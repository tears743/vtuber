"""
Step 0.6: Audio Transcriber - 视频音频转文字

通过 WSL + CUDA 调用 faster-whisper (large-v3) 识别视频语音。
RTX 4090 CUDA 加速，9 分钟视频约 47 秒出结果。

特点：
- 支持中文/英文/中英混搭
- 带时间戳
- VAD 过滤静音段
- 通过 WSL subprocess 调用，不影响 Windows 环境

依赖 (WSL):
- faster-whisper
- CUDA toolkit
"""
import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# WSL 内执行的 Python 转录脚本
WSL_TRANSCRIBE_SCRIPT = r'''
import json
import sys
import time

video_path = sys.argv[1]
output_path = sys.argv[2]
model_size = sys.argv[3] if len(sys.argv) > 3 else "large-v3"
language = sys.argv[4] if len(sys.argv) > 4 else "zh"

from faster_whisper import WhisperModel

model = WhisperModel(model_size, device="cuda", compute_type="float16")

t0 = time.time()
segments_iter, info = model.transcribe(
    video_path,
    beam_size=5,
    language=language,
    condition_on_previous_text=True,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
)

segments = []
text_parts = []
for seg in segments_iter:
    segments.append({
        "start": round(seg.start, 2),
        "end": round(seg.end, 2),
        "text": seg.text.strip(),
    })
    text_parts.append(seg.text.strip())

# 合并短句：间隔 > 1.5s 或累计 > 50 字时断开
merged = []
buf_start = None
buf_end = None
buf_text = ""

for seg in segments:
    if buf_start is None:
        buf_start = seg["start"]
        buf_end = seg["end"]
        buf_text = seg["text"]
        continue
    
    gap = seg["start"] - buf_end
    # 断句条件: 静音间隔 > 1.5s 或 累计文字 > 50 字
    if gap > 1.5 or len(buf_text) > 50:
        merged.append({
            "start": round(buf_start, 2),
            "end": round(buf_end, 2),
            "duration": round(buf_end - buf_start, 2),
            "text": buf_text,
        })
        buf_start = seg["start"]
        buf_end = seg["end"]
        buf_text = seg["text"]
    else:
        buf_end = seg["end"]
        buf_text += seg["text"]

if buf_text:
    merged.append({
        "start": round(buf_start, 2),
        "end": round(buf_end, 2),
        "duration": round(buf_end - buf_start, 2),
        "text": buf_text,
    })

result = {
    "text": "".join(text_parts),
    "segments": merged,
    "raw_segments": segments,  # 原始 whisper 粒度的时间戳
    "duration_s": round(info.duration, 1),
    "elapsed_s": round(time.time() - t0, 1),
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"OK: {len(segments)} raw -> {len(merged)} merged, {result['duration_s']}s, {result['elapsed_s']}s elapsed")
'''


class AudioTranscriber:
    """视频音频转录 - WSL + faster-whisper (CUDA)"""
    
    def __init__(self, model_size: str = "large-v3", language: str = "zh",
                 hf_token: str = ""):
        self.model_size = model_size
        self.language = language
        self.hf_token = hf_token
    
    def transcribe_all(self, media_dir: Path, manifest_path: Path) -> dict:
        """
        遍历 manifest 中有视频的条目，转录音频
        结果写入 manifest.json 的 video.transcript / video.segments 字段
        """
        if not manifest_path.exists():
            logger.error("[transcriber] manifest.json 不存在")
            return {}
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        # 收集需要转录的视频
        tasks = []
        for source_file, item in manifest.items():
            video = item.get("video")
            if not video:
                continue
            
            if isinstance(video, str):
                video_path = Path(video)
            elif isinstance(video, dict):
                # 已转录过的跳过：有 transcript_text 字段表示之前跑过转录
                # （即使结果为空字符串也算，说明视频无人声）
                if "transcript_text" in video:
                    continue
                video_path = Path(video.get("path", ""))
            else:
                continue
            
            if not video_path.exists():
                video_path = media_dir / video_path
            
            if video_path.exists():
                tasks.append((source_file, video_path))
        
        if not tasks:
            logger.info("[transcriber] 无视频需要转录")
            return manifest
        
        logger.info(f"[transcriber] {len(tasks)} 个视频待转录")
        
        for source_file, video_path in tasks:
            logger.info(f"[transcriber] 转录中: {video_path.name}")
            result = self._transcribe_via_wsl(video_path)
            
            if not result:
                logger.warning(f"[transcriber] 转录失败: {video_path.name}")
                continue
            
            # 写回 manifest
            video_item = manifest[source_file].get("video", {})
            if isinstance(video_item, str):
                video_item = {"path": video_item}
            
            video_item["transcript"] = result["segments"]  # 带时间戳的结构化转录
            video_item["transcript_text"] = result["text"]  # 纯文本备用
            video_item["raw_segments"] = result["raw_segments"]  # whisper原始粒度
            video_item["duration_s"] = result["duration_s"]
            manifest[source_file]["video"] = video_item
            
            logger.info(
                f"[transcriber] {video_path.name}: "
                f"{result['duration_s']}s, {len(result['segments'])} 段, "
                f"耗时 {result.get('elapsed_s', '?')}s, "
                f"前50字: {result['text'][:50]}"
            )
        
        # 保存
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[transcriber] 完成: 转录 {len(tasks)} 个视频")
        return manifest
    
    def _transcribe_via_wsl(self, video_path: Path) -> dict | None:
        """通过 WSL 调用 faster-whisper 转录"""
        try:
            # Windows 路径 → WSL 路径
            wsl_video = self._to_wsl_path(video_path)
            
            # 临时输出文件
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, 
                                              dir=video_path.parent)
            tmp.close()
            tmp_path = Path(tmp.name)
            wsl_tmp = self._to_wsl_path(tmp_path)
            
            # 写临时 Python 脚本
            script_tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False,
                                                      dir=video_path.parent, mode="w",
                                                      encoding="utf-8")
            script_tmp.write(WSL_TRANSCRIBE_SCRIPT)
            script_tmp.close()
            wsl_script = self._to_wsl_path(Path(script_tmp.name))
            
            # 构建命令
            env_prefix = ""
            if self.hf_token:
                env_prefix = f"export HF_TOKEN={self.hf_token} && "
            
            cmd = (
                f'wsl bash -c "{env_prefix}'
                f'python3 {wsl_script} {wsl_video} {wsl_tmp} '
                f'{self.model_size} {self.language}"'
            )
            
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=600,  # 10 分钟超时
                encoding="utf-8", errors="replace",
            )
            
            # 清理脚本
            Path(script_tmp.name).unlink(missing_ok=True)
            
            if result.returncode != 0:
                logger.warning(f"[transcriber] WSL 执行失败: {result.stderr[:300]}")
                tmp_path.unlink(missing_ok=True)
                return None
            
            logger.debug(f"[transcriber] WSL 输出: {result.stdout.strip()}")
            
            # 读取结果
            if tmp_path.exists():
                with open(tmp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tmp_path.unlink(missing_ok=True)
                return data
            
            return None
            
        except subprocess.TimeoutExpired:
            logger.warning(f"[transcriber] 转录超时: {video_path.name}")
            return None
        except Exception as e:
            logger.warning(f"[transcriber] 转录异常: {e}")
            return None
    
    @staticmethod
    def _to_wsl_path(win_path: Path) -> str:
        """Windows 路径转 WSL 路径: D:\\foo\\bar → /mnt/d/foo/bar"""
        s = str(win_path.resolve())
        drive = s[0].lower()
        rest = s[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
