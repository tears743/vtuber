"""
Recognize 节点 — 素材识别 (Vision)

对应: run_render.py → step_recognize() → MediaRecognizer.recognize_all()
"""
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext

logger = logging.getLogger(__name__)


@register
class RecognizeNode(BaseNode):
    type = "recognize"
    label = "素材识别"
    category = "内容处理"
    reads = ["media"]
    writes = ["recognized"]
    output_dirs = []  # 产出写入 media/manifest，不独立缓存
    config_schema = {
        "model": {
            "type": "model", "label": "Vision 模型",
            "default": "mimo-v2.5",
            "capabilities": ["vision"],
            "description": "用于图片/视频内容识别的 Vision 模型"
        },
        "concurrency": {
            "type": "int", "label": "并发识别数",
            "default": 10, "min": 1, "max": 20
        },
        "recognition_prompt": {
            "type": "text", "label": "图片识别指令",
            "default": "",
            "prompt_file": "recognize_image.txt",
            "variables": [],
            "description": "发给 Vision 模型的图片描述指令"
        },
        "video_understanding_prompt": {
            "type": "text", "label": "视频理解指令",
            "default": "",
            "prompt_file": "recognize_video.txt",
            "variables": [],
            "description": "发给 Vision 模型的视频分析指令"
        },
        "readme_summary_prompt": {
            "type": "text", "label": "README 总结指令",
            "default": "",
            "prompt_file": "recognize_readme.txt",
            "variables": []
        },
        "min_image_width": {
            "type": "int", "label": "最小图片宽度",
            "default": 200, "min": 50, "max": 500
        },
        "min_image_height": {
            "type": "int", "label": "最小图片高度",
            "default": 200, "min": 50, "max": 500
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.media_recognizer import MediaRecognizer

        on_progress("初始化识别器...", 0.0)

        config = ctx.config
        model_name = self.get_config("model", "mimo-v2.5")
        models = config.get("models", {})

        if model_name in models:
            model_cfg = models[model_name]
        else:
            logger.error(f"模型 {model_name} 未在全局配置中找到")
            return

        recognizer = MediaRecognizer(
            base_url=model_cfg["base_url"],
            api_key=model_cfg["api_key"],
            model=model_cfg["model"],
        )

        media_dir = ctx.media.dir
        manifest_path = ctx.media.manifest_path

        on_progress("识别素材中...", 0.1)
        import asyncio
        def report_recognition(message, progress):
            on_progress(message, 0.1 + 0.8 * progress)

        manifest = await asyncio.to_thread(
            recognizer.recognize_all,
            media_dir,
            manifest_path,
            report_recognition,
        )
        on_progress("识别完成", 0.9)

        # 更新 ctx.media (enriched)
        ctx.media.manifest = manifest
        total_images = sum(len(v.get("images", [])) for v in manifest.values())
        total_videos = sum(1 for v in manifest.values() if v.get("video"))
        ctx.media.total_images = total_images
        ctx.media.total_videos = total_videos

        ctx.recognized = True
        on_progress(f"识别完成: {ctx.media.total_items} 条素材已增强", 1.0)
