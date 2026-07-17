"""
Visual 节点 — 背景视觉层渲染

对应: run_render.py → step_visual() → render_script_visual()
"""
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register
from server.models import PipelineContext, VisualData

logger = logging.getLogger(__name__)


@register
class VisualNode(BaseNode):
    type = "visual"
    label = "Visual 渲染"
    category = "音视频"
    description = "将 Visual 轨中的真实图片和视频素材渲染为独立 MP4"
    cache_revision = "studio_alpha_fade_v4"
    inputs = [
        NodeInput("aligned", type="AlignedData", label="多轨脚本", required=True),
        NodeInput("media", type="MediaData", label="媒体素材", required=False),
    ]
    outputs = [NodeOutput("visual", type="VisualData", label="Visual 图层")]
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

        aligned = self.get_input("aligned") or ctx.aligned
        if aligned is None:
            raise RuntimeError("缺少 aligned 输入")
        aligned_dir = aligned.dir
        visual_dir = ctx.data_root / ctx.date / "visual"
        visual_dir.mkdir(parents=True, exist_ok=True)

        script_files = sorted(aligned_dir.glob("*.json"))
        tasks = []
        for script_path in script_files:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            visual_items = script.get("tracks", {}).get("visual", [])
            expected = any(item.get("type") in {"image", "video_clip"} for item in visual_items)
            tasks.append((script, visual_dir, expected))

        max_workers = self.get_config("workers", 4)
        on_progress(f"Visual 渲染中: {len(tasks)} 个脚本", 0.05)

        def _render_all():
            _success = 0
            _failed = 0
            _skipped = 0
            _files = {}
            def _render_one(args):
                script, out_dir, expected = args
                if not expected:
                    script_id = script.get("id", "unknown")
                    (out_dir / f"{script_id}_visual.mp4").unlink(missing_ok=True)
                    return script.get("id", "?"), None, False
                result = render_script_visual(
                    script,
                    out_dir,
                    lambda message, progress: on_progress(
                        f"{script.get('id', '?')}: {message}",
                        0.05 + 0.85 * progress,
                    ),
                )
                return script.get("id", "?"), result, True

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_render_one, t): t[0].get("id", "?") for t in tasks}
                total = len(futures)
                done_count = 0
                for future in as_completed(futures):
                    script_id = futures[future]
                    done_count += 1
                    try:
                        sid, result, expected = future.result()
                        if result:
                            _success += 1
                            _files[sid] = visual_dir / f"{sid}_visual.mp4"
                        elif not expected:
                            _skipped += 1
                        else:
                            _failed += 1
                    except Exception as e:
                        _failed += 1
                        logger.error(f"Visual 渲染失败 {script_id}: {e}")
                    on_progress(
                        f"Visual [{done_count}/{total}]: {script_id}",
                        0.1 + 0.85 * done_count / max(total, 1),
                    )
            return _files, _success, _failed, _skipped

        import asyncio
        files, success, failed, skipped = await asyncio.to_thread(_render_all)

        ctx.visual = VisualData(
            dir=visual_dir,
            files=files,
            success_count=success,
        )
        if failed:
            raise RuntimeError(f"Visual 渲染失败: {failed} 个脚本未生成图层")
        on_progress(f"Visual 完成: {success} 成功, {skipped} 空轨跳过", 1.0)
        return {"visual": ctx.visual}

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
