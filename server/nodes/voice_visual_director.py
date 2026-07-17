import asyncio
import copy
import hashlib
import json
from pathlib import Path

from openai import OpenAI

from server.models import AlignedData, AudioData, MediaData, PipelineContext, ScriptsData
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register


DEFAULT_AGENT_PROMPT = """你是 VideoFactory 的配音后编排导演 Agent。

你的输入是一份已经完成 TTS 的口播脚本：tracks.voice 已经包含真实 start_ms、duration_ms、audio_file。你只能根据这条真实 voice 轨生成其他轨道，不允许改写、删减、重排 voice。

目标：
- 保留 voice 轨原样，不输出 voice 轨。
- 根据口播文本、真实时长和素材清单生成 visual、overlay、live2d、background。
- 输出可以直接进入 overlay/visual/live2d/compose，不再经过 align。
- 每条新闻都从演播室主场景开始，并在新闻结束前回到演播室主场景。

轨道规则：
- visual：主画面轨。真实素材只在最需要佐证口播时短暂出现，不要让素材覆盖整条新闻；没有合适素材时使用 type="remotion" 动态组件。
  image/video_clip 会覆盖演播室并触发右下角小主播；remotion 是透明信息层，不触发小主播，底下仍显示演播室和大主播。
- overlay：弹幕、数据卡、引用框、重点文字等叠加层。
- live2d：Mili 表情/动作轨，只写 start_ms、duration_ms、action。
- background：全程背景，覆盖 0 到 total_duration_ms。

可用 visual 类型：
- image: {start_ms, duration_ms, type:"image", source:"本地图片路径", caption, animation:"ken_burns"}
- video_clip: {start_ms, duration_ms, type:"video_clip", source:"本地视频路径", time_range:[start,end], play_audio:false, caption, transition:"fade"}
- remotion: {start_ms, duration_ms, type:"remotion", component, props}

可用 remotion component：
- comment_scroll: props={comments:[...], direction:"right_to_left"}
- data_reveal: props={title, value, unit, description, color}
- info_panel: props={title, points:[...], color}
- highlight_text: props={text, sub_text, color, position:"center"}
- quote_box: props={text, source, color}
- code_scroll: props={code, language, title}
- stats_card: props={name, stars, forks, language, description}
- model_card: props={name, downloads, task, description}
- ranking_table: props={title, items:[{rank,name,value}]}

overlay 输出格式：
- overlay 条目直接使用 type="comment_scroll|data_reveal|info_panel|highlight_text|quote_box|code_scroll|stats_card|model_card|ranking_table"。
- overlay 不要写 type="remotion"，也不要写 component；只有 visual 轨的 Remotion 条目使用 type="remotion" + component。
- stars、forks、downloads、value、unit 等展示值统一输出字符串。

可用 live2d action：
- exp_pleasant, exp_happy_squint, exp_thinking, exp_curious, exp_neutral, exp_shy_smile, exp_stunned, exp_dejected
- motion_idle, motion_happy_wave, motion_lecture, motion_encourage
- sp_cast_success, sp_cast_fail, sp_thumbs_up

时间规则：
- 所有条目的 start_ms/duration_ms 必须在 0 到 total_duration_ms 内。
- voice 中相同 topic_id 的连续句子是一条新闻；intro/outro 不算新闻。
- 每条新闻开头和结尾都必须保留本次用户规则指定的纯演播室时间，不放 image/video_clip。
- 单个 image/video_clip 必须遵守本次用户规则指定的时长上限，且必须写 transition="fade"。
- 同一条新闻内的 image/video_clip 总占用不得超过本次用户规则指定的比例。
- 同一条新闻使用多个素材段时，中间必须按本次用户规则指定的时长回到演播室，不要素材接素材。
- 每个 image/video_clip 播放期间至少安排一个与其时间重叠的 visual remotion 信息层，用数据卡、要点、引用或项目卡丰富画面。
- visual 不要覆盖全程；无素材的时间就是演播室主场景，可以用透明 remotion 丰富但不能遮掉主播。
- overlay 不要过密，优先覆盖重点句、数据、引用、转场。
- live2d 可以覆盖全程，按口播情绪切换。
- background 必须至少一条，duration_ms 等于 total_duration_ms。

素材规则：
- image/video_clip 的 source 必须使用素材清单中出现的本地文件路径，不要写 URL。
- 素材清单中只要存在与当前口播相关的 images/videos，就必须把相关真实素材放入 visual；不能整条 visual 全部使用 remotion。
- 不确定素材是否存在时，使用 remotion，而不是编造路径。
- 所有事实、数据、引用都必须来自口播或素材摘要，不要新增事实。

输出严格 JSON，不要 Markdown：
{
  "final": true,
  "tracks": {
    "visual": [],
    "overlay": [],
    "live2d": [],
    "background": []
  }
}
"""


