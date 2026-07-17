"""
Base node interfaces for VideoFactory.

The runtime now treats declared NodeInput/NodeOutput entries as graph ports.
Legacy reads/writes are still exposed as compatibility ports for old nodes.
"""

import copy
import hashlib
import logging
from abc import ABC
from dataclasses import MISSING, dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Callable, Optional, get_args, get_origin

from server.models import PipelineContext

logger = logging.getLogger(__name__)


BUILTIN_DATA_FORMATS = {
    "*": {
        "type": "*",
        "label": "Any",
        "description": "任意上游值。具体结构要看连接的输出端口。",
        "fields": [],
    },
    "JSON": {
        "type": "JSON",
        "label": "JSON 对象",
        "description": "普通 JSON 兼容值，可以是 object/list/string/number/bool。",
        "fields": [],
    },
    "Trigger": {
        "type": "Trigger",
        "label": "触发事件",
        "description": "Trigger/Listener 节点发出的事件信号。",
        "fields": [
            {"name": "triggered_at", "type": "ISO datetime string", "required": False, "description": "触发时间。"},
            {"name": "payload", "type": "object", "required": False, "description": "可选事件载荷。"},
        ],
    },
    "Message": {
        "type": "Message",
        "label": "收到的消息",
        "description": "Listener/Channel 节点收到的平台消息。",
        "fields": [
            {"name": "text", "type": "string", "required": False, "description": "消息文本。"},
            {"name": "sender", "type": "string/object", "required": False, "description": "发送者信息。"},
            {"name": "raw", "type": "object", "required": False, "description": "原始平台载荷。"},
        ],
    },
    "Reply": {
        "type": "Reply",
        "label": "回复内容",
        "description": "Listener/Channel 节点可发送的回复载荷。",
        "fields": [
            {"name": "text", "type": "string", "required": False, "description": "回复文本。"},
            {"name": "attachments", "type": "list", "required": False, "description": "可选附件。"},
        ],
    },
}


PIPELINE_DATA_FORMAT_HINTS = {
    "CollectedData": {
        "description": "采集节点输出的原始素材索引，通常包含微博/抖音/GitHub/HuggingFace 等来源的 JSON 文件。",
        "fields": {
            "dir": "采集结果目录。",
            "files": "采集到的 JSON 文件路径列表。",
            "count": "采集条目数量。",
            "platforms": "按平台统计或分组的数据对象。",
        },
    },
    "MediaData": {
        "description": "下载后的本地媒体素材清单，包含图片、视频、README 等本地文件索引。",
        "fields": {
            "dir": "媒体下载目录。",
            "manifest_path": "manifest.json 文件路径。",
            "manifest": "媒体清单对象，记录每条素材及其本地文件。",
            "total_items": "素材条目总数。",
            "total_images": "图片数量。",
            "total_videos": "视频数量。",
            "total_readmes": "README/文本素材数量。",
        },
    },
    "SelectedData": {
        "description": "选题/筛选后的候选内容，用于后续生成脚本或编排。",
        "fields": {
            "dir": "选题输出目录。",
            "file": "选题结果文件路径。",
            "hot_topics": "热搜/热点候选列表。",
            "ai_topics": "AI 科技候选列表。",
        },
    },
    "ScriptsData": {
        "description": "口播/分镜脚本数据，后续 TTS、对齐、合成节点会读取它。",
        "fields": {
            "dir": "脚本输出目录。",
            "files": "脚本文件路径列表。",
            "scripts": "脚本内容字典，通常按视频/片段编号组织文本和角色信息。",
            "total_duration_ms": "每段脚本的目标总时长，单位毫秒；可为空，由后续音频补齐。",
        },
    },
    "AudioData": {
        "description": "TTS 生成后的音频结果和时长信息。",
        "fields": {
            "dir": "音频输出目录。",
            "durations_path": "durations.json 文件路径。",
            "durations": "每段音频的时长表，通常以脚本/片段 ID 为 key。",
            "segments": "音频分段信息，包含生成文件路径、角色、文本等节点产出的元数据。",
        },
    },
    "AlignedData": {
        "description": "脚本与音频对齐后的时间轴数据。",
        "fields": {
            "dir": "对齐输出目录。",
            "files": "对齐结果文件路径列表。",
            "scripts": "带时间戳的脚本/字幕/片段结构。",
        },
    },
    "OverlayData": {
        "description": "字幕、贴纸、覆盖层等渲染产物。",
        "fields": {
            "dir": "覆盖层输出目录。",
            "files": "按视频/片段组织的产物文件字典。",
            "success_count": "成功处理数量。",
            "failed_count": "失败数量。",
        },
    },
    "VisualData": {
        "description": "视觉素材或画面生成结果。",
        "fields": {
            "dir": "视觉输出目录。",
            "files": "生成图片/视频/中间文件字典。",
            "success_count": "成功处理数量。",
        },
    },
    "SubtitleData": {
        "description": "根据真实语音时间轴生成的独立字幕轨文件。",
        "fields": {
            "dir": "字幕输出目录。",
            "files": "按脚本 ID 组织的 ASS 字幕文件。",
            "success_count": "成功生成的字幕文件数量。",
        },
    },
    "Live2DData": {
        "description": "Live2D 驱动或人物视频相关产物。",
        "fields": {
            "dir": "Live2D 输出目录。",
            "files": "生成文件字典。",
            "success_count": "成功处理数量。",
        },
    },
    "FinalData": {
        "description": "最终合成视频结果。",
        "fields": {
            "dir": "最终输出目录。",
            "files": "最终视频和关联文件字典。",
            "success_count": "成功合成数量。",
            "total_duration_s": "最终视频时长，单位秒。",
        },
    },
}


