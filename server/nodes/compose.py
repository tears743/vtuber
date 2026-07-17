"""
Compose 节点 — 最终合成

对应: run_render.py → step_compose()
"""
import logging
from pathlib import Path

from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register
from server.models import PipelineContext, FinalData

logger = logging.getLogger(__name__)


@register
class ComposeNode(BaseNode):
    type = "compose"
    label = "最终合成"
    category = "输出"
    description = "合并 Visual、Overlay、字幕、Live2D 和音频生成最终视频"
    cache_revision = "studio_segment_fade_v6"
    inputs = [
        NodeInput("aligned", type="AlignedData", label="多轨脚本", required=True),
        NodeInput("audio", type="AudioData", label="音频", required=True),
        NodeInput("overlay", type="OverlayData", label="Overlay 图层", required=False),
        NodeInput("visual", type="VisualData", label="Visual 图层", required=False),
        NodeInput("subtitles", type="SubtitleData", label="字幕轨", required=True),
        NodeInput("live2d", type="Live2DData", label="Live2D 图层", required=False),
        NodeInput("media", type="MediaData", label="媒体素材", required=False),
    ]
    outputs = [NodeOutput("final", type="FinalData", label="最终视频")]
    reads = ["aligned", "audio", "overlay", "visual", "subtitles", "live2d", "media"]
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

        from agents.renderer.run_render import _probe_video_duration, step_compose

        on_progress("最终合成中...", 0.0)

        # Bind graph inputs to the compatibility context used by the renderer.
        for name in ("aligned", "audio", "overlay", "visual", "subtitles", "live2d", "media"):
            value = self.get_input(name)
            if value is not None:
                setattr(ctx, name, value)
        if ctx.subtitles is None:
            raise RuntimeError("缺少 subtitles 输入，请连接字幕生成节点")

        config = ctx.config
        data_root = ctx.data_root
        today = ctx.date

        # 直接调用现有函数（同步阻塞，放到线程）
        import asyncio
        await asyncio.to_thread(
            step_compose,
            config,
            today,
            data_root,
            lambda message, progress: on_progress(message, progress),
        )

        # 扫描产出
        output_dir = data_root / today / "final"
        files = {}
        total_duration_s = {}

        if output_dir.exists():
            for f in output_dir.glob("*.mp4"):
                script_id = f.stem
                duration = _probe_video_duration(f)
                if duration is None:
                    logger.warning("忽略不可读取的合成产物: %s", f)
                    continue
                files[script_id] = f
                total_duration_s[script_id] = duration

        ctx.final = FinalData(
            dir=output_dir,
            files=files,
            success_count=len(files),
            total_duration_s=total_duration_s,
        )
        if not files:
            raise RuntimeError("最终合成未生成任何视频")
        on_progress(f"合成完成: {len(files)} 个视频", 1.0)
        return {"final": ctx.final}

    def restore_cache(self, ctx):
        """从磁盘恢复 final 数据"""
        from agents.renderer.run_render import _probe_video_duration
        from server.models import FinalData
        output_dir = ctx.data_root / ctx.date / "final"
        files = {}
        total_duration_s = {}
        if output_dir.exists():
            for f in output_dir.glob("*.mp4"):
                script_id = f.stem
                duration = _probe_video_duration(f)
                if duration is None:
                    continue
                files[script_id] = f
                total_duration_s[script_id] = duration
        ctx.final = FinalData(
            dir=output_dir,
            files=files,
            success_count=len(files),
            total_duration_s=total_duration_s,
        )
