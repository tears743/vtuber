import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.renderer.run_render import _format_ffmpeg_exit_code, step_compose
from server.models import PipelineContext
from server.nodes.compose import ComposeNode


class ComposeFailureTests(unittest.TestCase):
    def test_windows_access_violation_is_identified(self):
        description = _format_ffmpeg_exit_code(-1073741819)
        self.assertIn("0xC0000005", description)
        self.assertIn("内存访问冲突", description)

    def test_step_compose_raises_when_ffmpeg_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            date = "2026-07-17"
            scripts_dir = data_root / date / "scripts_aligned"
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "failed.json").write_text(
                json.dumps({
                    "id": "failed",
                    "total_duration_ms": 1000,
                    "tracks": {"voice": [], "visual": [], "overlay": []},
                }),
                encoding="utf-8",
            )

            with patch("agents.renderer.run_render._compose_studio", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "最终合成失败"):
                    step_compose({}, date, data_root)

    def test_restore_cache_ignores_broken_mp4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            date = "2026-07-17"
            final_dir = data_root / date / "final"
            final_dir.mkdir(parents=True)
            (final_dir / "broken.mp4").write_bytes(b"not an mp4")

            ctx = PipelineContext(date=date, data_root=data_root)
            node = ComposeNode("compose")
            node.restore_cache(ctx)

            self.assertEqual(ctx.final.success_count, 0)
            self.assertEqual(ctx.final.files, {})


if __name__ == "__main__":
    unittest.main()