@register
class VoiceVisualDirectorAgent(BaseNode):
    type = "voice_visual_director_agent"
    label = "配音后轨道导演"
    category = "内容处理"
    description = "根据已配音口播脚本生成 visual/overlay/live2d/background 轨道，不修改 voice 轨。"
    icon = "导"
    color = "#7C3AED"
    node_kind = "agent"
    cache_revision = "studio_news_transitions_v4"

    inputs = [
        NodeInput(
            name="scripts",
            type="ScriptsData",
            label="已配音脚本",
            required=True,
            description="TTS 回填真实 duration/audio_file 后的口播脚本。",
        ),
        NodeInput(
            name="audio",
            type="AudioData",
            label="音频",
            required=True,
            description="TTS 输出的音频数据和 durations.json。",
        ),
        NodeInput(
            name="media",
            type="MediaData",
            label="素材",
            required=False,
            description="下载/识别/转录后的素材清单，用于选择画面、引用和数据卡。",
        ),
    ]
    outputs = [
        NodeOutput(
            name="aligned",
            type="AlignedData",
            label="最终脚本",
            description="无需再对齐、可直接进入渲染与合成的多轨脚本。",
        )
    ]

    writes = ["aligned"]
    output_dirs = ["scripts_aligned"]
    cacheable = False

    config_schema = {
        "model": {"type": "model", "label": "模型", "default": ""},
        "max_material_duration_ms": {
            "type": "int",
            "label": "单段素材最长时长(ms)",
            "default": 4500,
            "min": 1500,
            "max": 10000,
        },
        "studio_return_ms": {
            "type": "int",
            "label": "演播室停留时长(ms)",
            "default": 900,
            "min": 300,
            "max": 3000,
            "description": "每条新闻头尾以及相邻素材之间保留的演播室画面时长。",
        },
        "max_material_ratio": {
            "type": "float",
            "label": "素材最大占比",
            "default": 0.45,
            "min": 0.1,
            "max": 0.8,
            "step": 0.05,
        },
        "agent_prompt": {
            "type": "text",
            "label": "Agent 指令",
            "default": DEFAULT_AGENT_PROMPT,
        },
    }

    def fingerprint(self, ctx: PipelineContext) -> str:
        scripts = self.get_input("scripts") or ctx.scripts
        audio = self.get_input("audio") or ctx.audio
        script_mtimes = []
        for path in self._script_files(scripts):
            if Path(path).exists():
                script_mtimes.append([str(path), Path(path).stat().st_mtime_ns])
        durations_path = getattr(audio, "durations_path", None)
        durations_mtime = Path(durations_path).stat().st_mtime_ns if durations_path and Path(durations_path).exists() else ""
        raw = json.dumps(
            {
                "model": self.get_config("model", ""),
                "prompt": self.get_config("agent_prompt", ""),
                "max_material_duration_ms": self.get_config("max_material_duration_ms", 4500),
                "studio_return_ms": self.get_config("studio_return_ms", 900),
                "max_material_ratio": self.get_config("max_material_ratio", 0.45),
                "scripts": script_mtimes,
                "durations_mtime": durations_mtime,
                "version": 2,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def execute(self, ctx: PipelineContext, on_progress):
        scripts = self.get_input("scripts") or ctx.scripts
        audio = self.get_input("audio") or ctx.audio
        media = self.get_input("media") or ctx.media
        if scripts is None:
            raise RuntimeError("缺少已配音脚本输入")
        if audio is None:
            raise RuntimeError("缺少 TTS 音频输入")

        model_name = self.get_config("model", "")
        model_cfg = self._resolve_model(ctx, model_name)
        client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])

        aligned_dir = ctx.data_root / ctx.date / "scripts_aligned"
        aligned_dir.mkdir(parents=True, exist_ok=True)
        media_summary = self._summarize_media(media)
        available_media_paths = self._available_media_paths(media)

        aligned_files = []
        aligned_scripts = {}
        script_files = self._script_files(scripts)
        for index, script_path in enumerate(script_files):
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            script = json.loads(Path(script_path).read_text(encoding="utf-8"))
            script_id = script.get("id", Path(script_path).stem)
            script_base = 0.1 + 0.8 * index / max(len(script_files), 1)
            script_span = 0.8 / max(len(script_files), 1)
            on_progress(f"生成多轨脚本 [{index + 1}/{len(script_files)}]: {script_id}", script_base)

            draft = await self._generate_tracks(
                ctx,
                client,
                model_cfg,
                script,
                media_summary,
                available_media_paths,
                lambda message, progress, _base=script_base, _span=script_span: on_progress(
                    f"{script_id}: {message}",
                    _base + _span * progress,
                ),
            )
            final_script = self._merge_tracks(script, draft)
            output_path = aligned_dir / Path(script_path).name
            output_path.write_text(json.dumps(final_script, ensure_ascii=False, indent=2), encoding="utf-8")
            aligned_files.append(output_path)
            aligned_scripts[script_id] = final_script

        ctx.aligned = AlignedData(
            dir=aligned_dir,
            files=aligned_files,
            scripts=aligned_scripts,
        )
        on_progress(f"多轨脚本完成: {len(aligned_files)} 个", 1.0)
        return {"aligned": ctx.aligned}

    def restore_cache(self, ctx: PipelineContext):
        aligned_dir = ctx.data_root / ctx.date / "scripts_aligned"
        aligned_files = sorted(aligned_dir.glob("*.json"))
        aligned_scripts = {}
        for path in aligned_files:
            aligned_scripts[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        ctx.aligned = AlignedData(dir=aligned_dir, files=aligned_files, scripts=aligned_scripts)

    async def _generate_tracks(
        self,
        ctx,
        client,
        model_cfg,
        script: dict,
        media_summary: str,
        available_media_paths: list[str],
        progress_callback=None,
    ) -> dict:
        messages = self._messages(script, media_summary)
        final = None
        last_errors = []
        max_steps = 3
        for step in range(max_steps):
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()

            if progress_callback:
                progress_callback(f"Agent 生成轨道 {step + 1}/{max_steps}", 0.1 + 0.7 * step / max_steps)
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_cfg["model"],
                messages=messages,
                temperature=0.25,
                max_tokens=384000,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "返回合法 JSON，不要 Markdown。"})
                continue

            errors = self._validate_agent_result(data, script, available_media_paths)
            if not errors:
                final = data
                if progress_callback:
                    progress_callback("轨道校验通过", 0.95)
                break
            last_errors = errors
            if progress_callback:
                progress_callback(f"轨道校验发现 {len(errors)} 个问题，准备修复", 0.25 + 0.7 * (step + 1) / max_steps)

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "修复以下问题并返回完整 JSON：\n" + "\n".join(f"- {e}" for e in errors)})

        if final is None:
            if available_media_paths:
                details = "; ".join(last_errors) if last_errors else "模型未返回合法轨道"
                raise RuntimeError(f"轨道导演未能生成包含真实素材的 Visual 轨: {details}")
            return {"tracks": self._default_tracks(script)}
        return final

    def _messages(self, script: dict, media_summary: str) -> list[dict]:
        max_material_duration_ms = int(self.get_config("max_material_duration_ms", 4500))
        studio_return_ms = int(self.get_config("studio_return_ms", 900))
        max_material_ratio = float(self.get_config("max_material_ratio", 0.45))
        return [
            {"role": "system", "content": self.get_config("agent_prompt", DEFAULT_AGENT_PROMPT)},
            {
                "role": "user",
                "content": (
                    "请基于下面已配音口播和素材，生成除 voice 之外的其他轨道。\n"
                    "绝对不要输出 voice，也不要修改 voice。\n\n"
                    "本次编排硬性要求：\n"
                    f"- 单个 image/video_clip 不超过 {max_material_duration_ms}ms，并设置 transition=fade。\n"
                    f"- 每条新闻头尾、同新闻相邻素材之间至少保留 {studio_return_ms}ms 演播室主场景。\n"
                    f"- 每条新闻的不透明素材总时长最多占该新闻时长的 {max_material_ratio:.0%}。\n"
                    "- 每个 image/video_clip 时间段必须重叠一个 visual type=remotion 条目，"
                    "用信息卡、数据、引用或要点丰富素材画面。\n"
                    "- topic_id 表示新闻边界，intro/outro 不算新闻。\n\n"
                    f"脚本摘要：\n{self._script_summary(script)}\n\n"
                    f"素材摘要：\n{media_summary or '没有可用素材时，请使用 remotion 组件补足视觉轨。'}"
                ),
            },
        ]

    def _resolve_model(self, ctx: PipelineContext, model_name: str) -> dict:
        models = (ctx.config or {}).get("models", {})
        if model_name and model_name in models:
            return models[model_name]
        for cfg in models.values():
            if isinstance(cfg, dict) and cfg.get("base_url") and cfg.get("api_key") and cfg.get("model"):
                return cfg
        raise RuntimeError("未配置可用的 LLM 模型")

    def _script_files(self, scripts: ScriptsData | None) -> list[Path]:
        if not scripts:
            return []
        files = [Path(p) for p in (scripts.files or []) if Path(p).exists()]
        if files:
            return sorted(files)
        scripts_dir = Path(scripts.dir)
        return sorted(scripts_dir.glob("*.json")) if scripts_dir.exists() else []

    def _script_summary(self, script: dict) -> str:
        tracks = script.get("tracks", {})
        voice = tracks.get("voice", [])
        total_ms = int(script.get("total_duration_ms", 0) or 0)
        rows = [
            f"id: {script.get('id')}",
            f"title: {script.get('title')}",
            f"total_duration_ms: {total_ms}",
            "voice:",
        ]
        for idx, item in enumerate(voice):
            rows.append(
                json.dumps(
                    {
                        "index": idx,
                        "topic_id": item.get("topic_id", ""),
                        "aspect": item.get("aspect", ""),
                        "start_ms": item.get("start_ms", 0),
                        "duration_ms": item.get("duration_ms", 0),
                        "audio_file": item.get("audio_file", ""),
                        "text": item.get("text", ""),
                        "subtitle": item.get("subtitle", ""),
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(rows)[:20000]

    def _summarize_media(self, media: MediaData | None) -> str:
        manifest = getattr(media, "manifest", None) or {}
        manifest_path = getattr(media, "manifest_path", None)
        if not manifest and manifest_path and Path(manifest_path).exists():
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        items = list(self._iter_manifest_items(manifest))[:40]
        rows = []
        for idx, item in enumerate(items, start=1):
            title = item.get("title") or item.get("name") or item.get("id") or item.get("_manifest_key") or f"素材 {idx}"
            row = [f"### {idx}. {title}"]
            for key in ("summary", "description", "text", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    row.append(f"{key}: {value[:500]}")
                    break
            image_paths = self._collect_image_paths(item)
            video_paths = self._collect_video_paths(item)
            if image_paths:
                row.append("images: " + ", ".join(image_paths[:5]))
            if video_paths:
                row.append("videos: " + ", ".join(video_paths[:3]))
            comments = item.get("top_comments") or item.get("comments") or []
            if isinstance(comments, list) and comments:
                row.append("comments: " + json.dumps(comments[:5], ensure_ascii=False, default=str)[:800])
            rows.append("\n".join(row))
        return "\n\n".join(rows)[:24000]

    def _available_media_paths(self, media: MediaData | None) -> list[str]:
        manifest = getattr(media, "manifest", None) or {}
        manifest_path = getattr(media, "manifest_path", None)
        if not manifest and manifest_path and Path(manifest_path).exists():
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        paths = []
        for item in self._iter_manifest_items(manifest):
            paths.extend(self._collect_image_paths(item))
            paths.extend(self._collect_video_paths(item))

        existing = []
        seen = set()
        for value in paths:
            path = Path(value)
            if not path.is_file():
                continue
            normalized = str(path.resolve()).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            existing.append(str(path.resolve()))
        return existing[:120]

    def _collect_image_paths(self, item: dict) -> list[str]:
        paths = self._collect_paths(item, ("_local_images", "images", "recognized_images"))
        readme = item.get("readme")
        if isinstance(readme, dict):
            paths.extend(self._collect_paths(readme, ("images", "_local_images", "recognized_images")))
        return paths

    def _iter_manifest_items(self, manifest):
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
                        copied = dict(item)
                        copied.setdefault("_manifest_key", sub_key)
                        yield copied
        if not any(key in manifest for key in ("items", "media", "videos", "assets", "downloaded")):
            for key, value in manifest.items():
                if isinstance(value, dict):
                    copied = dict(value)
                    copied.setdefault("_manifest_key", key)
                    yield copied

    def _collect_paths(self, item: dict, keys: tuple[str, ...]) -> list[str]:
        paths = []
        for key in keys:
            value = item.get(key)
            if not isinstance(value, list):
                continue
            for entry in value:
                if isinstance(entry, str):
                    paths.append(entry)
                elif isinstance(entry, dict):
                    path = entry.get("path") or entry.get("local_path") or entry.get("file")
                    if path:
                        paths.append(str(path))
        return paths

    def _collect_video_paths(self, item: dict) -> list[str]:
        paths = []
        for key in ("_video_path", "video_path", "local_video", "path"):
            value = item.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
        video = item.get("video")
        if isinstance(video, dict):
            for key in ("path", "local_path", "_video_path"):
                value = video.get(key)
                if isinstance(value, str) and value:
                    paths.append(value)
        return paths

    def _validate_agent_result(
        self,
        data: dict,
        script: dict,
        available_media_paths: list[str] | None = None,
    ) -> list[str]:
        errors = []
        if not isinstance(data, dict):
            return ["结果必须是 JSON 对象"]
        if data.get("final") is not True:
            errors.append('必须包含 "final": true')
        tracks = data.get("tracks")
        if not isinstance(tracks, dict):
            errors.append("tracks 必须是对象")
            return errors
        if "voice" in tracks:
            errors.append("不要输出 voice 轨，voice 必须由系统保留原样")

        total_ms = int(script.get("total_duration_ms", 0) or 0)
        allowed = {"visual", "overlay", "live2d", "background"}
        for name, items in tracks.items():
            if name not in allowed and name != "voice":
                errors.append(f"不支持的轨道: {name}")
                continue
            if name == "voice":
                continue
            if not isinstance(items, list):
                errors.append(f"tracks.{name} 必须是数组")
                continue
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"tracks.{name}[{idx}] 必须是对象")
                    continue
                start = int(item.get("start_ms", 0) or 0)
                duration = int(item.get("duration_ms", 0) or 0)
                if start < 0 or duration <= 0:
                    errors.append(f"tracks.{name}[{idx}] start_ms/duration_ms 无效")
                if total_ms and start + duration > total_ms + 500:
                    errors.append(f"tracks.{name}[{idx}] 超出 total_duration_ms")

        available_media_paths = available_media_paths or []
        visual_items = tracks.get("visual") if isinstance(tracks.get("visual"), list) else []
        material_items = [
            item for item in visual_items
            if isinstance(item, dict) and item.get("type") in {"image", "video_clip"}
        ]
        remotion_items = [
            item for item in visual_items
            if isinstance(item, dict) and item.get("type") == "remotion"
        ]
        if available_media_paths and not material_items:
            errors.append("存在可用本地图片/视频，但 visual 全部使用了 remotion；请选入与口播相关的真实素材")

        allowed_sources = {
            str(Path(path).resolve()).casefold()
            for path in available_media_paths
        }
        for idx, item in enumerate(visual_items):
            if not isinstance(item, dict) or item.get("type") not in {"image", "video_clip"}:
                continue
            source = str(item.get("source") or "").strip()
            if not source:
                errors.append(f"tracks.visual[{idx}] 缺少 source")
                continue
            normalized = str(Path(source).resolve()).casefold()
            if normalized not in allowed_sources:
                errors.append(f"tracks.visual[{idx}].source 不在可用素材清单中: {source}")

        max_material_duration_ms = int(self.get_config("max_material_duration_ms", 4500))
        studio_return_ms = int(self.get_config("studio_return_ms", 900))
        max_material_ratio = float(self.get_config("max_material_ratio", 0.45))
        topic_windows = self._topic_windows(script)
        material_by_topic: dict[str, list[tuple[int, int, int]]] = {}

        for idx, item in enumerate(visual_items):
            if not isinstance(item, dict) or item.get("type") not in {"image", "video_clip"}:
                continue
            start = int(item.get("start_ms", 0) or 0)
            duration = int(item.get("duration_ms", 0) or 0)
            end = start + duration

            if duration > max_material_duration_ms:
                errors.append(
                    f"tracks.visual[{idx}] 素材时长 {duration}ms 超过单段上限 "
                    f"{max_material_duration_ms}ms"
                )
            if item.get("transition") != "fade":
                errors.append(f'tracks.visual[{idx}] 必须设置 transition="fade"')

            containing_topics = [
                (topic_id, window)
                for topic_id, window in topic_windows.items()
                if start >= window[0] and end <= window[1]
            ]
            if topic_windows and not containing_topics:
                errors.append(
                    f"tracks.visual[{idx}] 必须完整位于某条新闻的 topic_id 时间窗内，"
                    "不能跨新闻或占用 intro/outro"
                )
            elif containing_topics:
                topic_id, (topic_start, topic_end) = containing_topics[0]
                if start - topic_start < studio_return_ms:
                    errors.append(
                        f"tracks.visual[{idx}] 距新闻 {topic_id} 开头不足 "
                        f"{studio_return_ms}ms，开头必须先展示演播室"
                    )
                if topic_end - end < studio_return_ms:
                    errors.append(
                        f"tracks.visual[{idx}] 距新闻 {topic_id} 结尾不足 "
                        f"{studio_return_ms}ms，结尾必须回到演播室"
                    )
                material_by_topic.setdefault(topic_id, []).append((start, end, idx))

            has_remotion = any(
                start < int(remotion.get("start_ms", 0) or 0)
                + int(remotion.get("duration_ms", 0) or 0)
                and end > int(remotion.get("start_ms", 0) or 0)
                for remotion in remotion_items
            )
            if not has_remotion:
                errors.append(
                    f"tracks.visual[{idx}] 播放期间缺少重叠的 visual remotion 信息层"
                )

        for topic_id, intervals in material_by_topic.items():
            sorted_intervals = sorted(intervals)
            for previous, current in zip(sorted_intervals, sorted_intervals[1:]):
                gap = current[0] - previous[1]
                if gap < studio_return_ms:
                    errors.append(
                        f"新闻 {topic_id} 的素材段 visual[{previous[2]}] 与 "
                        f"visual[{current[2]}] 之间只留了 {gap}ms；"
                        f"至少需要 {studio_return_ms}ms 演播室画面"
                    )

            topic_start, topic_end = topic_windows[topic_id]
            topic_duration = max(1, topic_end - topic_start)
            material_duration = self._merged_interval_duration(
                [(start, end) for start, end, _ in sorted_intervals]
            )
            if material_duration / topic_duration > max_material_ratio:
                errors.append(
                    f"新闻 {topic_id} 的素材占比 {material_duration / topic_duration:.0%} "
                    f"超过上限 {max_material_ratio:.0%}，请缩短素材并增加演播室画面"
                )
        return errors

    def _topic_windows(self, script: dict) -> dict[str, tuple[int, int]]:
        windows: dict[str, tuple[int, int]] = {}
        voice_items = script.get("tracks", {}).get("voice", [])
        for item in voice_items:
            if not isinstance(item, dict):
                continue
            topic_id = str(item.get("topic_id") or "").strip()
            if not topic_id or topic_id in {"intro", "outro"}:
                continue
            start = int(item.get("start_ms", 0) or 0)
            end = start + max(0, int(item.get("duration_ms", 0) or 0))
            if topic_id in windows:
                previous_start, previous_end = windows[topic_id]
                windows[topic_id] = (min(previous_start, start), max(previous_end, end))
            else:
                windows[topic_id] = (start, end)
        return windows

    def _merged_interval_duration(self, intervals: list[tuple[int, int]]) -> int:
        total = 0
        current_start = None
        current_end = None
        for start, end in sorted(intervals):
            if current_start is None:
                current_start, current_end = start, end
                continue
            if start <= current_end:
                current_end = max(current_end, end)
                continue
            total += current_end - current_start
            current_start, current_end = start, end
        if current_start is not None:
            total += current_end - current_start
        return total

    def _merge_tracks(self, script: dict, agent_result: dict) -> dict:
        merged = copy.deepcopy(script)
        tracks = merged.setdefault("tracks", {})
        original_voice = copy.deepcopy(tracks.get("voice", []))
        generated = agent_result.get("tracks") if isinstance(agent_result, dict) else {}
        defaults = self._default_tracks(merged)

        tracks["voice"] = original_voice
        for name in ("visual", "overlay", "live2d", "background"):
            value = generated.get(name) if isinstance(generated, dict) else None
            tracks[name] = value if isinstance(value, list) and value else defaults[name]

        for item in tracks["overlay"]:
            if item.get("type") == "remotion" and item.get("component"):
                item["type"] = item.pop("component")

        total_ms = self._voice_total_ms(original_voice) or int(merged.get("total_duration_ms", 0) or 0)
        merged["total_duration_ms"] = total_ms
        meta = merged.setdefault("meta", {})
        meta["post_tts_director"] = self.type
        meta["voice_locked"] = True
        return merged

    def _default_tracks(self, script: dict) -> dict:
        voice = script.get("tracks", {}).get("voice", [])
        total_ms = self._voice_total_ms(voice) or int(script.get("total_duration_ms", 30000) or 30000)
        visual = []
        overlay = []
        live2d = []

        for idx, item in enumerate(voice):
            start = int(item.get("start_ms", 0) or 0)
            duration = max(500, int(item.get("duration_ms", 0) or 0))
            text = item.get("subtitle") or item.get("text") or ""
            visual.append(
                {
                    "start_ms": start,
                    "duration_ms": duration,
                    "type": "remotion",
                    "component": "highlight_text" if idx == 0 else "info_panel",
                    "props": {
                        "text": text[:28],
                        "sub_text": text[28:60],
                        "title": "要点",
                        "points": [text[:40]] if text else [],
                        "color": "#60a5fa",
                        "position": "center",
                    },
                }
            )
            live2d.append(
                {
                    "start_ms": start,
                    "duration_ms": duration,
                    "action": "exp_curious" if idx == 0 else "exp_pleasant",
                }
            )
            if idx % 3 == 1 and text:
                overlay.append(
                    {
                        "start_ms": start,
                        "duration_ms": min(duration, 3500),
                        "type": "highlight_text",
                        "description": "强调口播重点",
                        "props": {"text": text[:24], "color": "#ffdd57", "position": "center"},
                    }
                )

        return {
            "visual": visual,
            "overlay": overlay,
            "live2d": live2d,
            "background": [
                {
                    "start_ms": 0,
                    "duration_ms": total_ms,
                    "type": "gradient",
                    "colors": ["#0f172a", "#111827"],
                }
            ],
        }

    def _voice_total_ms(self, voice: list[dict]) -> int:
        total = 0
        for item in voice:
            total = max(total, int(item.get("start_ms", 0) or 0) + int(item.get("duration_ms", 0) or 0))
        return total
