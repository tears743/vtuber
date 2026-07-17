"""Focused checks for post-TTS studio and material orchestration rules."""

import inspect
import tempfile
import unittest
from pathlib import Path

from agents.renderer.run_render import _compose_studio
from server.nodes.voice_visual_director import VoiceVisualDirectorAgent


def _script() -> dict:
    return {
        "id": "test_script",
        "total_duration_ms": 22000,
        "tracks": {
            "voice": [
                {"topic_id": "intro", "start_ms": 0, "duration_ms": 1000, "text": "开场。"},
                {"topic_id": "topic_01", "start_ms": 1000, "duration_ms": 5000, "text": "第一条。"},
                {"topic_id": "topic_01", "start_ms": 6000, "duration_ms": 5000, "text": "第一条续。"},
                {"topic_id": "topic_02", "start_ms": 11000, "duration_ms": 5000, "text": "第二条。"},
                {"topic_id": "topic_02", "start_ms": 16000, "duration_ms": 5000, "text": "第二条续。"},
                {"topic_id": "outro", "start_ms": 21000, "duration_ms": 1000, "text": "结尾。"},
            ]
        },
    }


class VoiceVisualDirectorConstraintTests(unittest.TestCase):
    def setUp(self):
        self.node = VoiceVisualDirectorAgent(
            "director",
            {
                "max_material_duration_ms": 4500,
                "studio_return_ms": 900,
                "max_material_ratio": 0.45,
            },
        )

    def test_compliant_material_and_remotion_tracks_are_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            material = Path(temp_dir) / "material.png"
            material.touch()
            data = {
                "final": True,
                "tracks": {
                    "visual": [
                        {
                            "start_ms": 2200,
                            "duration_ms": 4000,
                            "type": "image",
                            "source": str(material),
                            "transition": "fade",
                        },
                        {
                            "start_ms": 2400,
                            "duration_ms": 2000,
                            "type": "remotion",
                            "component": "info_panel",
                            "props": {"title": "要点", "points": ["事实"]},
                        },
                    ],
                    "overlay": [],
                    "live2d": [],
                    "background": [
                        {"start_ms": 0, "duration_ms": 22000, "type": "gradient"}
                    ],
                },
            }

            errors = self.node._validate_agent_result(data, _script(), [str(material)])

        self.assertEqual(errors, [])

    def test_invalid_material_timing_returns_specific_repair_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            material = Path(temp_dir) / "material.png"
            material.touch()
            data = {
                "final": True,
                "tracks": {
                    "visual": [
                        {
                            "start_ms": 1100,
                            "duration_ms": 6000,
                            "type": "image",
                            "source": str(material),
                        }
                    ],
                    "overlay": [],
                    "live2d": [],
                    "background": [
                        {"start_ms": 0, "duration_ms": 22000, "type": "gradient"}
                    ],
                },
            }

            errors = self.node._validate_agent_result(data, _script(), [str(material)])

        joined = "\n".join(errors)
        self.assertIn("超过单段上限", joined)
        self.assertIn('transition="fade"', joined)
        self.assertIn("开头必须先展示演播室", joined)
        self.assertIn("缺少重叠的 visual remotion", joined)
        self.assertIn("素材占比", joined)

    def test_script_summary_exposes_topic_boundaries(self):
        summary = self.node._script_summary(_script())
        self.assertIn('"topic_id": "topic_01"', summary)
        self.assertIn('"topic_id": "topic_02"', summary)

    def test_compose_uses_segment_fades_instead_of_full_frame_blend(self):
        source = inspect.getsource(_compose_studio)
        self.assertIn("precomposed_visual_inputs", source)
        self.assertIn("fade=t=in", source)
        self.assertNotIn("blend=all_expr", source)


if __name__ == "__main__":
    unittest.main()
