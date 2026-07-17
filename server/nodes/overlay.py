"""
Overlay 节点 — Remotion 数据卡片渲染

对应: run_render.py → step_render() → render_overlay()
"""
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register
from server.models import PipelineContext, OverlayData

logger = logging.getLogger(__name__)


@register
class OverlayNode(BaseNode):
    type = "overlay"
    label = "Overlay 渲染"
    category = "音视频"
    description = "将 Overlay 和 Visual Remotion 渲染为透明 WebM 图层"
    cache_revision = "transparent_remotion_overlay_v3"
    inputs = [NodeInput("aligned", type="AlignedData", label="多轨脚本", required=True)]
    outputs = [NodeOutput("overlay", type="OverlayData", label="Overlay 图层")]
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

        aligned = self.get_input("aligned") or ctx.aligned
        if aligned is None:
            raise RuntimeError("缺少 aligned 输入")
        aligned_dir = aligned.dir
        overlay_dir = ctx.data_root / ctx.date / "overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)

        script_files = sorted(aligned_dir.glob("*.json"))
        tasks = []
        for script_path in script_files:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            script_id = script.get("id", script_path.stem)
            output_path = overlay_dir / f"{script_id}_overlay.webm"
            tracks = script.get("tracks", {})
            expected = bool(
                tracks.get("overlay", [])
                or any(item.get("type") == "remotion" for item in tracks.get("visual", []))
            )
            tasks.append((script, output_path, script_id, expected))

        max_workers = self.get_config("workers", 4)
        on_progress(f"Overlay 渲染中: {len(tasks)} 个脚本", 0.1)

        def _render_all():
            _success = 0
            _failed = 0
            _skipped = 0
            _files = {}
            def _render_one(args):
                s, out, sid, expected = args
                if not expected:
                    return sid, None, out, False
                result = render_overlay(s, out)
                return sid, result, out, True

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_render_one, t): t[2] for t in tasks}
                total = len(futures)
                done_count = 0
                for future in as_completed(futures):
                    script_id = futures[future]
                    done_count += 1
                    try:
                        sid, result, out, expected = future.result()
                        if result:
                            _success += 1
                            _files[sid] = out
                        elif not expected:
                            _skipped += 1
                        else:
                            _failed += 1
                    except Exception as e:
                        _failed += 1
                        logger.error(f"Overlay 渲染失败 {script_id}: {e}")
                    on_progress(
                        f"Overlay [{done_count}/{total}]: {script_id}",
                        0.1 + 0.85 * done_count / max(total, 1),
                    )
            return _files, _success, _failed, _skipped

        import asyncio
        files, success, failed, skipped = await asyncio.to_thread(_render_all)

        ctx.overlay = OverlayData(
            dir=overlay_dir,
            files=files,
            success_count=success,
            failed_count=failed,
        )
        if failed:
            raise RuntimeError(f"Overlay 渲染失败: {failed} 个脚本未生成图层")
        on_progress(f"Overlay 完成: {success} 成功, {skipped} 空轨跳过", 1.0)
        return {"overlay": ctx.overlay}

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
