"""
Fish Audio TTS client.

The node uses this wrapper so the rest of the pipeline can keep the same
ScriptsData -> AudioData contract as the existing VoxCPM TTS node.
"""
import base64
import json
import logging
import re
import socket
import subprocess
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    import msgpack
except Exception:  # pragma: no cover - handled with a runtime error.
    msgpack = None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_BASE = "http://127.0.0.1:8080"
DEFAULT_REFERENCE_AUDIO = PROJECT_ROOT / "data" / "tools" / "fish_audio_tts" / "default_reference.mp3"
DEFAULT_STARTUP_LOG = PROJECT_ROOT / "data" / "tools" / "fish_audio_tts" / "logs" / "fish_api_startup.log"
DEFAULT_STARTUP_COMMAND = (
    "if [ -f /home/tears/fish-speech/tools/api_server.py ]; then cd /home/tears/fish-speech; "
    "elif [ -f /mnt/d/fish-speech/tools/api_server.py ]; then cd /mnt/d/fish-speech; "
    "elif [ -f /mnt/d/FishSpeech/tools/api_server.py ]; then cd /mnt/d/FishSpeech; "
    "elif [ -f /mnt/d/workspace/fish-speech/tools/api_server.py ]; then cd /mnt/d/workspace/fish-speech; "
    "elif [ -f /mnt/d/workspace/FishSpeech/tools/api_server.py ]; then cd /mnt/d/workspace/FishSpeech; "
    "fi; "
    "if [ ! -f tools/api_server.py ]; then "
    "echo 'Fish Speech repo not found. Set startup_command to the correct repo path.' >&2; exit 2; "
    "fi; "
    "export TORCH_MATMUL_PRECISION=high; "
    "if [ -x .venv/bin/python ]; then "
    ".venv/bin/python tools/api_server.py "
    "--llama-checkpoint-path checkpoints/s2-pro "
    "--decoder-checkpoint-path checkpoints/s2-pro/codec.pth "
    "--listen 0.0.0.0:8080; "
    "else "
    "python3 tools/api_server.py "
    "--llama-checkpoint-path checkpoints/s2-pro "
    "--decoder-checkpoint-path checkpoints/s2-pro/codec.pth "
    "--listen 0.0.0.0:8080; "
    "fi"
)


def get_wav_duration_ms(wav_path: Path) -> int:
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate == 0:
            return 0
        return int(frames / rate * 1000)


