"""
BaseNode — 节点基类

支持三种节点类型：
- Processor: 一次性处理节点（collect/director/tts/compose 等）
- Trigger: 定时触发器节点（CronTrigger 等）
- Listener: 长连接监听器节点（WeChatChannel/FeishuChannel 等）

生命周期：
    prepare(ctx) → validate(ctx) → check_cache(ctx) → execute(ctx, on_progress) → finalize(ctx, success)

向后兼容：
- 旧 reads/writes 声明保留，用于数据契约校验
- 旧 config_schema 格式保留，自动转换为 inputs
- 旧 @register 装饰器继续工作
"""
import hashlib
import json
import logging
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from server.models import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 数据类：节点输入输出声明
# ═══════════════════════════════════════════════════════

@dataclass
class NodeInput:
    """节点输入声明 — 前端据此渲染表单/连线桩"""

    name: str                            # 唯一标识（snake_case）
    type: str                            # 类型：string/int/float/bool/list/dict/model/file/path/自定义类型名
    label: str = ""                      # 前端显示名
    default: Any = None                  # 默认值
    required: bool = True                # 是否必填
    description: str = ""                # 描述文本
    options: list = None                 # 枚举选项
    min: float = None                    # 数值最小值
    max: float = None                    # 数值最大值
    step: float = None                   # 数值步长
    hidden: bool = False                 # 不在UI显示
    group: str = "basic"                 # 参数分组（前端折叠面板）
    connected: bool = False              # True=来自上游连线, False=用户配置参数
    connected_from: str = None           # 运行时由 executor 注入: "node_id:output_name"

    # 向后兼容：旧 config_schema 中的 prompt_file 字段
    prompt_file: str = None
    variables: list = None

    def to_dict(self) -> dict:
        """序列化为前端可用的 dict"""
        d = {
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
        }
        return d


@dataclass
class NodeOutput:
    """节点输出声明 — 前端据此渲染连线桩"""

    name: str                            # 唯一标识
    type: str                            # 类型名（用于连线类型检查）
    label: str = ""                      # 前端显示名
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "description": self.description,
        }


# ═══════════════════════════════════════════════════════
# BaseNode 抽象基类
# ═══════════════════════════════════════════════════════

