"""
Step 0.5: Media Recognizer - 素材识别

用 mimo-v2.5-pro (vision) 识别下载的图片内容，
把识别结果写入 manifest.json，供 Director 脚本生成时引用。

识别内容：
- 图片: 场景描述、文字内容(OCR)、关键物体
- 视频: 时长、关键帧描述（TODO）
"""
import json
import base64
import logging
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from openai import OpenAI

logger = logging.getLogger(__name__)

# 图片质量阈值
MIN_WIDTH = 200       # 最小宽度 px
MIN_HEIGHT = 200      # 最小高度 px
MIN_FILE_SIZE = 10240 # 最小文件大小 10KB
MAX_CONCURRENCY = 10  # 最大并发数

RECOGNITION_PROMPT = """你是一个专业的视觉素材分析师。请对这张图片进行详细描述，供短视频脚本编剧参考。

请包含以下维度（尽量详细，100-150字）：
1. 【主体】画面中心是什么？人物/物体/场景？数量、动作、状态
2. 【文字】如果图中有文字（标题、评论、水印等），完整提取出来
3. 【构图】拍摄角度、画面布局（横屏/竖屏截图/九宫格等）
4. 【色调】主色调、光线、视觉风格（写实/卡通/截图/新闻配图）
5. 【情绪】画面传达的情绪或氛围（搞笑/严肃/震惊/温馨）
6. 【来源判断】这可能是什么类型的图（微博截图/新闻配图/表情包/实拍照片/示意图）

格式：直接输出描述段落，不要编号，不要 JSON。"""


class MediaRecognizer:
    """用 Vision 模型识别素材内容"""
    
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
    
    def recognize_all(self, media_dir: Path, manifest_path: Path) -> dict:
        """
        识别 media/ 中的所有素材，更新 manifest.json
        并发识别，最大 10 张同时进行
        """
        # 加载现有 manifest
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {}
        
        # ── Phase 1: 收集所有需要识别的图片任务 ──
        tasks = []  # [(source_file, img_path_str, img_path, quality)]
        
        for source_file, item in manifest.items():
            images = item.get("images", [])
            
            for img_item in images:
                # 兼容两种格式
                if isinstance(img_item, dict):
                    img_path_str = img_item.get("path", "")
                else:
                    img_path_str = img_item
                
                if not img_path_str:
                    continue
                
                img_path = Path(img_path_str)
                if not img_path.exists():
                    img_path = media_dir / img_path_str
                
                if not img_path.exists():
                    continue
                
                # 质量检查
                quality = self._check_image_quality(img_path)
                if not quality["usable"]:
                    logger.debug(f"[recognizer] 跳过低质量图: {img_path.name} ({quality['reason']})")
                    continue
                
                tasks.append((source_file, img_path_str, img_path, quality))
        
        logger.info(f"[recognizer] 共 {len(tasks)} 张图片待识别 (并发: {MAX_CONCURRENCY})")
        
        # ── Phase 2: 并发识别 ──
        results = {}  # {(source_file, img_path_str): {path, width, height, size_kb, description}}
        
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
            future_map = {}
            for source_file, img_path_str, img_path, quality in tasks:
                future = executor.submit(self._recognize_image, img_path)
                future_map[future] = (source_file, img_path_str, img_path, quality)
            
            done_count = 0
            for future in as_completed(future_map):
                source_file, img_path_str, img_path, quality = future_map[future]
                done_count += 1
                
                try:
                    description = future.result()
                except Exception as e:
                    description = f"识别失败: {type(e).__name__}"
                
                key = (source_file, img_path_str)
                results[key] = {
                    "path": img_path_str,
                    "width": quality["width"],
                    "height": quality["height"],
                    "size_kb": quality["size_kb"],
                    "description": description,
                }
                logger.info(
                    f"[recognizer] [{done_count}/{len(tasks)}] "
                    f"{img_path.name} ({quality['width']}x{quality['height']}): "
                    f"{description[:50]}"
                )
        
        # ── Phase 3: 写回 manifest ──
        for source_file, item in manifest.items():
            recognized_images = []
            images = item.get("images", [])
            
            for img_item in images:
                if isinstance(img_item, dict):
                    img_path_str = img_item.get("path", "")
                else:
                    img_path_str = img_item
                
                key = (source_file, img_path_str)
                if key in results:
                    recognized_images.append(results[key])
            
            item["images"] = recognized_images
            
            # 视频识别（获取时长）
            video_path = item.get("video")
            if video_path:
                if isinstance(video_path, str):
                    duration_s = self._get_video_duration(Path(video_path))
                    item["video"] = {
                        "path": video_path,
                        "duration_s": duration_s,
                        "requires_browser": "douyin" in source_file,
                    }
        
        # 保存
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[recognizer] 完成: 识别 {len(results)} 张图片")
        return manifest
    
    def _recognize_image(self, img_path: Path, max_retries: int = 2) -> str:
        """用 vision 模型识别单张图片，空结果自动重试"""
        # 读取图片转 base64
        with open(img_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        
        # 确定 MIME type
        suffix = img_path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", 
                   ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/jpeg")
        
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": RECOGNITION_PROMPT},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{mime_type};base64,{img_data}"
                            }},
                        ],
                    }],
                    max_tokens=131072,
                    temperature=0.1 + attempt * 0.1,  # 重试时稍微提高温度
                )
                
                result = response.choices[0].message.content.strip()
                if result:
                    return result
                
                if attempt < max_retries:
                    logger.debug(f"[recognizer] {img_path.name}: 空结果，重试 {attempt+1}/{max_retries}")
                    
            except Exception as e:
                if attempt < max_retries:
                    logger.debug(f"[recognizer] {img_path.name}: 失败 {e}，重试 {attempt+1}/{max_retries}")
                else:
                    logger.warning(f"[recognizer] 识别失败 {img_path.name}: {e}")
                    return f"识别失败: {type(e).__name__}"
        
        return "（模型未返回描述）"
    
    def _check_image_quality(self, img_path: Path) -> dict:
        """
        检查图片质量，过滤掉太小/模糊的图
        
        Returns:
            {"usable": bool, "width": int, "height": int, "size_kb": int, "reason": str}
        """
        try:
            file_size = img_path.stat().st_size
            size_kb = int(file_size / 1024)
            
            # 文件大小检查
            if file_size < MIN_FILE_SIZE:
                return {"usable": False, "width": 0, "height": 0, 
                        "size_kb": size_kb, "reason": f"文件太小 ({size_kb}KB < 10KB)"}
            
            # 尺寸检查
            with Image.open(img_path) as img:
                width, height = img.size
            
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return {"usable": False, "width": width, "height": height,
                        "size_kb": size_kb, "reason": f"分辨率太低 ({width}x{height})"}
            
            return {"usable": True, "width": width, "height": height, 
                    "size_kb": size_kb, "reason": ""}
            
        except Exception as e:
            return {"usable": False, "width": 0, "height": 0, 
                    "size_kb": 0, "reason": f"无法读取: {e}"}
    
    def _get_video_duration(self, video_path: Path) -> float | None:
        """获取视频时长（秒）"""
        if not video_path.exists():
            return None
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(video_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return round(float(result.stdout.strip()), 1)
        except Exception:
            pass
        return None

