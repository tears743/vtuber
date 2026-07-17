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


LEADING_INSTRUCTION_PATTERN = re.compile(r'^\s*([（(][^）)]{1,40}[）)])\s*')


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
    leading_instruction = ""
    instruction_match = LEADING_INSTRUCTION_PATTERN.match(text)
    if instruction_match:
        leading_instruction = re.sub(r'\s+', ' ', instruction_match.group(1)).strip()
        text = text[instruction_match.end():]

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
    # 保留代码统一添加的首个指令，移除正文中残留的括号指令。
    text = re.sub(r'[\(（][^\)）]{0,20}[\)）]', '', text)
    text = re.sub(r'[【\[][^】\]]{0,20}[】\]]', '', text)
    # 多余标点重复
    text = re.sub(r'([。！？…，、；：])\1+', r'\1', text)
    # 多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return f"{leading_instruction}{text}"


class VoxCPMTTS:
    """VoxCPM2 TTS 引擎 - 通过 HTTP 调用 WSL 服务"""
    
    def __init__(
        self,
        url: str = "http://127.0.0.1:8808",
        dialect: str = "四川话",
        cfg_value: float = 2.0,
        inference_timesteps: int = 32,
        speed: str = "快",
        customize: bool = True,
    ):
        self.url = url.rstrip("/")
        self.dialect = dialect
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        self.speed = speed  # "快"/"慢"/"正常"
        self.customize = bool(customize)
    
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
        instruction_match = LEADING_INSTRUCTION_PATTERN.match(cleaned)
        if not self.customize and instruction_match:
            cleaned = cleaned[instruction_match.end():].lstrip()
            instruction_match = None
        spoken_text = cleaned[instruction_match.end():] if instruction_match else cleaned

        if len(spoken_text.strip()) <= 1:
            logger.warning(f"[tts] 文本过短，跳过: '{text[:30]}'")
            # 生成 0.1s 静音
            self._write_silence(output_path, 100)
            return output_path, 100
        
        payload = {
            "text": cleaned,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
        }

        if not self.customize:
            payload["control_instruction"] = ""
        elif self.dialect and not LEADING_INSTRUCTION_PATTERN.match(cleaned):
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
            
            # TTS 幻觉检测：中文语速约 4-6 字/秒，上限按 800ms/字计算
            # 如果音频时长远超文本合理长度，说明模型产生了重复/幻觉
            max_reasonable_ms = max(len(cleaned) * 800, 3000)  # 至少 3 秒
            if duration_ms > max_reasonable_ms:
                logger.warning(
                    f"[tts] ⚠️ 幻觉检测: {output_path.name} "
                    f"时长 {duration_ms}ms 超过合理上限 {max_reasonable_ms}ms "
                    f"(文本 {len(cleaned)} 字), 截断音频"
                )
                # 用 ffmpeg 截断到合理时长
                import subprocess
                truncated_path = output_path.with_suffix(".trunc.wav")
                trim_cmd = [
                    "ffmpeg", "-y", "-i", str(output_path),
                    "-t", str(max_reasonable_ms / 1000),
                    "-ac", "1", str(truncated_path),
                ]
                try:
                    subprocess.run(
                        trim_cmd, capture_output=True, text=True,
                        timeout=15, encoding="utf-8", errors="replace",
                    )
                    if truncated_path.exists():
                        truncated_path.replace(output_path)
                        duration_ms = get_wav_duration_ms(output_path)
                        logger.info(f"[tts] ✅ 截断后: {output_path.name}: {duration_ms}ms")
                except Exception as trim_e:
                    logger.warning(f"[tts] 截断失败: {trim_e}")
                    if truncated_path.exists():
                        truncated_path.unlink()
            else:
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
    
    def synthesize_script(self, script: dict, audio_dir: Path, progress_callback=None) -> dict[int, int]:
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
                if text:
                    wav_path = audio_dir / f"voice_{i:02d}.wav"
                    _, duration_ms = self.synthesize(text, wav_path)
                    durations[i] = duration_ms
                if progress_callback:
                    progress_callback(
                        f"生成语音 [{i + 1}/{len(voice_items)}]",
                        (i + 1) / max(len(voice_items), 1),
                    )
            return durations
        
        # 兼容旧格式: segments
        segments = script.get("segments", [])
        for i, seg in enumerate(segments):
            if seg.get("type") != "live2d_talk":
                continue
            
            text = seg.get("text", "")
            if not text:
                continue
            
            wav_path = audio_dir / f"seg_{i:02d}.wav"
            _, duration_ms = self.synthesize(text, wav_path)
            durations[i] = duration_ms
            if progress_callback:
                progress_callback(
                    f"生成语音 [{i + 1}/{len(segments)}]",
                    (i + 1) / max(len(segments), 1),
                )
        
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
