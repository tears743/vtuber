"""
Align 节点 — 时间轴对齐

对应: run_render.py → step_align() → realign_script_file()
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, AlignedData

logger = logging.getLogger(__name__)


@register
class AlignNode(BaseNode):
    type = "align"
    label = "时间对齐"
    category = "音视频"
    reads = ["scripts", "audio"]
    writes = ["aligned"]
    output_dirs = ["scripts_aligned"]
    config_schema = {
        "gap_strategy": {
            "type": "enum", "label": "间隙策略",
            "default": "proportional",
            "options": ["proportional", "fixed", "none"],
            "description": "段落间的时间间隙分配方式"
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.realigner import realign_script_file

        on_progress("时间轴对齐...", 0.0)

        scripts_dir = ctx.scripts.dir
        audio_dir = ctx.audio.dir
        aligned_dir = ctx.data_root / ctx.date / "scripts_aligned"
        aligned_dir.mkdir(parents=True, exist_ok=True)

        # 加载 durations
        durations_path = ctx.audio.durations_path
        if not durations_path.exists():
            on_progress("❌ durations.json 不存在", 1.0)
            return

        with open(durations_path, "r", encoding="utf-8") as f:
            all_durations = json.load(f)

        script_files = sorted(scripts_dir.glob("*.json"))
        aligned_files = []
        aligned_scripts = {}

        for i, script_path in enumerate(script_files):
            script_id = script_path.stem
            durations = all_durations.get(script_id, {})
            durations_int = {int(k): v for k, v in durations.items()}

            import asyncio
            output_path = aligned_dir / script_path.name
            await asyncio.to_thread(realign_script_file, script_path, durations_int, output_path)
            aligned_files.append(output_path)

            with open(output_path, "r", encoding="utf-8") as f:
                aligned_scripts[script_id] = json.load(f)

            progress = 0.1 + 0.8 * ((i + 1) / max(len(script_files), 1))
            on_progress(f"对齐 [{i+1}/{len(script_files)}]: {script_id}", progress)

        ctx.aligned = AlignedData(
            dir=aligned_dir,
            files=aligned_files,
            scripts=aligned_scripts,
        )
        on_progress(f"时间轴对齐完成: {len(aligned_files)} 个脚本", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 aligned 数据"""
        import json
        from server.models import AlignedData
        aligned_dir = ctx.data_root / ctx.date / "scripts_aligned"
        aligned_files = sorted(aligned_dir.glob("*.json"))
        aligned_scripts = {}
        for sp in aligned_files:
            with open(sp, "r", encoding="utf-8") as f:
                aligned_scripts[sp.stem] = json.load(f)
        ctx.aligned = AlignedData(
            dir=aligned_dir,
            files=aligned_files,
            scripts=aligned_scripts,
        )