def _annotation_to_name(annotation: Any) -> str:
    if annotation is Any:
        return "Any"
    if annotation is None:
        return "None"
    origin = get_origin(annotation)
    if origin:
        args = get_args(annotation)
        origin_name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
        if args:
            return f"{origin_name}[{', '.join(_annotation_to_name(arg) for arg in args)}]"
        return origin_name
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def get_data_format_schema(type_name: str) -> dict:
    """Return a UI-friendly schema for known port data types."""
    normalized = type_name or "*"
    if normalized in BUILTIN_DATA_FORMATS:
        return copy.deepcopy(BUILTIN_DATA_FORMATS[normalized])

    try:
        import server.models as pipeline_models
    except Exception:
        pipeline_models = None

    model_cls = getattr(pipeline_models, normalized, None) if pipeline_models else None
    if model_cls and is_dataclass(model_cls):
        hints = PIPELINE_DATA_FORMAT_HINTS.get(normalized, {})
        field_hints = hints.get("fields", {})
        field_defs = []
        for item in fields(model_cls):
            field_defs.append({
                "name": item.name,
                "type": _annotation_to_name(item.type),
                "required": item.default is MISSING and item.default_factory is MISSING,
                "description": field_hints.get(item.name, ""),
            })
        return {
            "type": normalized,
            "label": normalized,
            "description": hints.get("description", f"{normalized} 节点间传递的数据对象。"),
            "fields": field_defs,
        }

    return {
        "type": normalized,
        "label": normalized,
        "description": "自定义数据类型。精确结构由产生该输出的节点在端口说明中描述。",
        "fields": [],
    }


def get_data_format_text(type_name: str) -> str:
    schema = get_data_format_schema(type_name)
    lines = [schema["type"]]
    if schema.get("description"):
        lines.append(schema["description"])
    for field in schema.get("fields", []):
        required = "required" if field.get("required") else "optional"
        lines.append(f"- {field['name']}: {field.get('type', 'Any')} ({required})")
    return "\n".join(lines)


@dataclass
class NodeInput:
    """Input port or legacy form field metadata."""

    name: str
    type: str
    label: str = ""
    default: Any = None
    required: bool = True
    description: str = ""
    options: list | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    hidden: bool = False
    group: str = "basic"
    connected: bool = False
    connected_from: str | None = None
    multi: bool = False
    prompt_file: str | None = None
    variables: list | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "default": self.default,
            "required": self.required,
            "description": self.description,
            "options": self.options,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "hidden": self.hidden,
            "group": self.group,
            "connected": self.connected,
            "multi": self.multi,
            "format_schema": get_data_format_schema(self.type),
            "format_text": get_data_format_text(self.type),
        }


@dataclass
class NodeOutput:
    """Output port metadata."""

    name: str
    type: str
    label: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "description": self.description,
            "format_schema": get_data_format_schema(self.type),
            "format_text": get_data_format_text(self.type),
        }


