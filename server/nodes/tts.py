"""
TTS 节点 — 语音合成

对应: run_render.py → step_tts() → VoxCPMTTS.synthesize_script()
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, AudioData

logger = logging.getLogger(__name__)


@register
class TTSNode(BaseNode):
    type = "tts"
    label = "语音合成"
    category = "音视频"
    reads = ["scripts"]
    writes = ["audio"]
    output_dirs = ["audio"]
    config_schema = {
        "engine": {
            "type": "enum", "label": "TTS 引擎",
            "default": "voxcpm",
            "options": ["voxcpm", "voxcpm2"]
        },
        "url": {
            "type": "str", "label": "服务地址",
            "default": "http://127.0.0.1:8808"
        },
        "dialect": {
            "type": "str", "label": "方言/口音",
            "default": "四川话",
            "description": "VoxCPM control_instruction 参数"
        },
        "reference_wav": {
            "type": "str", "label": "参考音频路径",
            "default": "assets/voice/reference.mp3",
            "description": "音色克隆参考音频"
        },
        "cfg_value": {
            "type": "float", "label": "CFG 强度",
            "default": 3.0, "min": 0.5, "max": 10.0, "step": 0.5
        },
        "inference_timesteps": {
            "type": "int", "label": "推理步数",
            "default": 32, "min": 8, "max": 64
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.tts import VoxCPMTTS

        on_progress("初始化 TTS...", 0.0)

        config = ctx.config
        tts_cfg = config.get("tts", {}).get("voxcpm", {})

        tts = VoxCPMTTS(
            url=self.get_config("url", tts_cfg.get("url", "http://127.0.0.1:8808")),
            dialect=self.get_config("dialect", tts_cfg.get("dialect", "四川话")),
            speed="快",
        )

        if not tts.check_health():
            logger.warning("VoxCPM TTS 服务不可用，尝试自动启动...")
            on_progress("启动 TTS 服务...", 0.02)
            
            if not self._start_tts_service(tts):
                logger.error("VoxCPM TTS 服务启动失败!")
                on_progress("❌ TTS 服务启动失败", 1.0)
                return

        scripts_dir = ctx.scripts.dir
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
            on_progress(f"TTS [{i+1}/{len(script_files)}]: {script_id}", progress)

            import asyncio
            durations = await asyncio.to_thread(tts.synthesize_script, script, script_audio_dir)
            all_durations[script_id] = durations

            # 记录音频文件列表
            wav_files = sorted(script_audio_dir.glob("voice_*.wav"))
            all_segments[script_id] = [p for p in wav_files]

        # 保存 durations 索引
        durations_path = audio_dir / "durations.json"
        with open(durations_path, "w", encoding="utf-8") as f:
            json.dump(all_durations, f, ensure_ascii=False, indent=2)

        ctx.audio = AudioData(
            dir=audio_dir,
            durations_path=durations_path,
            durations=all_durations,
            segments=all_segments,
        )
        on_progress(f"TTS 完成: {len(all_durations)} 个脚本", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 audio 数据"""
        import json
        from server.models import AudioData
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

    def _start_tts_service(self, tts) -> bool:
        """
        自动启动 WSL 中的 VoxCPM TTS 服务。
        
        通过 subprocess.Popen 在独立进程中启动 WSL TTS server，
        然后轮询 /health 直到服务就绪（最多等 180 秒）。
        """
        import subprocess
        import time
        
        # 直接用 Popen 启动 WSL TTS（不能用 Start-Process -WindowStyle Minimized，
        # 最小化窗口的 WSL 进程会被 Windows 杀掉）
        # CREATE_NEW_CONSOLE 保证 WSL 有独立的控制台窗口存活
        wsl_cmd = [
            "wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc",
            "cd ~ && export TORCH_MATMUL_PRECISION=high && "
            "python3 ~/tts_server.py --port 8808 --device cuda "
            "--reference-wav ~/baoer.mp3"
        ]
        
        try:
            logger.info("[tts] 启动 VoxCPM TTS 服务 (WSL)...")
            subprocess.Popen(
                wsl_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as e:
            logger.error(f"[tts] 启动命令失败: {e}")
            return False
        
        # 轮询等待服务就绪（模型加载 + warmup 需要较长时间）
        max_wait = 180
        poll_interval = 5
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            if tts.check_health():
                logger.info(f"[tts] VoxCPM 服务已就绪 (等待 {elapsed}s)")
                return True
            
            logger.info(f"[tts] 等待 TTS 服务启动... ({elapsed}/{max_wait}s)")
        
        logger.error(f"[tts] TTS 服务在 {max_wait}s 内未就绪")
        return False
