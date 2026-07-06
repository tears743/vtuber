"""
Transcribe 节点 — 视频音频转文字

对应: run_render.py → step_transcribe() → AudioTranscriber.transcribe_all()
"""
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext

logger = logging.getLogger(__name__)


@register
class TranscribeNode(BaseNode):
    type = "transcribe"
    label = "音频转录"
    category = "内容处理"
    reads = ["media"]
    writes = ["transcribed"]
    output_dirs = []  # 产出写入 media/manifest，不独立缓存
    config_schema = {
        "engine": {
            "type": "enum", "label": "转录引擎",
            "default": "faster_whisper",
            "options": ["faster_whisper", "crispasr"]
        },
        "model_size": {
            "type": "enum", "label": "模型大小",
            "default": "large-v3",
            "options": ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
        },
        "language": {
            "type": "str", "label": "语言",
            "default": "zh"
        },
        "device": {
            "type": "enum", "label": "设备",
            "default": "cuda",
            "options": ["cuda", "cpu"]
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.audio_transcriber import AudioTranscriber

        on_progress("初始化转录器...", 0.0)

        config = ctx.config
        media_dir = ctx.media.dir
        manifest_path = ctx.media.manifest_path

        if not manifest_path or not manifest_path.exists():
            on_progress("manifest.json 不存在，跳过转录", 1.0)
            return

        transcriber = AudioTranscriber(
            model_size=self.get_config("model_size", "large-v3"),
            language=self.get_config("language", "zh"),
            hf_token=config.get("hf_token", ""),
        )

        on_progress("转录中...", 0.1)
        import asyncio
        manifest = await asyncio.to_thread(transcriber.transcribe_all, media_dir, manifest_path)
        on_progress("转录完成", 0.9)

        ctx.media.manifest = manifest
        ctx.transcribed = True
        on_progress("音频转录完成", 1.0)
