import asyncio
import json
import re
from pathlib import Path

from openai import OpenAI

from server.models import PipelineContext, ScriptsData
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register


DEFAULT_VOICE_INSTRUCTION = "(四川话，语速快一点)"
MAX_VOICE_SENTENCE_CHARS = 50


DEFAULT_AGENT_PROMPT = """你是短视频口播编剧，专门为虚拟主播 Mili 写新闻/科技口播文案。

## 角色设定
- 角色：Mili，Live2D 二次元虚拟主播。
- 人设：懂技术、会摆龙门阵、有分寸的四川妹子。
- 风格：像懂行的朋友在聊天，轻松、有梗、有信息密度，不端着，不强行尬笑。
- 语言：四川话为主；项目名、模型名、论文名、技术术语保留英文原文，并用通俗中文解释。
- 目标：让观众觉得“有趣、有料、听完涨见识”，不是念新闻稿。

## 选题规则
- 先浏览全部素材，建立候选池；素材足够时必须选出 10-20 个互不重复的选题，并说明选择理由。
- 如果素材不足 10 条，尽量覆盖全部有效素材；如果素材很多，至少选择 10 条，不要只挑 3-5 条。
- AI/科技素材优先关注：项目/论文/模型名称、核心方法、关键数据、怎么用、适合谁、和同类方案差异。
- 今日热搜素材优先关注：事件核心看点、真实评论/转录中的亮点、反差、公共信息价值。
- 不要强行把泛生活素材写成科技新闻；素材是什么类型，就按它自己的价值来讲。
- 按 director 聚合播报思路覆盖更多选题。每条入选内容至少交代“发生了什么、关键依据、为什么值得关注”中的两项，不能只复述标题。

## 内容真实性
- 所有事实、数字、引用都必须来自素材摘要，不得编造。
- 明确区分“素材明确给出的事实”和“基于事实的分析判断”；分析可以有，但不能伪装成已证实事实。
- 提到数字、性能、Star、排名、发布时间、机构或作者时必须能在素材中找到依据；没有依据就不要写具体数值。
- 不确定的信息用“可能”“看起来”“从素材看”这类表达。
- 不要输出“请补充素材”“素材不足”“无法生成”这类占位话术；素材摘要不为空时必须完成可播口播。
- 不做人身攻击，不传播未经证实的谣言，不贩卖焦虑。

## 口播结构
- 开头必须有 3 秒钩子：反差、问题、悬念或一句犀利总结。
- 正文要分段，每个入选选题至少按本次配置要求生成足够的 voice 句子，不能把选题压缩成两三句摘要。
- 每个选题依次讲清“它是什么/发生了什么 -> 核心技术或关键机制 -> 实际价值与适用人群 -> 局限或仍待验证之处”。
- 每个选题必须把 selected_topics 中的 key_facts、readme_evidence、technical_analysis、impact 和 caveats 真正展开到口播，不能只把它们留在元数据中。
- 每个选题必须覆盖 overview、mechanism、evidence、use_case、impact、caveat、transition 七种讲解角度；mechanism 和 evidence 可以根据素材拆成多句。
- mechanism 至少写 2 句，分别解释关键模块/流程和它们如何协作；evidence 至少写 2 句，引用不同的素材事实。
- 每个 topic 的最后一句必须是 aspect=transition：自然引出下一条新闻；最后一个 topic 则自然过渡到整期总结。
- transition 不要机械重复“下一条”，要利用前后选题的差异写出承接关系，例如“看完省内存的模型，再看怎么让它自己干活”。
- 介绍技术项目时，要说明它解决的具体问题、关键模块如何协作、用户实际怎么用、相对常见方案有什么不同，以及当前限制。
- evidence 句子必须引用素材中明确出现的功能、架构、数据、命令、接口、技术栈或 README 说明，不能用“很强”“很火”代替证据。
- 专业术语第一次出现时，用一句普通人能理解的话解释；不要只罗列缩写、模型名或功能清单。
- 对 GitHub 项目要说明解决的问题、技术栈/架构亮点、典型使用场景和成熟度；对论文/模型要说明任务、方法、证据和限制。
- 只有素材提供对照依据时才做横向比较，不能凭印象声称“领先”“首个”“最佳”。
- 口播应有专业编辑感：准确使用项目名和数据，解释技术机制、使用场景与局限，避免空泛的“很厉害”“值得关注”。
- 段落之间要有自然转场，比如“接到看这个”“更关键的是”“这就有意思了”。
- 结尾要有一句总结或互动引导，但不要每段都喊“评论区说说”。

## TTS 分句规则
- 不要生成语气、口音、语速、停顿、情绪、表演提示或任何括号指令；代码会在生成后统一添加 TTS 语音指令。
- voice.text 和 subtitle 都只写可朗读的干净正文，不要包含括号说明。
- 每个 voice 元素只能包含一句话，并且必须以中文句号“。”结束。
- 每句话包含结尾句号在内不得超过 50 个字符；内容较长时拆成多个 voice 元素，并保持相同 topic_id。
- 不要使用问号或感叹号结束句子，需要表达疑问或强调时仍用中文句号结束。

## 输出要求
- 只输出 JSON，不要 Markdown。
- 你只负责 selected_topics 和 voice 口播文案，不生成 visual、overlay、live2d、background 等画面轨道；这些会由配音后的导演节点根据真实音频时长生成。
- 不要输出 start_ms、duration_ms、total_duration_ms；后续节点会根据真实音频补齐时长。
- 不要输出 audio_file 或本地音频路径；TTS 节点会在合成后回填。
- selected_topics 必须尽量有 10-20 条；素材少于 10 条时覆盖全部有效素材。
- selected_topics 每项必须包含 id、source、reason、key_facts、technical_analysis、impact、caveats。
- GitHub 选题还必须包含 readme_evidence，至少列出 2 条直接来自 README 的功能、架构、用法或限制证据。
- voice 每项必须包含 topic_id；开头和结尾使用 intro/outro，正文使用对应 selected_topics.id。
- 每个选题的 voice 句数由节点属性指定，不设置单个选题或整篇口播的总字数上限。
- voice 每项还必须包含 aspect，正文只能使用 overview、mechanism、evidence、use_case、impact、caveat 或 transition；每个 topic 必须以 transition 句结束。
- 每句话都要信息完整且不超过 50 个字符；不要靠重复观点或堆形容词凑字数。
"""


