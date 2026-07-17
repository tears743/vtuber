"""
Fish Audio TTS node.

It mirrors the existing tts node contract:
ScriptsData -> AudioData with data/<date>/audio/durations.json.
"""
import json
import logging
import os
from pathlib import Path

from server.models import AudioData, PipelineContext, ScriptsData
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register

logger = logging.getLogger(__name__)

DEFAULT_FISH_API_BASE = "http://127.0.0.1:8080"
DEFAULT_FISH_REFERENCE = "assets/voice/reference.mp3"


@register
class FishTTSNode(BaseNode):
    type = "fish_tts"
    label = "Fish Audio 语音合成"
    category = "音视频"
    description = "使用 Fish Audio / Fish Speech 兼容接口合成口播音频"
    icon = "🎙️"
    color = "#00A6A6"

    inputs = [
        NodeInput(
            name="scripts",
            type="ScriptsData",
            label="脚本",
            required=True,
            description="上游口播脚本。通常连接 director 或 AI 口播节点。",
        )
    ]
    outputs = [
        NodeOutput(
            name="audio",
            type="AudioData",
            label="音频",
            description="TTS 输出音频和 durations.json。",
        ),
        NodeOutput(
            name="scripts",
            type="ScriptsData",
            label="已回填脚本",
            description="已写入真实音频时长和 audio_file 路径的口播脚本。",
        ),
    ]

    reads = ["scripts"]
    writes = ["audio", "scripts"]
    output_dirs = ["audio"]

    config_schema = {
        "api_base": {
            "type": "str",
            "label": "服务地址",
            "default": DEFAULT_FISH_API_BASE,
            "description": "本地 Fish Speech 服务地址；也可填写 https://api.fish.audio 使用官方 API；也可用 FISH_AUDIO_API_BASE",
        },
        "api_key": {
            "type": "str",
            "label": "API Key",
            "default": "",
            "description": "官方 Fish Audio API 需要填写；也可用 FISH_AUDIO_API_KEY；本地服务可留空",
        },
        "model": {
            "type": "str",
            "label": "模型",
            "default": "",
            "description": "可选，传给 Fish Audio 的 model 字段；也可用 FISH_AUDIO_MODEL",
        },
        "reference_id": {
            "type": "str",
            "label": "参考音色 ID",
            "default": "",
            "description": "官方 Fish Audio 已创建的 reference_id；也可用 FISH_AUDIO_REFERENCE_ID；填写后优先使用",
        },
        "reference_audio": {
            "type": "str",
            "label": "参考音频",
            "default": DEFAULT_FISH_REFERENCE,
            "description": "没有 reference_id 时使用本地参考音频；缺失时会尝试从 Fish 工具或 VoxCPM 默认音频复制",
        },
        "reference_text": {
            "type": "text",
            "label": "参考音频文本",
            "default": "大家好，我是Mili，今天继续给大家摆一哈最近的新鲜事。",
            "description": "参考音频对应文本，可留空",
        },
        "language": {
            "type": "enum",
            "label": "语种",
            "default": "zh",
            "options": [
                {"value": "zh", "label": "中文"},
                {"value": "en", "label": "英文"},
                {"value": "ja", "label": "日文"},
                {"value": "ko", "label": "韩文"},
            ],
        },
        "output_format": {
            "type": "enum",
            "label": "输出格式",
            "default": "wav",
            "options": ["wav", "mp3", "opus"],
        },
        "timeout": {
            "type": "int",
            "label": "请求超时秒数",
            "default": 300,
            "min": 30,
            "max": 600,
        },
        "auto_start": {
            "type": "bool",
            "label": "自动启动本地服务",
            "default": True,
            "description": "本地 Fish Speech 不可用时，通过 WSL 自动启动；官方 API 不使用此项",
        },
        "wsl_distro": {
            "type": "str",
            "label": "WSL 发行版",
            "default": "Ubuntu",
            "description": "自动启动本地 Fish Speech 时使用的 WSL 发行版",
        },
        "startup_command": {
            "type": "text",
            "label": "启动命令",
            "default": "",
            "description": "可选；留空使用默认 Fish Speech 启动命令",
        },
        "startup_wait_seconds": {
            "type": "int",
            "label": "启动等待秒数",
            "default": 240,
            "min": 30,
            "max": 900,
        },
        "max_new_tokens": {
            "type": "int",
            "label": "生成 token 上限",
            "default": 1024,
            "min": 128,
            "max": 4096,
        },
        "chunk_length": {
            "type": "int",
            "label": "分块长度",
            "default": 200,
            "min": 50,
            "max": 400,
        },
        "top_p": {
            "type": "float",
            "label": "top_p",
            "default": 0.7,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
        },
        "temperature": {
            "type": "float",
            "label": "temperature",
            "default": 0.7,
            "min": 0.1,
            "max": 1.5,
            "step": 0.05,
        },
        "repetition_penalty": {
            "type": "float",
            "label": "重复惩罚",
            "default": 1.2,
            "min": 0.8,
            "max": 2.0,
            "step": 0.05,
        },
        "normalize": {
            "type": "bool",
            "label": "文本规范化",
            "default": True,
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import asyncio

        from agents.renderer.fish_tts import FishAudioTTS

        on_progress("初始化 Fish Audio TTS...", 0.0)

        tts_cfg = (ctx.config or {}).get("tts", {}).get("fish", {})
        api_key = self.get_config("api_key", "") or tts_cfg.get("api_key", "") or os.getenv("FISH_AUDIO_API_KEY", "")
        api_base = (
            self.get_config("api_base", "")
            or tts_cfg.get("api_base", "")
            or os.getenv("FISH_AUDIO_API_BASE", "")
            or DEFAULT_FISH_API_BASE
        )
        reference_audio = (
            self.get_config("reference_audio", "")
            or tts_cfg.get("reference_audio", "")
            or os.getenv("FISH_AUDIO_REFERENCE_AUDIO", "")
            or DEFAULT_FISH_REFERENCE
        )
        reference_audio = self._resolve_reference_audio(reference_audio)

        tts = FishAudioTTS(
            api_base=api_base,
            api_key=api_key,
            model=self.get_config("model", "") or tts_cfg.get("model", "") or os.getenv("FISH_AUDIO_MODEL", ""),
            reference_id=(
                self.get_config("reference_id", "")
                or tts_cfg.get("reference_id", "")
                or os.getenv("FISH_AUDIO_REFERENCE_ID", "")
            ),
            reference_audio=reference_audio,
            reference_text=(
                self.get_config("reference_text", "")
                or tts_cfg.get("reference_text", "")
                or os.getenv("FISH_AUDIO_REFERENCE_TEXT", "")
            ),
            language=self.get_config("language", "") or tts_cfg.get("language", "") or os.getenv("FISH_AUDIO_LANGUAGE", "zh"),
            output_format=self.get_config("output_format", "") or tts_cfg.get("output_format", "") or "wav",
            timeout=int(self.get_config("timeout", tts_cfg.get("timeout", 300))),
            auto_start=self.get_config("auto_start", tts_cfg.get("auto_start", True)),
            wsl_distro=self.get_config("wsl_distro", tts_cfg.get("wsl_distro", "Ubuntu")),
            startup_command=self.get_config("startup_command", tts_cfg.get("startup_command", "")),
            startup_log=self.get_config("startup_log", tts_cfg.get("startup_log", "")),
            startup_wait_seconds=int(self.get_config("startup_wait_seconds", tts_cfg.get("startup_wait_seconds", 240))),
            max_new_tokens=int(self.get_config("max_new_tokens", tts_cfg.get("max_new_tokens", 1024))),
            chunk_length=int(self.get_config("chunk_length", tts_cfg.get("chunk_length", 200))),
            top_p=float(self.get_config("top_p", tts_cfg.get("top_p", 0.7))),
            temperature=float(self.get_config("temperature", tts_cfg.get("temperature", 0.7))),
            repetition_penalty=float(self.get_config("repetition_penalty", tts_cfg.get("repetition_penalty", 1.2))),
            normalize=self.get_config("normalize", tts_cfg.get("normalize", True)),
        )

        if not tts.check_health():
            logger.warning("[fish_tts] 服务健康检查未通过，仍尝试直接合成")

        scripts = self.get_input("scripts") or ctx.scripts
        if scripts is None:
            raise RuntimeError("缺少 scripts 输入")

        scripts_dir = scripts.dir
        audio_dir = ctx.data_root / ctx.date / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        script_files = sorted(scripts_dir.glob("*.json"))
        all_durations = {}
        all_segments = {}

        for i, script_path in enumerate(script_files):
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)

            script_id = script.get("id", script_path.stem)
            script_audio_dir = audio_dir / script_id

            progress = 0.1 + 0.8 * (i / max(len(script_files), 1))
            on_progress(f"Fish TTS [{i + 1}/{len(script_files)}]: {script_id}", progress)

            script_span = 0.8 / max(len(script_files), 1)
            def report_voice(message, voice_progress, _script_id=script_id, _base=progress):
                on_progress(f"{_script_id}: {message}", _base + script_span * voice_progress)

            durations = await asyncio.to_thread(
                tts.synthesize_script,
                script,
                script_audio_dir,
                report_voice,
            )
            all_durations[script_id] = durations
            all_segments[script_id] = sorted(script_audio_dir.glob("voice_*.wav"))
            self._write_audio_metadata(script, script_path, script_audio_dir, durations, ctx)

        durations_path = audio_dir / "durations.json"
        with open(durations_path, "w", encoding="utf-8") as f:
            json.dump(all_durations, f, ensure_ascii=False, indent=2)

        ctx.audio = AudioData(
            dir=audio_dir,
            durations_path=durations_path,
            durations=all_durations,
            segments=all_segments,
        )
        ctx.scripts = self._load_scripts_data(scripts_dir)
        on_progress(f"Fish TTS 完成: {len(all_durations)} 个脚本", 1.0)
        return {"audio": ctx.audio, "scripts": ctx.scripts}

    def _write_audio_metadata(
        self,
        script: dict,
        script_path: Path,
        script_audio_dir: Path,
        durations: dict,
        ctx: PipelineContext,
    ) -> None:
        script_id = script.get("id", script_path.stem)
        tracks = script.setdefault("tracks", {})
        voice_items = tracks.get("voice", [])
        current_ms = 0

        if voice_items:
            for index, item in enumerate(voice_items):
                duration_ms = int(durations.get(index) or durations.get(str(index)) or item.get("duration_ms", 0) or 0)
                wav_path = script_audio_dir / f"voice_{index:02d}.wav"
                item["start_ms"] = current_ms
                item["duration_ms"] = duration_ms
                item["audio_file"] = self._relative_run_path(wav_path, ctx)
                item["audio_path"] = str(wav_path)
                current_ms += duration_ms
        else:
            for index, item in enumerate(script.get("segments", [])):
                if item.get("type") != "live2d_talk":
                    continue
                duration_ms = int(durations.get(index) or durations.get(str(index)) or item.get("duration_ms", 0) or 0)
                wav_path = script_audio_dir / f"seg_{index:02d}.wav"
                item["start_ms"] = current_ms
                item["duration_ms"] = duration_ms
                item["audio_file"] = self._relative_run_path(wav_path, ctx)
                item["audio_path"] = str(wav_path)
                current_ms += duration_ms

        script["total_duration_ms"] = current_ms
        meta = script.setdefault("meta", {})
        meta["duration_source"] = "fish_tts"
        meta["audio_dir"] = self._relative_run_path(script_audio_dir, ctx)
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    def _relative_run_path(self, path: Path, ctx: PipelineContext) -> str:
        run_root = ctx.data_root / ctx.date
        try:
            return str(path.relative_to(run_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _load_scripts_data(self, scripts_dir: Path) -> ScriptsData:
        script_files = sorted(scripts_dir.glob("*.json"))
        scripts = {}
        durations = {}
        for path in script_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            script_id = data.get("id", path.stem)
            scripts[script_id] = data
            durations[script_id] = data.get("total_duration_ms", 0)
        return ScriptsData(
            dir=scripts_dir,
            files=script_files,
            scripts=scripts,
            total_duration_ms=durations,
        )

    def _resolve_reference_audio(self, configured_path: str) -> str:
        path = Path(configured_path)
        if path.exists():
            return str(path)

        default_path = Path(DEFAULT_FISH_REFERENCE)
        if not configured_path or path == default_path or path.as_posix() == default_path.as_posix():
            default_path.parent.mkdir(parents=True, exist_ok=True)
            for candidate in (
                Path("data/tools/fish_audio_tts/default_reference.mp3"),
                Path("data/tools/fish_audio_tts/default_reference.wav"),
                Path("D:/VoxCPM/baoer.mp3"),
                Path("D:/workspace/VoxCPM/baoer.mp3"),
                Path.home() / "baoer.mp3",
            ):
                if candidate.exists():
                    default_path.write_bytes(candidate.read_bytes())
                    logger.info("[fish_tts] 已复制默认参考音频: %s -> %s", candidate, default_path)
                    return str(default_path)
        return configured_path

    def restore_cache(self, ctx: PipelineContext):
        audio_dir = ctx.data_root / ctx.date / "audio"
        durations_path = audio_dir / "durations.json"
        all_durations = {}
        if durations_path.exists():
            with open(durations_path, "r", encoding="utf-8") as f:
                all_durations = json.load(f)
        all_segments = {}
        for script_id in all_durations:
            script_audio_dir = audio_dir / script_id
            if script_audio_dir.exists():
                all_segments[script_id] = sorted(script_audio_dir.glob("voice_*.wav"))
        ctx.audio = AudioData(
            dir=audio_dir,
            durations_path=durations_path,
            durations=all_durations,
            segments=all_segments,
        )
        scripts_dir = ctx.data_root / ctx.date / "scripts"
        if scripts_dir.exists():
            ctx.scripts = self._load_scripts_data(scripts_dir)
