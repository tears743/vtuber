"""
Visual 节点 — 背景视觉层渲染

对应: run_render.py → step_visual() → render_script_visual()
"""
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, VisualData

logger = logging.getLogger(__name__)


@register
class VisualNode(BaseNode):
    type = "visual"
    label = "Visual 渲染"
    category = "音视频"
    reads = ["aligned", "media"]
    writes = ["visual"]
    output_dirs = ["visual"]
    config_schema = {
        "workers": {
            "type": "int", "label": "并发渲染数",
            "default": 4, "min": 1, "max": 8
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.visual_renderer import render_script_visual

        on_progress("准备 Visual 渲染...", 0.0)

        aligned_dir = ctx.aligned.dir
        visual_dir = ctx.data_root / ctx.date / "visual"
        visual_dir.mkdir(parents=True, exist_ok=True)

        script_files = sorted(aligned_dir.glob("*.json"))
        tasks = []
        for script_path in script_files:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            tasks.append((script, visual_dir))

        max_workers = self.get_config("workers", 4)

        def _render_all():
            _success = 0
            _failed = 0
            _files = {}
            def _render_one(args):
                script, out_dir = args
                result = render_script_visual(script, out_dir)
                return script.get("id", "?"), result

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_render_one, t): t[0].get("id", "?") for t in tasks}
                total = len(futures)
                done_count = 0
                for future in as_completed(futures):
                    script_id = futures[future]
                    done_count += 1
                    try:
                        sid, result = future.result()
                        if result:
                            _success += 1
                            _files[sid] = visual_dir / f"{sid}_visual.mp4"
                        else:
                            _failed += 1
                    except Exception as e:
                        _failed += 1
                        logger.error(f"Visual 渲染失败 {script_id}: {e}")
            return _files, _success, _failed

        import asyncio
        files, success, failed = await asyncio.to_thread(_render_all)

        ctx.visual = VisualData(
            dir=visual_dir,
            files=files,
            success_count=success,
        )
        on_progress(f"Visual 完成: {success} 成功, {failed} 失败", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 visual 数据"""
        from server.models import VisualData
        visual_dir = ctx.data_root / ctx.date / "visual"
        files = {}
        for f in visual_dir.glob("*_visual.mp4"):
            script_id = f.stem.replace("_visual", "")
            files[script_id] = f
        ctx.visual = VisualData(
            dir=visual_dir,
            files=files,
            success_count=len(files),
        )
