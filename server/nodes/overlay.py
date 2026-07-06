"""
Overlay 节点 — Remotion 数据卡片渲染

对应: run_render.py → step_render() → render_overlay()
"""
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, OverlayData

logger = logging.getLogger(__name__)


@register
class OverlayNode(BaseNode):
    type = "overlay"
    label = "Overlay 渲染"
    category = "音视频"
    reads = ["aligned"]
    writes = ["overlay"]
    output_dirs = ["overlay"]
    config_schema = {
        "project_dir": {
            "type": "str", "label": "Remotion 项目目录",
            "default": "remotion"
        },
        "workers": {
            "type": "int", "label": "并发渲染数",
            "default": 4, "min": 1, "max": 8
        },
        "fps": {
            "type": "int", "label": "帧率",
            "default": 30
        },
        "width": {"type": "int", "label": "宽度", "default": 1080},
        "height": {"type": "int", "label": "高度", "default": 1920},
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.remotion_renderer import render_overlay

        on_progress("准备 Overlay 渲染...", 0.0)

        aligned_dir = ctx.aligned.dir
        overlay_dir = ctx.data_root / ctx.date / "overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)

        script_files = sorted(aligned_dir.glob("*.json"))
        tasks = []
        for script_path in script_files:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            script_id = script.get("id", script_path.stem)
            output_path = overlay_dir / f"{script_id}_overlay.webm"
            tasks.append((script, output_path, script_id))

        max_workers = self.get_config("workers", 4)

        def _render_all():
            _success = 0
            _failed = 0
            _files = {}
            def _render_one(args):
                s, out, sid = args
                result = render_overlay(s, out)
                return sid, result, out

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_render_one, t): t[2] for t in tasks}
                total = len(futures)
                done_count = 0
                for future in as_completed(futures):
                    script_id = futures[future]
                    done_count += 1
                    try:
                        sid, result, out = future.result()
                        if result:
                            _success += 1
                            _files[sid] = out
                        else:
                            _failed += 1
                    except Exception as e:
                        _failed += 1
                        logger.error(f"Overlay 渲染失败 {script_id}: {e}")
            return _files, _success, _failed

        import asyncio
        files, success, failed = await asyncio.to_thread(_render_all)

        ctx.overlay = OverlayData(
            dir=overlay_dir,
            files=files,
            success_count=success,
            failed_count=failed,
        )
        on_progress(f"Overlay 完成: {success} 成功, {failed} 失败", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 overlay 数据"""
        from server.models import OverlayData
        overlay_dir = ctx.data_root / ctx.date / "overlay"
        files = {}
        for f in overlay_dir.glob("*_overlay.webm"):
            script_id = f.stem.replace("_overlay", "")
            files[script_id] = f
        ctx.overlay = OverlayData(
            dir=overlay_dir,
            files=files,
            success_count=len(files),
            failed_count=0,
        )
