"""VoxCPM TTS node.

Synthesizes every voice segment and writes the measured audio timing back to
the script so downstream timeline nodes consume real durations and paths.
"""

import asyncio
import json
import logging
from pathlib import Path

from server.models import AudioData, PipelineContext, ScriptsData
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register

logger = logging.getLogger(__name__)


@register
class TTSNode(BaseNode):
    type = "tts"
    label = "VoxCPM 语音合成"
    category = "音视频"
    description = "使用本地 VoxCPM2 服务生成语音，并把真实时长和文件路径回填到脚本"

    inputs = [
        NodeInput(
            name="scripts",
            type="ScriptsData",
            label="口播脚本",
            required=True,
            description="口播 Agent 或 Director 输出的脚本。",
        )
    ]
    outputs = [
        NodeOutput(
            name="audio",
            type="AudioData",
            label="音频",
            description="VoxCPM 生成的 WAV 文件和实际时长索引。",
        ),
        NodeOutput(
            name="scripts",
            type="ScriptsData",
            label="已回填脚本",
            description="已写入真实音频时长、起始时间和音频路径的脚本。",
        ),
    ]

    reads = ["scripts"]
    writes = ["audio", "scripts"]
    output_dirs = ["audio"]
    config_schema = {
        "engine": {
            "type": "enum",
            "label": "TTS 引擎",
            "default": "voxcpm2",
            "options": ["voxcpm2"],
        },
        "url": {
            "type": "str",
            "label": "服务地址",
            "default": "http://127.0.0.1:8808",
        },
        "dialect": {
            "type": "str",
            "label": "方言/口音",
            "default": "四川话",
            "description": "传给 VoxCPM control_instruction 的口音要求。",
        },
        "speed": {
            "type": "enum",
            "label": "语速",
            "default": "快",
            "options": ["慢", "正常", "快"],
        },
        "customize": {
            "type": "bool",
            "label": "启用语音定制",
            "default": True,
            "description": "关闭后不发送口音/语速指令，control_instruction 为空。",
        },
        "reference_wav": {
            "type": "str",
            "label": "参考音频路径",
            "default": "assets/voice/reference.mp3",
            "description": "VoxCPM 服务使用的音色克隆参考音频。",
        },
        "cfg_value": {
            "type": "float",
            "label": "CFG 强度",
            "default": 3.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.5,
        },
        "inference_timesteps": {
            "type": "int",
            "label": "推理步数",
            "default": 32,
            "min": 8,
            "max": 64,
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from agents.renderer.tts import VoxCPMTTS

        on_progress("初始化 VoxCPM TTS...", 0.0)

        tts_cfg = (ctx.config or {}).get("tts", {}).get("voxcpm", {})
        tts = VoxCPMTTS(
            url=self.get_config("url", tts_cfg.get("url", "http://127.0.0.1:8808")),
            dialect=self.get_config("dialect", tts_cfg.get("dialect", "四川话")),
            cfg_value=float(self.get_config("cfg_value", tts_cfg.get("cfg_value", 3.0))),
            inference_timesteps=int(
                self.get_config("inference_timesteps", tts_cfg.get("inference_timesteps", 32))
            ),
            speed=self.get_config("speed", tts_cfg.get("speed", "快")),
            customize=bool(self.get_config("customize", tts_cfg.get("customize", True))),
        )

        if not tts.check_health():
            logger.warning("[tts] VoxCPM 服务不可用，尝试自动启动")
            on_progress("启动 VoxCPM TTS 服务...", 0.02)
            if not await asyncio.to_thread(self._start_tts_service, tts):
                raise RuntimeError("VoxCPM TTS 服务启动失败，请检查 WSL、模型和 GPU 状态。")

        scripts = self.get_input("scripts") or ctx.scripts
        if scripts is None:
            raise RuntimeError("缺少 scripts 输入")

        scripts_dir = Path(scripts.dir)
        script_files = sorted(scripts_dir.glob("*.json"))
        if not script_files:
            raise RuntimeError(f"脚本目录中没有 JSON 文件: {scripts_dir}")

        audio_dir = ctx.data_root / ctx.date / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        all_durations = {}
        all_segments = {}

        for index, script_path in enumerate(script_files):
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            script = json.loads(script_path.read_text(encoding="utf-8"))
            script_id = script.get("id", script_path.stem)
            script_audio_dir = audio_dir / script_id
            progress = 0.1 + 0.8 * (index / max(len(script_files), 1))
            on_progress(f"VoxCPM TTS [{index + 1}/{len(script_files)}]: {script_id}", progress)

            script_span = 0.8 / max(len(script_files), 1)
            def report_voice(message, voice_progress, _script_id=script_id, _base=progress):
                on_progress(f"{_script_id}: {message}", _base + script_span * voice_progress)

            durations = await asyncio.to_thread(
                tts.synthesize_script,
                script,
                script_audio_dir,
                report_voice,
            )
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            all_durations[script_id] = durations
            all_segments[script_id] = sorted(script_audio_dir.glob("*.wav"))
            self._write_audio_metadata(script, script_path, script_audio_dir, durations, ctx)

        durations_path = audio_dir / "durations.json"
        durations_path.write_text(
            json.dumps(all_durations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        ctx.audio = AudioData(
            dir=audio_dir,
            durations_path=durations_path,
            durations=all_durations,
            segments=all_segments,
        )
        ctx.scripts = self._load_scripts_data(scripts_dir)
        on_progress(f"VoxCPM TTS 完成: {len(all_durations)} 个脚本", 1.0)
        return {"audio": ctx.audio, "scripts": ctx.scripts}

    def _write_audio_metadata(
        self,
        script: dict,
        script_path: Path,
        script_audio_dir: Path,
        durations: dict,
        ctx: PipelineContext,
    ) -> None:
        tracks = script.setdefault("tracks", {})
        voice_items = tracks.get("voice", [])
        current_ms = 0

        if voice_items:
            for index, item in enumerate(voice_items):
                duration_ms = int(
                    durations.get(index)
                    or durations.get(str(index))
                    or item.get("duration_ms", 0)
                    or 0
                )
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
                duration_ms = int(
                    durations.get(index)
                    or durations.get(str(index))
                    or item.get("duration_ms", 0)
                    or 0
                )
                wav_path = script_audio_dir / f"seg_{index:02d}.wav"
                item["start_ms"] = current_ms
                item["duration_ms"] = duration_ms
                item["audio_file"] = self._relative_run_path(wav_path, ctx)
                item["audio_path"] = str(wav_path)
                current_ms += duration_ms

        script["total_duration_ms"] = current_ms
        meta = script.setdefault("meta", {})
        meta["duration_source"] = "voxcpm_tts"
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

    def restore_cache(self, ctx: PipelineContext):
        audio_dir = ctx.data_root / ctx.date / "audio"
        durations_path = audio_dir / "durations.json"
        all_durations = {}
        if durations_path.exists():
            all_durations = json.loads(durations_path.read_text(encoding="utf-8"))

        all_segments = {}
        for script_id in all_durations:
            script_audio_dir = audio_dir / script_id
            if script_audio_dir.exists():
                all_segments[script_id] = sorted(script_audio_dir.glob("*.wav"))

        ctx.audio = AudioData(
            dir=audio_dir,
            durations_path=durations_path,
            durations=all_durations,
            segments=all_segments,
        )
        scripts_dir = ctx.data_root / ctx.date / "scripts"
        if scripts_dir.exists():
            ctx.scripts = self._load_scripts_data(scripts_dir)

    def _start_tts_service(self, tts) -> bool:
        """Start the VoxCPM HTTP service in WSL and wait until it is healthy."""
        import subprocess
        import time

        wsl_cmd = [
            "wsl.exe",
            "-d",
            "Ubuntu",
            "--",
            "bash",
            "-lc",
            "cd ~ && export TORCH_MATMUL_PRECISION=high && "
            "python3 /mnt/d/workspace/videoFactory/scripts/tts_server.py --port 8808 --device cuda "
            "--reference-wav ~/baoer.mp3",
        ]

        try:
            logger.info("[tts] 启动 VoxCPM TTS 服务 (WSL)")
            subprocess.Popen(wsl_cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as exc:
            logger.error("[tts] 启动命令失败: %s", exc)
            return False

        max_wait = 180
        poll_interval = 5
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            if tts.check_health():
                logger.info("[tts] VoxCPM 服务已就绪 (等待 %ss)", elapsed)
                return True
            logger.info("[tts] 等待 VoxCPM 服务启动 (%s/%ss)", elapsed, max_wait)

        logger.error("[tts] VoxCPM 服务在 %ss 内未就绪", max_wait)
        return False