class BaseNode(ABC):
    """节点基类 — 所有节点的统一接口

    子类必须覆盖：
    - type: 节点类型唯一标识
    - execute(): 核心执行逻辑（Processor 节点）

    可选覆盖：
    - label/category/description/icon/color/version: 元信息
    - inputs/outputs: 输入输出声明
    - prepare/validate/check_cache/restore_cache/on_error/finalize: 生命周期钩子
    - fingerprint: 缓存指纹（cacheable=True 时必须实现）
    - migrate_config: 版本迁移
    """

    # ── 元信息 ──
    type: str = ""
    label: str = ""
    category: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    icon: str = "⚙️"
    color: str = "#78909C"
    deprecated: bool = False
    node_pack: str = "builtin"           # 所属节点包名

    # ── 节点类型 ──
    node_kind: str = "processor"         # "processor" | "trigger" | "listener"

    # ── 输入输出声明 ──
    inputs: list[NodeInput] = []
    outputs: list[NodeOutput] = []

    # ── 向后兼容：旧声明方式 ──
    reads: list[str] = []                # 旧方式：reads=["collected"]
    writes: list[str] = []               # 旧方式：writes=["scripts"]
    config_schema: dict = {}             # 旧方式：前端表单 schema

    # ── 缓存策略 ──
    cacheable: bool = False              # 默认不缓存（LLM 节点不幂等）
    output_dirs: list[str] = []          # 产出目录（向后兼容的缓存检查）

    # ── 失败策略 ──
    on_failure: str = "abort"            # abort | skip | retry
    max_retries: int = 0
    retry_delay: float = 1.0

    # ── 触发器/监听器特有 ──
    is_entry_point: bool = False         # 工作流入口（Trigger/Listener 为 True）

    # ═══════════════════════════════════════════════════════
    # 初始化
    # ═══════════════════════════════════════════════════════

    def __init__(self, node_id: str, config: Optional[dict] = None):
        self.id = node_id
        self.config = config or {}

        # 用 config_schema 的 default 填充未设置的配置（向后兼容）
        for key, schema in self.config_schema.items():
            if key not in self.config and "default" in schema:
                self.config[key] = schema["default"]

        # 用 inputs 的 default 填充未设置的配置（新方式）
        for inp in self.inputs:
            if not inp.connected and inp.name not in self.config:
                if inp.default is not None:
                    self.config[inp.name] = inp.default

        # 运行时状态
        self._ctx: Optional[PipelineContext] = None

    # ═══════════════════════════════════════════════════════
    # 生命周期钩子
    # ═══════════════════════════════════════════════════════

    async def prepare(self, ctx: PipelineContext) -> None:
        """执行前准备资源（连接服务、加载模型、创建临时目录）

        在 execute 之前调用。失败会跳过 execute 但仍调用 finalize。
        """
        pass

    async def validate(self, ctx: PipelineContext) -> list[str]:
        """校验上游数据是否就绪，返回错误列表

        默认检查 inputs 中 connected=True 的输入是否在 ctx.data 中有对应数据。
        旧方式：检查 reads 中的字段是否在 ctx 上非 None。
        """
        errors = []

        # 新方式：检查 connected inputs
        for inp in self.inputs:
            if inp.connected and inp.required:
                if inp.connected_from is None:
                    errors.append(f"输入 '{inp.name}' 未连接上游")
                elif ctx.read_raw(inp.connected_from) is None:
                    errors.append(f"上游数据未就绪: {inp.connected_from}")

        # 旧方式：检查 reads 字段（向后兼容）
        for key in self.reads:
            if getattr(ctx, key, None) is None:
                errors.append(f"缺少上游数据: {key}")

        return errors

    async def check_cache(self, ctx: PipelineContext) -> bool:
        """检查产出缓存是否命中

        默认逻辑：
        - cacheable=False → 不缓存
        - cacheable=True + output_dirs → 检查目录存在且非空（向后兼容）
        - cacheable=True + fingerprint() → 检查指纹缓存文件
        """
        if not self.cacheable:
            return False

        # 旧方式：检查 output_dirs
        if self.output_dirs:
            for dir_name in self.output_dirs:
                output_dir = ctx.data_root / ctx.date / dir_name
                if not output_dir.exists() or not any(output_dir.iterdir()):
                    return False
            return True

        # 新方式：检查指纹缓存
        try:
            fp = self.fingerprint(ctx)
            cache_file = ctx.data_root / ctx.date / ".cache" / f"{self.id}_{fp}.json"
            return cache_file.exists()
        except NotImplementedError:
            return False

    async def restore_cache(self, ctx: PipelineContext) -> None:
        """缓存命中时，从磁盘恢复产出数据到 ctx

        子类应覆盖此方法以正确恢复上下文。
        """
        pass

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        """核心执行逻辑（Processor 节点必须实现）

        Args:
            ctx: 管线上下文
            on_progress: 进度回调 (message, progress_0_to_1)

        Returns:
            outputs dict，如 {"result": value}
            返回值会自动写入 ctx.data["{node_id}:{output_name}"]
        """
        raise NotImplementedError(f"Node {self.type} must implement execute()")

    async def on_error(self, ctx: PipelineContext, error: Exception) -> None:
        """execute 抛异常时的错误处理钩子"""
        pass

    async def finalize(self, ctx: PipelineContext, success: bool) -> None:
        """执行后清理（无论成功失败都调用）

        用于关闭连接、删除临时文件、释放 GPU 内存等。
        """
        pass

    # ═══════════════════════════════════════════════════════
    # 缓存指纹
    # ═══════════════════════════════════════════════════════

    def fingerprint(self, ctx: PipelineContext) -> str:
        """返回基于输入参数的哈希，用于缓存 key

        cacheable=True 时必须实现。
        不假设相同输入必然产生相同输出（LLM 节点不幂等）。
        """
        raise NotImplementedError(f"Node {self.type} is cacheable but doesn't implement fingerprint()")

    def _compute_cache_key(self, ctx: PipelineContext) -> str:
        """计算完整缓存 key = hash(type + version + fingerprint)"""
        fp = self.fingerprint(ctx)
        raw = f"{self.type}:{self.version}:{fp}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ═══════════════════════════════════════════════════════
    # 配置迁移
    # ═══════════════════════════════════════════════════════

    @classmethod
    def migrate_config(cls, old_version: str, config: dict) -> dict:
        """节点版本升级时的配置迁移

        子类覆盖此方法处理 config 格式变化。
        """
        return config

    # ═══════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════

    def get_input(self, name: str) -> Any:
        """读取输入值

        优先从 connected_from（上游连线）读取，
        其次从 config（用户配置参数）读取。
        """
        # 检查是否是 connected input
        for inp in self.inputs:
            if inp.name == name:
                if inp.connected and inp.connected_from:
                    # 从 ctx.data 读取上游产出
                    if self._ctx:
                        return self._ctx.read_raw(inp.connected_from)
                # 非 connected，从 config 读取
                return self.config.get(name, inp.default)

        # 旧方式：直接从 ctx 属性读取（向后兼容）
        if self._ctx:
            val = getattr(self._ctx, name, None)
            if val is not None:
                return val

        # 最终 fallback 到 config
        return self.config.get(name)

    def get_config(self, key: str, fallback: Any = None) -> Any:
        """获取节点配置参数"""
        return self.config.get(key, fallback)

    def render_prompt(self, template: str, variables: dict) -> str:
        """将模板中的 {{变量}} 替换为实际值"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    # ═══════════════════════════════════════════════════════
    # 序列化
    # ═══════════════════════════════════════════════════════

    def to_dict(self) -> dict:
        """序列化为工作流 JSON 可存储的 dict"""
        return {
            "id": self.id,
            "type": self.type,
            "config": self.config,
        }

    @classmethod
    def get_definition(cls) -> dict:
        """返回节点类型定义（供前端节点库使用）

        数据分离：
        - inputs/outputs: 连线桩声明（前端画布渲染连线点）
        - config_schema: 配置参数声明（前端属性面板渲染表单）
        - reads/writes: 向后兼容的数据契约声明
        """
        # 构建输入连线桩列表（只包含 connected=True 的输入）
        inputs_list = [inp.to_dict() for inp in cls.inputs if inp.connected]

        # 向后兼容：从 reads 生成输入连线桩（如果 inputs 为空）
        if not inputs_list and cls.reads:
            inputs_list = [
                {"name": r, "type": "any", "label": r, "connected": True}
                for r in cls.reads
            ]

        # 构建输出连线桩列表
        outputs_list = [out.to_dict() for out in cls.outputs]

        # 向后兼容：从 writes 生成输出连线桩（如果 outputs 为空）
        if not outputs_list and cls.writes:
            outputs_list = [{"name": w, "type": "any", "label": w, "description": ""} for w in cls.writes]

        # 构建 config_schema（配置参数，供前端属性面板渲染表单）
        schema = {}
        for key, field_def in cls.config_schema.items():
            field_copy = dict(field_def)
            # 处理 prompt_file
            if "prompt_file" in field_copy:
                prompt_path = Path(__file__).parent.parent / "prompts" / field_copy["prompt_file"]
                try:
                    field_copy["default"] = prompt_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    logger.warning(f"Prompt file not found: {prompt_path}")
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
            # 连线桩（画布上的连线点）
            "inputs": inputs_list,
            "outputs": outputs_list,
            # 配置参数（属性面板的表单字段）
            "config_schema": schema,
            # 向后兼容
            "reads": cls.reads,
            "writes": cls.writes,
        }


# ═══════════════════════════════════════════════════════
# 触发器/监听器基类
# ═══════════════════════════════════════════════════════

class TriggerNode(BaseNode):
    """触发器节点基类 — 定时触发，非常驻连接

    使用 listen() 而非 execute()。
    到时间后调用 emit(event_data) 触发下游子图。
    """

    node_kind = "trigger"
    cacheable = False
    is_entry_point = True

    async def listen(self, ctx: PipelineContext, emit: Callable) -> None:
        """监听周期性事件，有事件时调用 emit(event_data) 触发下游

        Args:
            ctx: PipelineContext
            emit: 触发回调，调用后执行下游子图
                  emit(event_data: dict) -> awaitable
        """
        raise NotImplementedError(f"TriggerNode {self.type} must implement listen()")

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        raise NotImplementedError("TriggerNode uses listen() instead of execute()")


class ListenerNode(BaseNode):
    """监听器节点基类 — 长连接常驻，事件驱动

    用于接入微信/飞书/钉钉等 IM 平台的 WebSocket/长轮询监听。
    不需要公网回调地址，通过 SDK 的长连接模式接收消息。

    bidirectional=True 时，下游产出回写到 ctx.data["{node_id}:reply"]，
    然后调用 send_reply() 发送回复，继续监听下一条消息。
    """

    node_kind = "listener"
    cacheable = False
    is_entry_point = True

    bidirectional: bool = False         # 是否需要回复（双向通道）

    async def listen(self, ctx: PipelineContext, emit: Callable) -> None:
        """长驻监听，收到事件时调用 emit(event_data) 触发下游

        对于双向通道（bidirectional=True），下游产出到 ctx.data["{node_id}:reply"]
        后，调用 send_reply() 发送回复，然后继续监听下一条消息。
        """
        raise NotImplementedError(f"ListenerNode {self.type} must implement listen()")

    async def send_reply(self, ctx: PipelineContext, reply_data: Any) -> None:
        """发送回复（仅 bidirectional=True 时需要实现）

        Args:
            reply_data: 下游节点产出的回复内容
        """
        pass

    async def execute(self, ctx: PipelineContext, on_progress: Callable[[str, float], None]) -> dict:
        raise NotImplementedError("ListenerNode uses listen() instead of execute()")