def clean_tts_text(text: str) -> str:
    text = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(r"[*#_~`>|\\]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        r"\U0001F1E0-\U0001F1FF\U0001f900-\U0001f9FF\U0001fa00-\U0001fa6f"
        r"\U0001fa70-\U0001faff\U00002702-\U000027B0]",
        "",
        text,
    )
    text = re.sub(r"([。！？…，、；：])\1+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


class FishAudioTTS:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        api_key: str = "",
        model: str = "",
        reference_id: str = "",
        reference_audio: str = "",
        reference_text: str = "",
        language: str = "zh",
        output_format: str = "wav",
        timeout: int = 180,
        auto_start: bool = True,
        wsl_distro: str = "Ubuntu",
        startup_command: str = "",
        startup_log: str = "",
        startup_wait_seconds: int = 240,
        startup_poll_seconds: int = 5,
        max_new_tokens: int = 1024,
        chunk_length: int = 200,
        top_p: float = 0.7,
        temperature: float = 0.7,
        repetition_penalty: float = 1.2,
        normalize: bool = True,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.reference_id = reference_id
        self.reference_audio = reference_audio or str(DEFAULT_REFERENCE_AUDIO)
        self.reference_text = reference_text
        self.language = language
        self.output_format = output_format or "wav"
        self.timeout = timeout
        self.auto_start = _as_bool(auto_start)
        self.wsl_distro = wsl_distro
        self.startup_command = startup_command or DEFAULT_STARTUP_COMMAND
        self.startup_log = startup_log or str(DEFAULT_STARTUP_LOG)
        self.startup_wait_seconds = int(startup_wait_seconds or 240)
        self.startup_poll_seconds = max(1, int(startup_poll_seconds or 5))
        self.max_new_tokens = int(max_new_tokens or 1024)
        self.chunk_length = int(chunk_length or 200)
        self.top_p = float(top_p or 0.7)
        self.temperature = float(temperature or 0.7)
        self.repetition_penalty = float(repetition_penalty or 1.2)
        self.normalize = _as_bool(normalize)

    def check_health(self) -> bool:
        if self._is_official_api():
            return bool(self.api_key)

        for path in ("/health", "/v1/health"):
            try:
                resp = requests.get(f"{self.api_base}{path}", headers=self._headers(), timeout=5)
                if resp.status_code < 500:
                    return True
            except Exception:
                continue
        return self._tcp_ready(timeout=2.0)

    def synthesize_script(self, script: dict, audio_dir: Path, progress_callback=None) -> dict[int, int]:
        audio_dir.mkdir(parents=True, exist_ok=True)
        durations = {}
        tracks = script.get("tracks")
        if tracks and "voice" in tracks:
            voice_items = tracks.get("voice", [])
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

    def synthesize(self, text: str, output_path: Path) -> tuple[Path, int]:
        cleaned = clean_tts_text(text)
        if len(cleaned) <= 1:
            logger.warning("[fish_tts] 文本过短，写入静音: %r", text[:30])
            self._write_silence(output_path, 100)
            return output_path, 100

        logger.info("[fish_tts] 合成: %r -> %s", cleaned[:40] + "...", output_path.name)
        audio_bytes = self._request_audio(cleaned)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        output_path = self._ensure_wav(output_path)
        duration_ms = get_wav_duration_ms(output_path)
        logger.info("[fish_tts] ✅ %s: %sms", output_path.name, duration_ms)
        return output_path, duration_ms

    def _headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request_audio(self, text: str) -> bytes:
        if self._is_official_api():
            return self._request_official_audio(text)

        self._ensure_server_ready()
        return self._request_local_audio(text)

    def _request_official_audio(self, text: str) -> bytes:
        if not self.api_key:
            raise RuntimeError(
                "Fish Audio 官方 API 缺少 API Key。请在 Fish TTS 节点 api_key、"
                "config.yaml 的 tts.fish.api_key，或环境变量 FISH_AUDIO_API_KEY 中配置；"
                "如果使用本地 Fish Speech，请把服务地址设为 http://127.0.0.1:8080。"
            )

        payload = {
            "text": text,
            "format": self.output_format,
            "normalize": True,
            "latency": "normal",
        }
        if self.model:
            payload["model"] = self.model
        if self.language:
            payload["language"] = self.language
        if self.reference_id:
            payload["reference_id"] = self.reference_id
        else:
            reference = self._reference_payload()
            if reference:
                payload["references"] = [reference]

        endpoint = "/v1/tts"
        resp = requests.post(
            f"{self.api_base}{endpoint}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            if resp.status_code == 401:
                raise RuntimeError("Fish Audio 官方 API 鉴权失败，请检查 api_key 是否已配置且有效。")
            raise RuntimeError(f"Fish Audio request failed: HTTP {resp.status_code}: {resp.text[:500]}")
        return self._extract_audio_bytes(resp)

    def _request_local_audio(self, text: str) -> bytes:
        if msgpack is None:
            raise RuntimeError("本地 Fish Speech 调用需要安装 msgpack Python 包。")

        references = []
        if not self.reference_id:
            references.append(self._reference_msgpack_payload())

        payload = {
            "text": text,
            "references": references,
            "reference_id": self.reference_id or None,
            "format": self.output_format,
            "max_new_tokens": self.max_new_tokens,
            "chunk_length": self.chunk_length,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
            "temperature": self.temperature,
            "streaming": False,
            "use_memory_cache": "on",
            "seed": None,
            "normalize": self.normalize,
            "language": self.language,
        }

        resp = requests.post(
            f"{self.api_base}/v1/tts",
            data=msgpack.packb(payload, use_bin_type=True),
            headers={
                "Content-Type": "application/msgpack",
                "Accept": "audio/wav, audio/*, application/octet-stream",
            },
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Fish Speech request failed: HTTP {resp.status_code}: {resp.text[:1000]}")
        return resp.content

    def _reference_payload(self) -> dict | None:
        if not self.reference_audio:
            return None
        path = Path(self.reference_audio)
        if not path.exists():
            logger.warning("[fish_tts] 参考音频不存在: %s", path)
            return None
        audio_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "audio": audio_b64,
            "text": self.reference_text or "",
        }

    def _reference_msgpack_payload(self) -> dict:
        path = Path(self.reference_audio)
        if not path.exists():
            raise FileNotFoundError(f"Fish Speech 参考音频不存在: {path}")
        return {
            "audio": path.read_bytes(),
            "text": self.reference_text or "",
        }

    def _is_official_api(self) -> bool:
        return "api.fish.audio" in (urlparse(self.api_base).netloc or "").lower()

    def _tcp_ready(self, timeout: float = 2.0) -> bool:
        parsed = urlparse(self.api_base)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _ensure_server_ready(self) -> None:
        if self.check_health():
            return
        if not self.auto_start:
            raise RuntimeError(f"Fish Speech 本地服务不可用: {self.api_base}")

        status = self._start_wsl_service()
        if status.get("server_ready"):
            return

        exit_detail = ""
        if "process_exit_code" in status:
            exit_detail = f" WSL 进程提前退出，退出码 {status['process_exit_code']}。"
        raise RuntimeError(
            "Fish Speech 本地服务启动失败。"
            f"已等待 {status.get('server_ready_after_seconds')} 秒；"
            f"请检查 WSL、startup_command、模型路径和 GPU 状态。日志: {status.get('startup_log')}.{exit_detail}"
        )

    def _start_wsl_service(self) -> dict:
        startup_log = Path(self.startup_log)
        if not startup_log.is_absolute():
            startup_log = PROJECT_ROOT / startup_log
        startup_log.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["wsl.exe"]
        if self.wsl_distro:
            cmd.extend(["-d", self.wsl_distro])
        cmd.extend(["--", "bash", "-lc", self.startup_command])

        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        log_file = startup_log.open("wb")
        log_file.write(f"Starting Fish Speech at {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode("utf-8"))
        log_file.flush()
        process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, creationflags=creationflags)

        waited = 0
        while waited < self.startup_wait_seconds:
            time.sleep(self.startup_poll_seconds)
            waited += self.startup_poll_seconds
            if self.check_health():
                return {
                    "server_ready": True,
                    "server_ready_after_seconds": waited,
                    "startup_log": str(startup_log),
                }
            exit_code = process.poll()
            if exit_code is not None:
                return {
                    "server_ready": False,
                    "server_ready_after_seconds": waited,
                    "startup_log": str(startup_log),
                    "process_exit_code": exit_code,
                }

        return {
            "server_ready": False,
            "server_ready_after_seconds": waited,
            "startup_log": str(startup_log),
        }

    def _extract_audio_bytes(self, resp: requests.Response) -> bytes:
        content_type = resp.headers.get("content-type", "").lower()
        if "application/json" not in content_type:
            return resp.content

        data = resp.json()
        for key in ("audio", "audio_data", "data"):
            value = data.get(key)
            if isinstance(value, str) and value:
                if value.startswith("data:"):
                    value = value.split(",", 1)[-1]
                return base64.b64decode(value)
        if isinstance(data.get("url"), str):
            audio_resp = requests.get(data["url"], timeout=self.timeout)
            audio_resp.raise_for_status()
            return audio_resp.content
        raise RuntimeError("Fish Audio response does not contain audio bytes: " + json.dumps(data)[:300])

    def _ensure_wav(self, path: Path) -> Path:
        if path.suffix.lower() == ".wav":
            try:
                get_wav_duration_ms(path)
                return path
            except Exception:
                pass

        import subprocess

        wav_path = path.with_suffix(".wav")
        tmp_path = wav_path.with_suffix(".tmp.wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", "24000", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg convert failed: {result.stderr[:300]}")
        tmp_path.replace(wav_path)
        if path != wav_path and path.exists():
            try:
                path.unlink()
            except Exception:
                pass
        return wav_path

    def _write_silence(self, path: Path, duration_ms: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24000
        num_samples = int(sample_rate * duration_ms / 1000)
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * num_samples)