class BaseNode(ABC):
    """Base class for processor nodes."""

    type: str = ""
    label: str = ""
    category: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    icon: str = ""
    color: str = "#78909C"
    deprecated: bool = False
    node_pack: str = "builtin"

    node_kind: str = "processor"

    inputs: list[NodeInput] = []
    outputs: list[NodeOutput] = []

    reads: list[str] = []
    writes: list[str] = []
    config_schema: dict = {}

    cacheable: bool = False
    output_dirs: list[str] = []

    on_failure: str = "abort"
    max_retries: int = 0
    retry_delay: float = 1.0

    is_entry_point: bool = False

    def __init__(self, node_id: str, config: Optional[dict] = None):
        self.id = node_id
        self.config = config or {}
        self.inputs = copy.deepcopy(self.__class__.inputs)
        self.outputs = copy.deepcopy(self.__class__.outputs)

        for key, schema in self.config_schema.items():
            if key not in self.config and "default" in schema:
                self.config[key] = schema["default"]

        for inp in self.inputs:
            if inp.name not in self.config and inp.default is not None:
                self.config[inp.name] = inp.default

        self._ctx: Optional[PipelineContext] = None

    async def prepare(self, ctx: PipelineContext) -> None:
        pass

    async def validate(self, ctx: PipelineContext) -> list[str]:
        errors: list[str] = []

        for inp in self.inputs:
            if not inp.required:
                continue
            if inp.connected_from:
                refs = inp.connected_from if isinstance(inp.connected_from, list) else [inp.connected_from]
                missing = [ref for ref in refs if ctx.read_raw(ref) is None]
                if missing:
                    errors.append(f"Missing upstream data for input '{inp.name}': {', '.join(missing)}")
                continue
            if inp.name in self.config and self.config.get(inp.name) not in (None, ""):
                continue
            errors.append(f"Input '{inp.name}' is not connected or configured")

        for key in self.reads:
            if getattr(ctx, key, None) is None:
                errors.append(f"Missing upstream data: {key}")

        return errors

    async def check_cache(self, ctx: PipelineContext) -> bool:
        if not self.cacheable:
            return False

        if self.output_dirs:
            for dir_name in self.output_dirs:
                output_dir = ctx.data_root / ctx.date / dir_name
                if not output_dir.exists() or not any(output_dir.iterdir()):
                    return False
            return True

        try:
            fp = self.fingerprint(ctx)
            cache_file = ctx.data_root / ctx.date / ".cache" / f"{self.id}_{fp}.json"
            return cache_file.exists()
        except NotImplementedError:
            return False

    async def restore_cache(self, ctx: PipelineContext) -> None:
        pass

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        raise NotImplementedError(f"Node {self.type} must implement execute()")

    async def on_error(self, ctx: PipelineContext, error: Exception) -> None:
        pass

    async def finalize(self, ctx: PipelineContext, success: bool) -> None:
        pass

    def fingerprint(self, ctx: PipelineContext) -> str:
        raise NotImplementedError(f"Node {self.type} is cacheable but does not implement fingerprint()")

    def _compute_cache_key(self, ctx: PipelineContext) -> str:
        fp = self.fingerprint(ctx)
        raw = f"{self.type}:{self.version}:{fp}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def migrate_config(cls, old_version: str, config: dict) -> dict:
        return config

    def get_input(self, name: str) -> Any:
        for inp in self.inputs:
            if inp.name != name:
                continue
            if inp.connected_from and self._ctx:
                if isinstance(inp.connected_from, list):
                    values = [self._ctx.read_raw(ref) for ref in inp.connected_from]
                    return [value for value in values if value is not None]
                return self._ctx.read_raw(inp.connected_from)
            return self.config.get(name, inp.default)

        if self._ctx:
            val = getattr(self._ctx, name, None)
            if val is not None:
                return val
        return self.config.get(name)

    def get_inputs(self, name: str) -> list[Any]:
        value = self.get_input(name)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def get_config(self, key: str, fallback: Any = None) -> Any:
        return self.config.get(key, fallback)

    def render_prompt(self, template: str, variables: dict) -> str:
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "config": self.config,
        }

    @classmethod
    def get_definition(cls) -> dict:
        inputs_list = [inp.to_dict() for inp in cls.inputs]
        if not inputs_list and cls.reads:
            inputs_list = [
                {
                    "name": r,
                    "type": "*",
                    "label": r,
                    "connected": True,
                    "required": True,
                    "multi": False,
                    "format_schema": get_data_format_schema("*"),
                    "format_text": get_data_format_text("*"),
                }
                for r in cls.reads
            ]

        outputs_list = [out.to_dict() for out in cls.outputs]
        if not outputs_list and cls.writes:
            outputs_list = [
                {
                    "name": w,
                    "type": "*",
                    "label": w,
                    "description": "",
                    "format_schema": get_data_format_schema("*"),
                    "format_text": get_data_format_text("*"),
                }
                for w in cls.writes
            ]

        schema = {}
        for key, field_def in cls.config_schema.items():
            field_copy = dict(field_def)
            if "prompt_file" in field_copy:
                prompt_path = Path(__file__).parent.parent / "prompts" / field_copy["prompt_file"]
                try:
                    field_copy["default"] = prompt_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    logger.warning("Prompt file not found: %s", prompt_path)
                del field_copy["prompt_file"]
            schema[key] = field_copy

        return {
            "type": cls.type,
            "label": cls.label,
            "category": cls.category,
            "description": cls.description,
            "version": cls.version,
            "author": cls.author,
            "icon": cls.icon,
            "color": cls.color,
            "deprecated": cls.deprecated,
            "node_pack": cls.node_pack,
            "node_kind": cls.node_kind,
            "inputs": inputs_list,
            "outputs": outputs_list,
            "config_schema": schema,
            "reads": cls.reads,
            "writes": cls.writes,
        }


class TriggerNode(BaseNode):
    node_kind = "trigger"
    cacheable = False
    is_entry_point = True

    async def listen(self, ctx: PipelineContext, emit: Callable) -> None:
        raise NotImplementedError(f"TriggerNode {self.type} must implement listen()")

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        raise NotImplementedError("TriggerNode uses listen() instead of execute()")


class ListenerNode(BaseNode):
    node_kind = "listener"
    cacheable = False
    is_entry_point = True

    bidirectional: bool = False

    async def listen(self, ctx: PipelineContext, emit: Callable) -> None:
        raise NotImplementedError(f"ListenerNode {self.type} must implement listen()")

    async def send_reply(self, ctx: PipelineContext, reply_data: Any) -> None:
        pass

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        raise NotImplementedError("ListenerNode uses listen() instead of execute()")
