"""
Live2D 节点 — Live2D 口播渲染

对应: run_render.py → step_live2d()
"""
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, Live2DData

logger = logging.getLogger(__name__)


@register
class Live2DNode(BaseNode):
    type = "live2d"
    label = "Live2D 渲染"
    category = "音视频"
    reads = ["aligned", "audio"]
    writes = ["live2d"]
    output_dirs = ["live2d"]
    config_schema = {
        "model_path": {
            "type": "str", "label": "Live2D 模型路径",
            "default": "D:/workspace/Open-LLM-VTuber/live2d-models/mao_pro/runtime"
        },
        "model_json": {
            "type": "str", "label": "模型配置文件",
            "default": "mao_pro.model3.json"
        },
        "emotion_map": {
            "type": "dict", "label": "表情映射表",
            "default": {
                "neutral": 0, "sarcastic": 2, "amused": 3,
                "shocked": 3, "excited": 3, "speechless": 1,
                "smirk": 3, "fear": 1, "sadness": 1
            },
            "description": "emotion 名称 → motion group index 映射"
        },
        "workers": {
            "type": "int", "label": "并发渲染数",
            "default": 2, "min": 1, "max": 4
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.live2d_renderer import step_live2d as _step_live2d

        on_progress("Live2D 渲染中...", 0.0)

        max_workers = self.get_config("workers", 2)
        import asyncio
        await asyncio.to_thread(_step_live2d, ctx.date, max_workers)

        # 扫描产出
        live2d_dir = ctx.data_root / ctx.date / "live2d"
        files = {}
        if live2d_dir.exists():
            for f in live2d_dir.glob("*_live2d.webm"):
                script_id = f.stem.replace("_live2d", "")
                files[script_id] = f

        ctx.live2d = Live2DData(
            dir=live2d_dir,
            files=files,
            success_count=len(files),
        )
        on_progress(f"Live2D 完成: {len(files)} 个", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 live2d 数据"""
        from server.models import Live2DData
        live2d_dir = ctx.data_root / ctx.date / "live2d"
        files = {}
        if live2d_dir.exists():
            for f in live2d_dir.glob("*_live2d.webm"):
                script_id = f.stem.replace("_live2d", "")
                files[script_id] = f
        ctx.live2d = Live2DData(
            dir=live2d_dir,
            files=files,
            success_count=len(files),
        )
