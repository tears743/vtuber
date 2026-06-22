"""
Step 1: TTS Generation - VoxCPM2 四川话语音合成

调用 WSL 中部署的 VoxCPM2 HTTP Server (port 8808)
生成四川方言口播音频，返回 WAV 路径和实际时长
"""
import re
import json
import logging
import requests
import struct
import wave
from pathlib import Path

logger = logging.getLogger(__name__)


def get_wav_duration_ms(wav_path: Path) -> int:
    """读取 WAV 文件的实际时长（毫秒）"""
    with wave.open(str(wav_path), 'rb') as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate == 0:
            return 0
        return int(frames / rate * 1000)


def clean_tts_text(text: str) -> str:
    """清洗文本，移除不适合 TTS 的字符"""
    # 转义序列
    text = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Markdown 格式
    text = re.sub(r'[*#_~`>|\\]', '', text)
    # Markdown 链接
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # Emoji
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U0001f900-\U0001f9FF\U0001fa00-\U0001fa6f\U0001fa70-\U0001faff\U00002702-\U000027B0]', '', text)
    # 括号内短指令
    text = re.sub(r'[\(（][^\)）]{0,20}[\)）]', '', text)
    text = re.sub(r'[【\[][^】\]]{0,20}[】\]]', '', text)
    # 多余标点重复
    text = re.sub(r'([。！？…，、；：])\1+', r'\1', text)
    # 多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class VoxCPMTTS:
    """VoxCPM2 TTS 引擎 - 通过 HTTP 调用 WSL 服务"""
    
    def __init__(
        self,
        url: str = "http://127.0.0.1:8808",
        dialect: str = "四川话",
        cfg_value: float = 3.0,
        inference_timesteps: int = 32,
        speed: str = "快",
    ):
        self.url = url.rstrip("/")
        self.dialect = dialect
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        self.speed = speed  # "快"/"慢"/"正常"
    
    def check_health(self) -> bool:
        """检查 TTS 服务是否可用"""
        try:
            resp = requests.get(f"{self.url}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
    
    def synthesize(self, text: str, output_path: Path) -> tuple[Path, int]:
        """
        合成语音
        
        Args:
            text: 四川话台词
            output_path: 输出 WAV 文件路径
            
        Returns:
            (wav_path, duration_ms)
        """
        cleaned = clean_tts_text(text)
        
        if len(cleaned) <= 1:
            logger.warning(f"[tts] 文本过短，跳过: '{text[:30]}'")
            # 生成 0.1s 静音
            self._write_silence(output_path, 100)
            return output_path, 100
        
        payload = {
            "text": cleaned,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
        }
        
        if self.dialect:
            ctrl = self.dialect
            if self.speed and self.speed != "正常":
                ctrl += f"，语速{self.speed}一点"
            payload["control_instruction"] = ctrl
        
        logger.info(f"[tts] 合成: '{cleaned[:40]}...' -> {output_path.name}")
        
        try:
            resp = requests.post(
                f"{self.url}/generate",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            
            # 保存 WAV
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            
            duration_ms = get_wav_duration_ms(output_path)
            logger.info(f"[tts] ✅ {output_path.name}: {duration_ms}ms")
            return output_path, duration_ms
            
        except requests.Timeout:
            logger.error(f"[tts] 超时: '{cleaned[:30]}'")
            self._write_silence(output_path, 2000)
            return output_path, 2000
        except Exception as e:
            logger.error(f"[tts] 错误: {e}")
            self._write_silence(output_path, 1000)
            return output_path, 1000
    
    def synthesize_script(self, script: dict, audio_dir: Path) -> dict[int, int]:
        """
        为一个脚本的所有 voice 轨条目生成音频
        
        支持两种格式：
        - 新格式 (tracks.voice): [{text, subtitle, start_ms, duration_ms}]
        - 旧格式 (segments): [{type: "live2d_talk", text, ...}]
        
        Returns:
            {voice_index: duration_ms}
        """
        audio_dir.mkdir(parents=True, exist_ok=True)
        durations = {}
        
        # 新格式: tracks.voice
        tracks = script.get("tracks")
        if tracks and "voice" in tracks:
            voice_items = tracks["voice"]
            for i, item in enumerate(voice_items):
                text = item.get("text", "")
                if not text:
                    continue
                
                wav_path = audio_dir / f"voice_{i:02d}.wav"
                _, duration_ms = self.synthesize(text, wav_path)
                durations[i] = duration_ms
            return durations
        
        # 兼容旧格式: segments
        for i, seg in enumerate(script.get("segments", [])):
            if seg.get("type") != "live2d_talk":
                continue
            
            text = seg.get("text", "")
            if not text:
                continue
            
            wav_path = audio_dir / f"seg_{i:02d}.wav"
            _, duration_ms = self.synthesize(text, wav_path)
            durations[i] = duration_ms
        
        return durations
    
    def _write_silence(self, path: Path, duration_ms: int):
        """生成静音 WAV 文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24000
        num_samples = int(sample_rate * duration_ms / 1000)
        
        with wave.open(str(path), 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b'\x00\x00' * num_samples)

    def _apply_speed(self, wav_path: Path) -> Path:
        """用 FFmpeg atempo 加速音频"""
        import subprocess
        tmp_path = wav_path.with_suffix(".tmp.wav")
        cmd = [
            "ffmpeg", "-y", "-i", str(wav_path),
            "-filter:a", f"atempo={self.speed}",
            "-ac", "1", "-ar", "24000",
            str(tmp_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=30, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                tmp_path.replace(wav_path)
            else:
                logger.warning(f"[tts] atempo失败: {result.stderr[:100]}")
                if tmp_path.exists():
                    tmp_path.unlink()
        except Exception as e:
            logger.warning(f"[tts] atempo异常: {e}")
            if tmp_path.exists():
                tmp_path.unlink()
        return wav_path
