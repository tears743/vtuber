"""Focused checks for broadcast sentence shaping and VoxCPM instructions."""

import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from agents.renderer.tts import VoxCPMTTS, clean_tts_text
from nodes.community.tech_broadcast_script_agent.node import (
    DEFAULT_VOICE_INSTRUCTION,
    MAX_VOICE_SENTENCE_CHARS,
    TechBroadcastScriptAgent,
)
from server.models import PipelineContext


def _wav_bytes(duration_ms: int = 100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * int(24000 * duration_ms / 1000))
    return buffer.getvalue()


class _Response:
    content = _wav_bytes()

    def raise_for_status(self):
        return None


class VoiceScriptConstraintTests(unittest.TestCase):
    def test_detailed_topic_requires_and_accepts_all_content_aspects(self):
        node = TechBroadcastScriptAgent(
            "script_agent",
            {"min_sentences_per_topic": 9},
        )
        data = {
            "final": True,
            "selected_topics": [
                {
                    "id": "topic_01",
                    "title": "详细测试选题",
                    "source": "M001",
                    "reason": "这个选题包含足够明确的技术信息和实际应用价值，值得展开说明。",
                    "key_facts": [
                        "素材明确说明系统包含三个相互协作的模块。",
                        "素材给出了可以直接复现的安装和调用步骤。",
                    ],
                    "technical_analysis": (
                        "系统先采集结构化输入，再由调度模块分配任务，最后通过校验模块检查输出；"
                        "各模块使用明确接口传递数据并保留失败状态。"
                    ),
                    "impact": "开发团队可以减少重复接线工作，并更快定位任务失败发生在哪个环节。",
                    "caveats": "当前实现仍依赖本地环境配置，复杂任务还需要人工检查结果。",
                }
            ],
            "voice": [
                {"topic_id": "intro", "aspect": "intro", "text": "先来看今天的重点。"},
                {"topic_id": "topic_01", "aspect": "overview", "text": "这个项目解决重复编排任务的问题。"},
                {"topic_id": "topic_01", "aspect": "mechanism", "text": "调度模块会按输入类型分配处理步骤。"},
                {"topic_id": "topic_01", "aspect": "mechanism", "text": "校验模块再检查输出并保留失败状态。"},
                {"topic_id": "topic_01", "aspect": "evidence", "text": "素材列出了三个模块和对应接口。"},
                {"topic_id": "topic_01", "aspect": "evidence", "text": "素材还给出了可以复现的安装步骤。"},
                {"topic_id": "topic_01", "aspect": "use_case", "text": "开发团队可以用它批量处理日常任务。"},
                {"topic_id": "topic_01", "aspect": "impact", "text": "它能减少重复接线并缩短排错时间。"},
                {"topic_id": "topic_01", "aspect": "caveat", "text": "本地配置和复杂结果仍需要人工检查。"},
                {"topic_id": "topic_01", "aspect": "transition", "text": "讲完任务编排，再来看下一种实现思路。"},
                {"topic_id": "outro", "aspect": "outro", "text": "今天就先讲到这里。"},
            ],
        }

        errors = node._validate_agent_result(
            data,
            expected_topic_count=1,
            allowed_sources={"M001"},
            github_sources=set(),
        )

        self.assertEqual(errors, [])

    def test_script_writer_strips_llm_controls_and_only_splits_at_periods(self):
        long_sentence = (
            "这个项目把数据采集模型推理结果校验和任务编排放在一条链路里，"
            "并且给出了可以复现的部署步骤和明确的使用限制"
        )
        data = {
            "title": "测试口播",
            "voice": [
                {
                    "topic_id": "topic_01",
                    "text": f"（轻笑）第一句话。第二句话。{long_sentence}。",
                }
            ],
            "selected_topics": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = PipelineContext(
                date="2026-07-16",
                data_root=Path(temp_dir),
                config={},
            )
            node = TechBroadcastScriptAgent(
                "script_agent",
                {"voice_instruction": DEFAULT_VOICE_INSTRUCTION},
            )
            scripts_data = node._write_scripts(ctx, data)

        voice = scripts_data.scripts["tech_broadcast_script"]["tracks"]["voice"]
        self.assertEqual(len(voice), 3)
        self.assertEqual([item["id"] for item in voice], [f"voice_{i:02d}" for i in range(len(voice))])
        for item in voice:
            self.assertTrue(item["text"].startswith(DEFAULT_VOICE_INSTRUCTION))
            self.assertNotIn("轻笑", item["text"])
            self.assertNotIn(DEFAULT_VOICE_INSTRUCTION, item["subtitle"])
            self.assertTrue(item["subtitle"].endswith("。"))
            self.assertEqual(item["subtitle"].count("。"), 1)
        self.assertEqual(voice[-1]["subtitle"], f"{long_sentence}。")

    def test_transition_must_be_the_last_sentence_of_each_topic(self):
        node = TechBroadcastScriptAgent("script_agent", {"min_sentences_per_topic": 9})
        topic = {
            "id": "topic_01",
            "title": "测试选题",
            "source": "M001",
            "reason": "这个选题包含足够的事实和技术分析，适合进行详细口播说明。",
            "key_facts": ["这是第一条明确素材事实。", "这是第二条明确素材事实。"],
            "technical_analysis": "这里包含足够详细的技术机制、模块关系、执行流程和接口协作方式说明。" * 2,
            "impact": "它能够帮助实际用户减少重复操作，并提升复杂任务的执行效率。",
            "caveats": "当前仍然存在部署成本和结果校验方面的限制。",
        }
        voice = [
            {"topic_id": "intro", "aspect": "intro", "text": "这是开场。"},
            {"topic_id": "topic_01", "aspect": "overview", "text": "这是项目概述。"},
            {"topic_id": "topic_01", "aspect": "mechanism", "text": "这是第一句机制。"},
            {"topic_id": "topic_01", "aspect": "mechanism", "text": "这是第二句机制。"},
            {"topic_id": "topic_01", "aspect": "evidence", "text": "这是第一条证据。"},
            {"topic_id": "topic_01", "aspect": "evidence", "text": "这是第二条证据。"},
            {"topic_id": "topic_01", "aspect": "use_case", "text": "这是使用场景。"},
            {"topic_id": "topic_01", "aspect": "impact", "text": "这是实际影响。"},
            {"topic_id": "topic_01", "aspect": "transition", "text": "接着看看下一条。"},
            {"topic_id": "topic_01", "aspect": "caveat", "text": "这是限制说明。"},
            {"topic_id": "outro", "aspect": "outro", "text": "这是总结。"},
        ]

        errors = node._validate_agent_result(
            {"final": True, "selected_topics": [topic], "voice": voice},
            expected_topic_count=1,
            allowed_sources={"M001"},
            github_sources=set(),
        )

        self.assertTrue(any("最后一个 voice 必须是 transition" in error for error in errors))

    def test_validator_rejects_long_sentence_instead_of_hard_splitting(self):
        node = TechBroadcastScriptAgent("script_agent", {})
        topic = {
            "id": "topic_01",
            "title": "测试选题",
            "source": "M001",
            "reason": "这是一个用于验证句子长度规则的充分理由。",
            "key_facts": ["这是第一条有效素材事实。", "这是第二条有效素材事实。"],
            "technical_analysis": "这里提供足够详细的技术机制、实现路径、关键结构和实际工作原理分析。",
            "impact": "这里说明该项目对实际用户和应用场景产生的具体价值。",
            "caveats": "这里说明仍然存在的限制和待验证问题。",
        }
        long_sentence = "这是一句没有自然句号而且明显超过五十个字符的测试文本" * 2 + "。"
        data = {
            "final": True,
            "selected_topics": [topic],
            "voice": [
                {"topic_id": "intro", "text": "这是开场。"},
                {"topic_id": "topic_01", "text": long_sentence},
                {"topic_id": "topic_01", "text": "这是第二句正文。"},
                {"topic_id": "outro", "text": "这是结尾。"},
            ],
        }

        errors = node._validate_agent_result(
            data,
            expected_topic_count=1,
            allowed_sources={"M001"},
            github_sources=set(),
        )

        self.assertTrue(any(f"超过 {MAX_VOICE_SENTENCE_CHARS} 个字符" in error for error in errors))

    def test_tts_cleaner_preserves_only_leading_instruction(self):
        cleaned = clean_tts_text("(四川话，语速快一点)（轻笑）这句话要正常朗读。")
        self.assertEqual(cleaned, "(四川话，语速快一点)这句话要正常朗读。")

    @patch("agents.renderer.tts.requests.post")
    def test_configured_instruction_is_not_duplicated_in_payload(self, post):
        post.return_value = _Response()
        tts = VoxCPMTTS(dialect="四川话", speed="快")

        with tempfile.TemporaryDirectory() as temp_dir:
            tts.synthesize(
                "(四川话，语速快一点)这句话要正常朗读。",
                Path(temp_dir) / "voice.wav",
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["text"], "(四川话，语速快一点)这句话要正常朗读。")
        self.assertNotIn("control_instruction", payload)

    @patch("agents.renderer.tts.requests.post")
    def test_disabled_customization_sends_empty_control_instruction(self, post):
        post.return_value = _Response()
        tts = VoxCPMTTS(dialect="四川话", speed="快", customize=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            tts.synthesize(
                "(四川话，语速快一点)关闭定制后只朗读正文。",
                Path(temp_dir) / "voice.wav",
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["text"], "关闭定制后只朗读正文。")
        self.assertEqual(payload["control_instruction"], "")


if __name__ == "__main__":
    unittest.main()
