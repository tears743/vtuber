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
        skipped = 0
        
        for source_file, item in manifest.items():
            images = item.get("images", [])
            
            for img_item in images:
                # 兼容两种格式
                if isinstance(img_item, dict):
                    img_path_str = img_item.get("path", "")
                    # 缓存判断：已有有效 description 则跳过
                    existing_desc = img_item.get("description", "")
                    if existing_desc and not existing_desc.startswith("识别失败"):
                        skipped += 1
                        continue
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
        
        if skipped > 0:
            logger.info(f"[recognizer] 跳过 {skipped} 张已识别的图片（缓存命中）")
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
                    # 本次新识别的，用结构化结果替换
                    recognized_images.append(results[key])
                else:
                    # 保留原始条目（已有 description 的缓存 或 纯路径字符串）
                    recognized_images.append(img_item)
            
            item["images"] = recognized_images
            
            # 视频识别（时长 + 内容理解）
            video_info = item.get("video")
            if video_info:
                if isinstance(video_info, str):
                    video_path_str = video_info
                elif isinstance(video_info, dict):
                    video_path_str = video_info.get("path", "")
                else:
                    video_path_str = ""
                
                # 已有完整识别结果则跳过（但被 rejected 的需要重试）
                already_done = (isinstance(video_info, dict) 
                                and video_info.get("duration_s") 
                                and video_info.get("summary")
                                and "rejected" not in video_info.get("summary", "").lower())
                
                if video_path_str and not already_done:
                    video_path = Path(video_path_str)
                    duration_s = self._get_video_duration(video_path)
                    
                    # 用 mimo 做视频内容理解
                    video_understanding = self._summarize_video(video_path, duration_s)
                    
                    summary = video_understanding.get("summary", "")
                    # 检测 API 安全策略拒绝
                    is_rejected = ("rejected" in summary.lower() 
                                   or "high risk" in summary.lower()
                                   or "unsafe" in summary.lower())
                    
                    if is_rejected:
                        logger.warning(f"[recognizer] ⚠️ API 安全策略拒绝: {video_path.name}, 将仅保留基础信息")
                        summary = ""
                    
                    item["video"] = {
                        "path": video_path_str,
                        "duration_s": duration_s,
                        "summary": summary,
                        # transcript_hint: recognizer 的纯文本预估，供参考
                        # transcript: 保留给 audio_transcriber 写入带时间戳的结构化数据
                        "transcript_hint": video_understanding.get("transcript", "") if not is_rejected else "",
                        "key_moments": video_understanding.get("key_moments", []) if not is_rejected else [],
                        "requires_browser": "douyin" in source_file,
                    }
            
            # README 识别：图片识别 + 内容总结
            readme_data = item.get("readme")
            if readme_data and isinstance(readme_data, dict):
                # 识别 README 中的图片（已有 recognized_images 则跳过）
                if not readme_data.get("recognized_images"):
                    readme_images = readme_data.get("images", [])
                    recognized_readme_imgs = []
                    for img_path_str in readme_images:
                        img_path = Path(img_path_str)
                        if img_path.exists():
                            quality = self._check_image_quality(img_path)
                            if quality["usable"]:
                                try:
                                    desc = self._recognize_image(img_path)
                                    recognized_readme_imgs.append({
                                        "path": img_path_str,
                                        "width": quality["width"],
                                        "height": quality["height"],
                                        "description": desc,
                                    })
                                except Exception:
                                    pass
                    
                    if recognized_readme_imgs:
                        readme_data["recognized_images"] = recognized_readme_imgs
                
                # 总结 README 内容
                readme_path = Path(readme_data.get("path", ""))
                if readme_path.exists() and not readme_data.get("summary"):
                    try:
                        readme_text = readme_path.read_text(encoding="utf-8")[:15000]
                        summary = self._summarize_readme(readme_text)
                        if summary:
                            readme_data["summary"] = summary
                    except Exception as e:
                        logger.debug(f"[recognizer] README 总结失败: {e}")
        
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
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and result.stdout.strip():
                return round(float(result.stdout.strip()), 1)
        except Exception:
            pass
        return None
    
    # Base64 上限: 50MB 编码后 → 原文件约 37MB
    VIDEO_BASE64_MAX_BYTES = 37 * 1024 * 1024
    
    def _summarize_video(self, video_path: Path, duration_s: float | None = None) -> dict:
        """
        用 mimo-v2.5 做视频内容理解。
        
        限制:
        - Base64 编码后不超过 50MB
        - 格式: MP4/MOV/AVI/WMV
        - fps: [0.1, 10], 默认 2
        
        Returns:
            {"summary": "...", "transcript": "...", "key_moments": [...]}
        """
        if not video_path.exists():
            return {}
        
        file_size = video_path.stat().st_size
        
        # 超过 37MB 需要压缩
        actual_path = video_path
        compressed = None
        if file_size > self.VIDEO_BASE64_MAX_BYTES:
            compressed = video_path.parent / f"{video_path.stem}_compressed.mp4"
            try:
                # 压缩到 720p + crf 28，控制在 37MB 以内
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(video_path),
                     "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28",
                     "-c:a", "aac", "-b:a", "64k", str(compressed)],
                    capture_output=True, text=True, timeout=120,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode == 0 and compressed.exists():
                    if compressed.stat().st_size <= self.VIDEO_BASE64_MAX_BYTES:
                        actual_path = compressed
                        logger.info(f"[recognizer] 视频压缩: {file_size/1024/1024:.1f}MB -> {compressed.stat().st_size/1024/1024:.1f}MB")
                    else:
                        logger.warning(f"[recognizer] 压缩后仍超限，跳过视频理解")
                        compressed.unlink(missing_ok=True)
                        return {}
                else:
                    logger.warning(f"[recognizer] 视频压缩失败")
                    return {}
            except Exception as e:
                logger.warning(f"[recognizer] 视频压缩异常: {e}")
                return {}
        
        # 读取并 base64 编码
        try:
            with open(actual_path, "rb") as f:
                video_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"[recognizer] 视频读取失败: {e}")
            if compressed and compressed.exists():
                compressed.unlink(missing_ok=True)
            return {}
        
        # 根据时长选择 fps
        if duration_s and duration_s > 30:
            fps = 1  # 长视频降低帧率
        else:
            fps = 2  # 短视频用默认
        
        prompt = """你是一名专业的短视频内容分析师。请对这段视频进行详细分析，供短视频脚本编剧参考。

请输出以下内容（JSON 格式）：
{
  "summary": "200-400字的视频内容总结，包含：主题是什么、画面展示了什么、传达了什么信息、情绪基调",
  "transcript": "如果视频中有人说话/旁白/字幕，尽可能还原完整的文字内容。如果没有语音则输出空字符串",
  "key_moments": [
    {"start": 0, "end": 5, "duration": 5, "description": "开头画面描述（这段时间内画面展示了什么）"},
    {"start": 5, "end": 15, "duration": 10, "description": "关键转折/重点画面描述"},
    ...（覆盖视频全程，相邻段首尾相连）
  ]
}

要求：
- summary 要具体描述画面内容，不要笼统概括
- transcript 优先还原口播/字幕文字，这对脚本编剧非常重要
- key_moments 必须覆盖视频**全部时长**（从0秒到结尾），分为 5-8 段，相邻段的 end 和下一段的 start 相等
- key_moments 每段的 description 描述该时间段内的画面内容、人物动作、字幕文字等
- 只输出 JSON，不要其他文字"""
        
        # 重试最多 3 次
        import re
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {
                                    "url": f"data:video/mp4;base64,{video_b64}"
                                },
                                "fps": fps,
                                "media_resolution": "default",
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }],
                    max_tokens=4096,
                    temperature=0.1,
                )
                
                result_text = response.choices[0].message.content.strip()
                
                # 尝试解析 JSON
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    logger.info(f"[recognizer] \u2705 视频理解: {video_path.name} ({len(parsed.get('summary',''))} chars)")
                    return parsed
                else:
                    # 无法解析 JSON，把整段文本当 summary
                    logger.info(f"[recognizer] 视频理解(非JSON): {video_path.name}")
                    return {"summary": result_text[:1000], "transcript": "", "key_moments": []}
                
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"[recognizer] 视频理解 attempt {attempt+1} JSON 解析失败: {video_path.name}: {e}")
            except Exception as e:
                last_error = e
                logger.warning(f"[recognizer] 视频理解 attempt {attempt+1} 异常: {video_path.name}: {e}")
            
            if attempt < 2:
                import time
                time.sleep(2)
        
        logger.error(f"[recognizer] 视频理解 3 次均失败: {video_path.name}: {last_error}")
        if compressed and compressed.exists():
            compressed.unlink(missing_ok=True)
        return {}
    
    def _summarize_readme(self, readme_text: str) -> str | None:
        """
        用 LLM 总结 README 内容，输出结构化摘要供 Director 使用。
        """
        prompt = """你是一名资深科技新闻编辑，擅长将开源项目提炼为观众感兴趣的科技新闻素材。请对以下 GitHub README 进行**详细的**结构化总结，供短视频脚本编剧参考。

请包含以下维度（总共 500-1000 字，越详细越好）：

1. 【一句话新闻标题】用新闻标题的方式概括为什么值得关注
2. 【项目定位】面向非技术观众解释：这个项目是做什么的、解决了什么痛点、目标用户是谁
3. 【核心功能详解】逐条列出 3-5 个最吸引人的功能：
   - 每个功能要说清楚具体做了什么、怎么做的
   - 如果有性能对比或 benchmark 数据，必须提取出具体数字
   - 说明这个功能对用户的实际价值
4. 【技术架构】
   - 技术栈（语言、框架、依赖的模型等）
   - 核心算法或方法论（如果 README 有提及）
   - 部署方式（本地/云端/Docker/pip install）
   - 支持的平台和环境
5. 【数据与性能】
   - Star 数、Fork 数、下载量等社区数据
   - 性能 benchmark（速度、准确率、资源占用等）
   - 支持的模型规模（参数量、训练数据量）
   - 对比竞品的优势数据
6. 【使用场景举例】2-3 个具体的使用场景，让观众能联想到自己的需求
7. 【为什么值得关注】结合当前 AI/技术趋势分析热门原因

格式要求：
- 使用自然段落形式输出，每个维度可以用【】标记开头
- 所有数字、数据必须精确引用自 README 原文，不要编造
- 如果某个维度 README 没有提及，可以跳过
- 输出中文
- 如果 README 内容不足以总结，输出"内容不足\""""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": f"{prompt}\n\n---\n\n{readme_text}"},
                ],
                max_tokens=10000,
                temperature=0.2,
            )
            
            result = response.choices[0].message.content.strip()
            if result and "内容不足" not in result:
                return result
            return None
            
        except Exception as e:
            logger.debug(f"[recognizer] README 总结 LLM 调用失败: {e}")
            return None