@register
class TechBroadcastScriptAgent(BaseNode):
    type = "tech_broadcast_script_agent"
    label = "科技播报口播文案生成"
    category = "Content Processing"
    description = "根据素材识别和音频转录结果生成可供 TTS 使用的科技播报口播脚本"

    inputs = [
        NodeInput(
            name="collected",
            type="CollectedData",
            label="采集数据",
            required=False,
            description="采集节点输出的完整原始选题池，包含尚无本地媒体的科技条目。",
        ),
        NodeInput(
            name="media",
            type="MediaData",
            label="素材",
            required=False,
            description="下载节点输出的素材清单。未连接时会从运行上下文中读取。",
        ),
        NodeInput(
            name="recognized",
            type="*",
            label="素材识别",
            required=False,
            description="素材识别完成信号或识别结果。",
        ),
        NodeInput(
            name="transcribed",
            type="*",
            label="音频转录",
            required=False,
            description="音频转录完成信号或转录结果。",
        ),
    ]
    outputs = [
        NodeOutput(
            name="scripts",
            type="ScriptsData",
            label="口播脚本",
            description="可直接连接到 TTS 节点 scripts 输入的脚本数据。",
        )
    ]

    reads = []
    writes = ["scripts"]
    output_dirs = ["scripts"]
    cacheable = True
    cache_revision = "professional_v7_topic_transitions"
    allowed_tools = []

    config_schema = {
        "model": {"type": "model", "label": "Model", "default": ""},
        "generation_version": {
            "type": "str",
            "label": "生成规则版本",
            "default": "professional_v7_topic_transitions",
            "hidden": True,
        },
        "min_sentences_per_topic": {
            "type": "int",
            "label": "每个选题最少句数",
            "default": 9,
            "min": 9,
            "max": 18,
            "description": "控制每个 topic 的讲解详细程度；每句仍不超过 50 个字符。",
        },
        "voice_instruction": {
            "type": "str",
            "label": "TTS 语音指令",
            "default": DEFAULT_VOICE_INSTRUCTION,
            "description": "由代码统一添加到每个 voice.text；LLM 不生成该指令。",
        },
        "agent_prompt": {
            "type": "text",
            "label": "Agent Prompt",
            "default": DEFAULT_AGENT_PROMPT,
        },
    }

    def fingerprint(self, ctx: PipelineContext) -> str:
        media = self.get_input("media") or ctx.media
        collected = self.get_input("collected") or ctx.collected
        manifest_path = getattr(media, "manifest_path", None)
        manifest_mtime = ""
        if manifest_path and Path(manifest_path).exists():
            manifest_mtime = str(Path(manifest_path).stat().st_mtime_ns)
        collected_files = self._resolve_collected_files(collected)
        collected_signature = [
            (str(path), path.stat().st_mtime_ns)
            for path in collected_files
            if path.exists()
        ]
        raw = json.dumps(
            {
                "model": self.get_config("model", ""),
                "generation_version": self.get_config(
                    "generation_version", "professional_v7_topic_transitions"
                ),
                "min_sentences_per_topic": self.get_config("min_sentences_per_topic", 9),
                "voice_instruction": self.get_config(
                    "voice_instruction", DEFAULT_VOICE_INSTRUCTION
                ),
                "prompt": self.get_config("agent_prompt", ""),
                "manifest_path": str(manifest_path or ""),
                "manifest_mtime": manifest_mtime,
                "collected_files": collected_signature,
                "summary_version": 8,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        import hashlib

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def execute(self, ctx: PipelineContext, on_progress):
        on_progress("Agent 初始化...", 0.0)

        model_name = self.get_config("model", "")
        model_cfg = (ctx.config or {}).get("models", {}).get(model_name)
        if not model_cfg:
            raise RuntimeError(f"Model is not configured: {model_name}")

        media = self.get_input("media") or ctx.media
        collected = self.get_input("collected") or ctx.collected
        manifest = getattr(media, "manifest", None) or {}
        manifest_path = getattr(media, "manifest_path", None)
        if not manifest and manifest_path and Path(manifest_path).exists():
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        material_items = self._material_items(manifest, collected)
        material_items, skipped_github = self._filter_unusable_github_items(material_items)
        if skipped_github:
            ctx.logger.warning(
                "[%s] 跳过 %s 个无有效 README 的 GitHub 仓库: %s",
                self.id,
                len(skipped_github),
                ", ".join(skipped_github),
            )
        material_count = len(material_items)
        expected_topic_count = min(10, material_count)
        material_sources = {f"M{idx:03d}" for idx in range(1, material_count + 1)}
        github_sources = {
            f"M{idx:03d}"
            for idx, item in enumerate(material_items, start=1)
            if str(item.get("source") or "").strip().lower().replace(" ", "_") == "github_trending"
        }
        readme_count, readme_chars = self._validate_github_readmes(material_items)
        material_summary = self._summarize_items(material_items)
        if not material_summary:
            raise RuntimeError("没有可用于生成口播的素材内容，请先连接下载/识别/转录节点。")
        minimum_input_chars = max(2000, expected_topic_count * 800)
        if len(material_summary) < minimum_input_chars:
            raise RuntimeError(
                f"口播输入信息不足: 当前 {len(material_summary)} 字，"
                f"至少需要 {minimum_input_chars} 字；请先完成素材采集、README 下载和识别。"
            )
        ctx.logger.info(
            "[%s] 汇总素材: %s 条, %s 字; GitHub README: %s 个, %s 字",
            self.id,
            material_count,
            len(material_summary),
            readme_count,
            readme_chars,
        )
        on_progress(f"素材汇总完成: {material_count} 条，{len(material_summary)} 字", 0.1)

        client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])
        messages = [
            {"role": "system", "content": self.get_config("agent_prompt", "")},
            {
                "role": "user",
                "content": (
                    "请基于下面素材先做选题，再生成 Mili 的口播文案，返回 JSON 对象。\n"
                    "JSON 格式：\n"
                    "{\n"
                    '  "final": true,\n'
                    '  "title": "标题",\n'
                    '  "hook": "前三秒钩子",\n'
                    '  "selected_topics": [\n'
                    '    {\n'
                    '      "id": "topic_01", "title": "选题名", "source": "M001",\n'
                    '      "reason": "为什么值得讲",\n'
                    '      "key_facts": ["素材明确给出的事实1", "事实2"],\n'
                    '      "readme_evidence": ["README 中的具体证据1", "具体证据2"],\n'
                    '      "technical_analysis": "技术原理、架构或方法分析",\n'
                    '      "impact": "实际价值、适用人群或行业影响",\n'
                    '      "caveats": "限制、风险或仍待验证之处"\n'
                    '    }\n'
                    "  ],\n"
                    '  "voice": [\n'
                    '    {"topic_id": "intro", "aspect": "intro", "text": "开场钩子。", "subtitle": "开场钩子。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "overview", "text": "先说明项目解决的问题。", "subtitle": "先说明项目解决的问题。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "mechanism", "text": "再解释关键模块如何工作。", "subtitle": "再解释关键模块如何工作。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "mechanism", "text": "接着说明模块之间如何协作。", "subtitle": "接着说明模块之间如何协作。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "evidence", "text": "引用素材里的具体技术证据。", "subtitle": "引用素材里的具体技术证据。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "evidence", "text": "再引用一条不同的素材事实。", "subtitle": "再引用一条不同的素材事实。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "use_case", "text": "说明谁能在什么场景使用。", "subtitle": "说明谁能在什么场景使用。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "impact", "text": "解释它带来的实际价值。", "subtitle": "解释它带来的实际价值。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "caveat", "text": "最后交代限制和适用边界。", "subtitle": "最后交代限制和适用边界。"},\n'
                    '    {"topic_id": "topic_01", "aspect": "transition", "text": "顺着这个问题，再来看下一条新方案。", "subtitle": "顺着这个问题，再来看下一条新方案。"},\n'
                    '    {"topic_id": "outro", "aspect": "outro", "text": "总结。", "subtitle": "总结。"}\n'
                    "  ]\n"
                    "}\n"
                    "禁止输出 start_ms、duration_ms、total_duration_ms。\n"
                    f"本次共有 {material_count} 条候选素材，selected_topics 至少选择 {expected_topic_count} 条，"
                    f"素材足够时目标是 10-20 条。每个选题至少对应 "
                    f"{int(self.get_config('min_sentences_per_topic', 9))} 个 voice 句子，"
                    "不设置单个选题或整篇口播的总字数上限。\n"
                    "每个选题必须覆盖 aspect=overview、mechanism、evidence、use_case、impact、caveat，"
                    "其中 mechanism 至少 2 句，evidence 至少 2 句，"
                    "并把 selected_topics 的素材事实、README 证据、技术分析、实际价值和限制逐项展开。"
                    "每个 topic 最后必须写一条 aspect=transition 的自然过渡句，引出下一选题；"
                    "最后一个 topic 过渡到总结。"
                    "不要只报项目名、Star 数和一句功能总结。\n"
                    "不要生成任何语气、口音、语速、停顿、情绪或括号指令，"
                    "代码会在之后统一添加 TTS 语音指令。每个 voice 只能写一句话，"
                    "必须以中文句号“。”结束，包含句号在内不得超过 50 个字符；"
                    "长内容请拆成多个相同 topic_id 的 voice 元素。\n"
                    "source 必须填写素材标题前的 M 编号。每个选题必须先整理至少 2 条 key_facts；"
                    "GitHub 选题还必须从对应 README 正文提取至少 2 条 readme_evidence。"
                    "再给出技术分析、实际价值和局限。"
                    "不能只改写标题，也不能用空泛评价代替技术解释。\n"
                    "如果素材摘要不为空，必须从素材中挑选最有价值的事实完成口播，"
                    "不要回复“素材不足”“请补充素材”“无法生成”等占位话术。\n\n"
                    f"素材：\n{material_summary}"
                ),
            },
        ]

        final = None
        max_steps = 4
        for step in range(max_steps):
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            on_progress(f"Agent 生成脚本 {step + 1}/{max_steps}", 0.15 + step * 0.18)
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_cfg["model"],
                messages=messages,
                temperature=0.35,
                max_tokens=384000,
                response_format={"type": "json_object"},
            )

            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            content = response.choices[0].message.content or "{}"
            on_progress(f"Agent 校验脚本 {step + 1}/{max_steps}", 0.22 + step * 0.18)
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "返回合法 JSON，不要包含 Markdown。"})
                continue

            errors = self._validate_agent_result(
                data,
                expected_topic_count=expected_topic_count,
                allowed_sources=material_sources,
                github_sources=github_sources,
            )
            if not errors:
                final = data
                break

            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": "请修复这些问题并返回完整 JSON：\n" + "\n".join(f"- {err}" for err in errors),
                }
            )

        if final is None:
            raise RuntimeError("Agent did not produce a valid script within max_steps")

        scripts_data = self._write_scripts(ctx, final)
        ctx.scripts = scripts_data
        on_progress("口播脚本生成完成", 1.0)
        return {"scripts": scripts_data}

    def restore_cache(self, ctx: PipelineContext):
        scripts_dir = ctx.data_root / ctx.date / "scripts"
        script_files = sorted(scripts_dir.glob("*.json"))
        scripts = {}
        durations = {}
        for path in script_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            script_id = data.get("id", path.stem)
            scripts[script_id] = data
            durations[script_id] = data.get("total_duration_ms", 0)
        ctx.scripts = ScriptsData(
            dir=scripts_dir,
            files=script_files,
            scripts=scripts,
            total_duration_ms=durations,
        )

    def _material_items(self, manifest: dict, collected) -> list[dict]:
        collected_items = self._load_collected_items(collected, manifest)
        if collected_items:
            return collected_items
        return list(self._iter_manifest_items(manifest))

    def _resolve_collected_files(self, collected) -> list[Path]:
        if collected is None:
            return []
        base_dir = Path(getattr(collected, "dir", "") or "")
        files = []
        for file_ref in getattr(collected, "files", []) or []:
            path = Path(file_ref)
            if not path.is_absolute():
                path = base_dir / path
            if path.suffix.lower() == ".json":
                files.append(path)
        if not files and base_dir.exists():
            files = sorted(base_dir.glob("*.json"))
        return files

    def _load_collected_items(self, collected, manifest: dict) -> list[dict]:
        items = []
        for path in self._resolve_collected_files(collected):
            if path.name.startswith(".") or not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue

            item = dict(data)
            item.setdefault("_manifest_key", path.name)
            media_item = manifest.get(path.name) if isinstance(manifest, dict) else None
            if isinstance(media_item, dict):
                for key in ("images", "video", "readme", "recognized_images"):
                    if media_item.get(key) is not None:
                        item[key] = media_item[key]
            items.append(item)
        return items

    def _summarize_manifest(self, manifest: dict) -> str:
        return self._summarize_items(list(self._iter_manifest_items(manifest)))

    def _summarize_items(self, manifest_items: list[dict]) -> str:
        items = []

        for idx, item in enumerate(manifest_items[:80], start=1):
            title = self._title_for_item(item, idx)
            desc_parts = self._collect_text_fields(item)
            readme_text = self._collect_readme_text(item)
            transcript_text = self._collect_transcripts(item)
            key_moments = self._collect_key_moments(item)
            image_notes = self._collect_image_notes(item)
            parts = [f"### [M{idx:03d}] {title}"]
            if item.get("author"):
                parts.append(f"作者: {item.get('author')}")
            if desc_parts:
                parts.append(f"摘要: {self._join_limited(desc_parts, 1800)}")
            if readme_text:
                parts.append(f"README 正文:\n{readme_text[:8000]}")
            if transcript_text:
                parts.append(f"转录: {transcript_text[:1600]}")
            if key_moments:
                parts.append(f"关键画面: {json.dumps(key_moments, ensure_ascii=False, default=str)[:1000]}")
            if image_notes:
                parts.append(f"图片识别: {self._join_limited(image_notes, 1200)}")
            items.append("\n".join(parts))
        return "\n\n".join(items)[:160000]

    def _iter_manifest_items(self, manifest: dict):
        if isinstance(manifest, list):
            yield from [item for item in manifest if isinstance(item, dict)]
            return
        if not isinstance(manifest, dict):
            return

        for key in ("items", "media", "videos", "assets", "downloaded"):
            value = manifest.get(key)
            if isinstance(value, list):
                yield from [item for item in value if isinstance(item, dict)]
            elif isinstance(value, dict):
                for sub_key, item in value.items():
                    if isinstance(item, dict):
                        yield self._with_manifest_key(item, sub_key)

        if not any(key in manifest for key in ("items", "media", "videos", "assets", "downloaded")):
            dict_values = [(key, value) for key, value in manifest.items() if isinstance(value, dict)]
            scalar_values = [value for value in manifest.values() if not isinstance(value, (dict, list))]
            if dict_values and not scalar_values:
                for key, item in dict_values:
                    yield self._with_manifest_key(item, key)
            else:
                yield manifest

    def _with_manifest_key(self, item: dict, key: str) -> dict:
        copied = dict(item)
        copied.setdefault("_manifest_key", key)
        return copied

    def _title_for_item(self, item: dict, idx: int) -> str:
        title = item.get("title") or item.get("name") or item.get("id")
        if title:
            return str(title)
        key = str(item.get("_manifest_key") or "")
        if key:
            return Path(key).stem.replace("_", " ")
        return f"素材 {idx}"

    def _collect_text_fields(self, item: dict) -> list[str]:
        parts = []
        for key in ("description", "summary", "text", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())

        video = item.get("video")
        if isinstance(video, dict):
            for key in ("summary", "description", "transcript_hint"):
                value = video.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())

        return parts

    def _collect_readme_text(self, item: dict) -> str:
        readme = item.get("readme")
        if not isinstance(readme, dict):
            return ""
        for key in ("content", "summary", "description"):
            value = readme.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        readme_path = readme.get("path")
        if not readme_path:
            return ""
        path = Path(readme_path)
        try:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")[:12000]
        except OSError:
            pass
        return ""

    def _validate_github_readmes(self, items: list[dict]) -> tuple[int, int]:
        readme_count = 0
        readme_chars = 0
        for idx, item in enumerate(items, start=1):
            source = str(item.get("source") or "").strip().lower().replace(" ", "_")
            if source != "github_trending":
                continue
            text = self._collect_readme_text(item)
            if len(text.strip()) < 50:
                continue
            readme_count += 1
            readme_chars += len(text)
        return readme_count, readme_chars

    def _filter_unusable_github_items(self, items: list[dict]) -> tuple[list[dict], list[str]]:
        valid_items = []
        skipped = []
        for idx, item in enumerate(items, start=1):
            source = str(item.get("source") or "").strip().lower().replace(" ", "_")
            if source == "github_trending" and len(self._collect_readme_text(item).strip()) < 50:
                skipped.append(self._title_for_item(item, idx))
                continue
            valid_items.append(item)
        return valid_items, skipped

    def _collect_transcripts(self, item: dict) -> str:
        transcripts = []
        for source in (item, item.get("video") if isinstance(item.get("video"), dict) else None):
            if not isinstance(source, dict):
                continue
            for key in ("transcript", "segments", "raw_segments"):
                text = self._segments_to_text(source.get(key))
                if text:
                    transcripts.append(text)
        return "\n".join(transcripts)

    def _collect_key_moments(self, item: dict):
        for source in (item, item.get("video") if isinstance(item.get("video"), dict) else None):
            if not isinstance(source, dict):
                continue
            value = source.get("key_moments") or source.get("_video_key_moments")
            if value:
                return value
        return []

    def _collect_image_notes(self, item: dict) -> list[str]:
        notes = []
        image_groups = []
        for key in ("images", "recognized_images"):
            value = item.get(key)
            if isinstance(value, list):
                image_groups.append(value)
        readme = item.get("readme")
        if isinstance(readme, dict):
            value = readme.get("recognized_images")
            if isinstance(value, list):
                image_groups.append(value)

        for group in image_groups:
            for image in group[:5]:
                if isinstance(image, dict):
                    desc = image.get("description") or image.get("caption") or image.get("summary")
                    if desc:
                        notes.append(str(desc))
        return notes

    def _join_limited(self, values: list[str], limit: int) -> str:
        text = "\n".join(str(value).strip() for value in values if str(value).strip())
        return text[:limit]

    def _segments_to_text(self, transcript) -> str:
        if isinstance(transcript, str):
            return transcript
        if not isinstance(transcript, list):
            return ""
        texts = []
        for seg in transcript:
            if isinstance(seg, dict):
                text = seg.get("text") or seg.get("content") or ""
                if text:
                    start = seg.get("start")
                    end = seg.get("end")
                    if start is not None and end is not None:
                        texts.append(f"[{start}-{end}] {text}")
                    else:
                        texts.append(str(text))
            elif isinstance(seg, str):
                texts.append(seg)
        return "\n".join(texts)

    def _validate_agent_result(
        self,
        data: dict,
        expected_topic_count: int = 10,
        allowed_sources: set[str] | None = None,
        github_sources: set[str] | None = None,
    ) -> list[str]:
        errors = []
        if not isinstance(data, dict):
            return ["结果必须是 JSON 对象。"]
        if data.get("final") is not True:
            errors.append('必须包含 "final": true。')
        voice = data.get("voice")
        selected_topics = data.get("selected_topics")
        minimum_topics = max(1, expected_topic_count)
        if not isinstance(selected_topics, list) or len(selected_topics) < minimum_topics:
            errors.append(
                f"当前素材量要求 selected_topics 至少 {minimum_topics} 条；"
                "素材足够时必须覆盖 10-20 条，不能只选 3-5 条。"
            )
        topic_ids = []
        if isinstance(selected_topics, list):
            for idx, topic in enumerate(selected_topics):
                if not isinstance(topic, dict):
                    errors.append(f"selected_topics[{idx}] 必须是对象。")
                    continue
                topic_id = str(topic.get("id", "")).strip()
                if not topic_id:
                    errors.append(f"selected_topics[{idx}] 缺少 id。")
                elif topic_id in topic_ids:
                    errors.append(f"selected_topics id 重复: {topic_id}")
                else:
                    topic_ids.append(topic_id)
                topic_source = str(topic.get("source", "")).strip()
                if allowed_sources is not None and topic_source not in allowed_sources:
                    errors.append(
                        f"selected_topics[{idx}].source 必须引用有效素材编号: {topic_source or '空'}"
                    )
                minimum_field_lengths = {
                    "title": 2,
                    "source": 1,
                    "reason": 15,
                    "technical_analysis": 40,
                    "impact": 20,
                    "caveats": 10,
                }
                for field, minimum_length in minimum_field_lengths.items():
                    if len(str(topic.get(field, "")).strip()) < minimum_length:
                        errors.append(f"selected_topics[{idx}].{field} 内容不足。")
                key_facts = topic.get("key_facts")
                valid_facts = (
                    [fact for fact in key_facts if len(str(fact).strip()) >= 8]
                    if isinstance(key_facts, list)
                    else []
                )
                if len(valid_facts) < 2:
                    errors.append(f"selected_topics[{idx}].key_facts 至少需要 2 条素材事实。")
                if github_sources is not None and topic_source in github_sources:
                    readme_evidence = topic.get("readme_evidence")
                    valid_readme_evidence = (
                        [evidence for evidence in readme_evidence if len(str(evidence).strip()) >= 8]
                        if isinstance(readme_evidence, list)
                        else []
                    )
                    if len(valid_readme_evidence) < 2:
                        errors.append(
                            f"selected_topics[{idx}].readme_evidence 至少需要 2 条 README 证据。"
                        )

        min_sentences_per_topic = max(9, int(self.get_config("min_sentences_per_topic", 9)))
        minimum_voice_segments = max(4, minimum_topics * min_sentences_per_topic + 2)
        if not isinstance(voice, list):
            errors.append("voice 必须是数组。")
        else:
            if len(voice) < minimum_voice_segments:
                errors.append(
                    f"voice 至少需要 {minimum_voice_segments} 段；每个入选选题至少需要 "
                    f"{min_sentences_per_topic} 个详细讲解句子。"
                )

            allowed_topic_aspects = {
                "overview",
                "mechanism",
                "evidence",
                "use_case",
                "impact",
                "caveat",
                "transition",
            }
            required_topic_aspects = {
                "overview",
                "mechanism",
                "evidence",
                "use_case",
                "impact",
                "caveat",
                "transition",
            }
            topic_voice = {topic_id: [] for topic_id in topic_ids}
            for idx, item in enumerate(voice):
                if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                    errors.append(f"voice[{idx}] 必须包含 text。")
                    continue
                topic_id = str(item.get("topic_id", "")).strip()
                aspect = str(item.get("aspect", "")).strip()
                if not topic_id:
                    errors.append(f"voice[{idx}] 缺少 topic_id。")
                elif topic_id in topic_voice:
                    topic_voice[topic_id].append(item)
                    if aspect not in allowed_topic_aspects:
                        errors.append(
                            f"voice[{idx}].aspect 必须是 overview、mechanism、evidence、"
                            "use_case、impact、caveat 或 transition。"
                        )
                elif topic_id not in {"intro", "outro"}:
                    errors.append(f"voice[{idx}].topic_id 未出现在 selected_topics: {topic_id}")
                elif aspect != topic_id:
                    errors.append(f"voice[{idx}].aspect 对 {topic_id} 必须填写 {topic_id}。")
                if "duration_ms" in item or "start_ms" in item:
                    errors.append(f"voice[{idx}] 不要包含 start_ms/duration_ms，后续节点会补齐时长。")
                text = str(item.get("text", "")).strip()
                if self._contains_inline_control(text):
                    errors.append(
                        f"voice[{idx}].text 不要包含语气、口音、语速或其他括号指令；"
                        "TTS 指令会由代码统一添加。"
                    )
                if not text.endswith("。"):
                    errors.append(f"voice[{idx}].text 必须以中文句号“。”结束。")
                if text.count("。") != 1 or re.search(r"[！？!?]", text):
                    errors.append(f"voice[{idx}].text 只能包含一句话，不能包含多个句子。")
                if self._text_char_count(text) > MAX_VOICE_SENTENCE_CHARS:
                    errors.append(
                        f"voice[{idx}].text 超过 {MAX_VOICE_SENTENCE_CHARS} 个字符，"
                        "请拆成多个相同 topic_id 的 voice 元素。"
                    )
            for topic_id, items in topic_voice.items():
                if len(items) < min_sentences_per_topic:
                    errors.append(
                        f"选题 {topic_id} 至少需要 {min_sentences_per_topic} 个 voice 句子，"
                        "请展开事实背景、技术机制、证据、场景、影响和限制。"
                    )
                aspects = {str(item.get("aspect", "")).strip() for item in items}
                missing_aspects = sorted(required_topic_aspects - aspects)
                if missing_aspects:
                    errors.append(
                        f"选题 {topic_id} 缺少详细讲解角度: {', '.join(missing_aspects)}。"
                    )
                if items and str(items[-1].get("aspect", "")).strip() != "transition":
                    errors.append(f"选题 {topic_id} 的最后一个 voice 必须是 transition 过渡句。")
                aspect_counts = {}
                for item in items:
                    aspect = str(item.get("aspect", "")).strip()
                    aspect_counts[aspect] = aspect_counts.get(aspect, 0) + 1
                if aspect_counts.get("mechanism", 0) < 2:
                    errors.append(f"选题 {topic_id} 的 mechanism 至少需要 2 句技术机制说明。")
                if aspect_counts.get("evidence", 0) < 2:
                    errors.append(f"选题 {topic_id} 的 evidence 至少需要 2 句不同素材证据。")
            combined_text = "\n".join(
                str(item.get("text", "")) for item in voice if isinstance(item, dict)
            )
            blocked_phrases = ["请补充", "素材不足", "素材缺失", "没有正文内容", "无法生成", "提供更多"]
            for phrase in blocked_phrases:
                if phrase in combined_text:
                    errors.append(f"voice 不能包含占位话术：{phrase}")
                    break
        if "duration_ms" in data or "total_duration_ms" in data:
            errors.append("顶层不要包含 duration_ms/total_duration_ms，后续节点会根据真实音频补齐。")
        return errors

    def _write_scripts(self, ctx: PipelineContext, data: dict) -> ScriptsData:
        scripts_dir = ctx.data_root / ctx.date / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        voice_instruction = self._normalize_voice_instruction(
            self.get_config("voice_instruction", DEFAULT_VOICE_INSTRUCTION)
        )
        voice_items = []
        for item in data.get("voice", []):
            if not isinstance(item, dict):
                continue
            topic_id = str(item.get("topic_id") or "").strip()
            aspect = str(item.get("aspect") or "").strip()
            for sentence in self._split_voice_sentences(str(item.get("text", ""))):
                voice_items.append(
                    {
                        "id": f"voice_{len(voice_items):02d}",
                        "topic_id": topic_id,
                        "aspect": aspect,
                        "text": f"{voice_instruction}{sentence}",
                        "subtitle": sentence,
                        "start_ms": 0,
                        "duration_ms": 0,
                    }
                )

        script = {
            "id": "tech_broadcast_script",
            "title": data.get("title") or "科技播报口播",
            "type": "tech_broadcast",
            "hook": data.get("hook", ""),
            "total_duration_ms": 0,
            "tracks": {"voice": voice_items, "visual": []},
            "meta": {
                "generator": self.type,
                "selected_topics": data.get("selected_topics") or [],
                "duration_source": "audio_alignment",
                "voice_instruction": voice_instruction,
            },
        }

        script_path = scripts_dir / f"{script['id']}.json"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

        return ScriptsData(
            dir=scripts_dir,
            files=[script_path],
            scripts={script["id"]: script},
            total_duration_ms={script["id"]: 0},
        )

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _strip_inline_controls(self, text: str) -> str:
        return re.sub(r"（[^（）]{0,40}）|\([^()]{0,40}\)", "", text)

    def _contains_inline_control(self, text: str) -> bool:
        return bool(re.search(r"（[^（）]{0,40}）|\([^()]{0,40}\)", text))

    def _normalize_voice_instruction(self, instruction: str) -> str:
        instruction = self._clean_text(str(instruction or DEFAULT_VOICE_INSTRUCTION))
        if not instruction:
            instruction = DEFAULT_VOICE_INSTRUCTION
        return f"({instruction.strip('()（） ')})"

    def _split_voice_sentences(self, text: str) -> list[str]:
        clean_text = self._clean_text(self._strip_inline_controls(text))
        if not clean_text:
            return []

        sentences = []
        for raw_sentence in clean_text.split("。"):
            body = raw_sentence.strip(" \t\r\n。")
            if not body:
                continue
            sentences.append(f"{body}。")
        return sentences

    def _text_char_count(self, text: str) -> int:
        return len(re.sub(r"\s+", "", text))
