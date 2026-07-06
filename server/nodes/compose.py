"""
Compose 节点 — 最终合成

对应: run_render.py → step_compose()
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, FinalData

logger = logging.getLogger(__name__)


@register
class ComposeNode(BaseNode):
    type = "compose"
    label = "最终合成"
    category = "输出"
    reads = ["aligned", "audio", "overlay", "visual", "live2d", "media"]
    writes = ["final"]
    output_dirs = ["final"]
    config_schema = {
        "resolution": {
            "type": "list", "label": "分辨率 [宽, 高]",
            "default": [1080, 1920]
        },
        "fps": {
            "type": "int", "label": "帧率",
            "default": 30
        },
        "codec": {
            "type": "enum", "label": "编码器",
            "default": "libx264",
            "options": ["libx264", "libx265", "libaom-av1"]
        },
        "studio_bg": {
            "type": "str", "label": "演播室背景图",
            "default": "assets/studio/bg_starry.png"
        },
        "studio_desk": {
            "type": "str", "label": "演播台前景图",
            "default": "assets/studio/desk_foreground.png"
        },
        "character_position": {
            "type": "dict", "label": "角色位置",
            "default": {"anchor": "bottom_right", "x_offset": -50, "y_offset": -30, "scale": 0.4},
            "description": "Live2D 角色在画面中的锚点和偏移"
        },
        "fade_duration_s": {
            "type": "float", "label": "转场时长(秒)",
            "default": 0.5, "min": 0, "max": 2.0, "step": 0.1
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        """调用现有的 step_compose 逻辑"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.run_render import step_compose

        on_progress("最终合成中...", 0.0)

        config = ctx.config
        data_root = ctx.data_root
        today = ctx.date

        # 直接调用现有函数（同步阻塞，放到线程）
        import asyncio
        await asyncio.to_thread(step_compose, config, today, data_root)

        # 扫描产出
        output_dir = data_root / today / "final"
        files = {}
        total_duration_s = {}

        if output_dir.exists():
            for f in output_dir.glob("*.mp4"):
                script_id = f.stem
                files[script_id] = f
                # 尝试获取时长
                try:
                    import subprocess
                    result = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-print_format", "json",
                         "-show_format", str(f)],
                        capture_output=True, text=True, encoding="utf-8"
                    )
                    info = json.loads(result.stdout)
                    duration = float(info.get("format", {}).get("duration", 0))
                    total_duration_s[script_id] = duration
                except Exception:
                    pass

        ctx.final = FinalData(
            dir=output_dir,
            files=files,
            success_count=len(files),
            total_duration_s=total_duration_s,
        )
        on_progress(f"合成完成: {len(files)} 个视频", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 final 数据"""
        import json, subprocess
        from server.models import FinalData
        output_dir = ctx.data_root / ctx.date / "final"
        files = {}
        total_duration_s = {}
        if output_dir.exists():
            for f in output_dir.glob("*.mp4"):
                script_id = f.stem
                files[script_id] = f
                try:
                    result = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-print_format", "json",
                         "-show_format", str(f)],
                        capture_output=True, text=True, encoding="utf-8"
                    )
                    info = json.loads(result.stdout)
                    duration = float(info.get("format", {}).get("duration", 0))
                    total_duration_s[script_id] = duration
                except Exception:
                    pass
        ctx.final = FinalData(
            dir=output_dir,
            files=files,
            success_count=len(files),
            total_duration_s=total_duration_s,
        )
