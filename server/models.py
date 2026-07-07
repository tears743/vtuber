"""
Pipeline Context — 管线上下文

新设计：产出仓库模式
- ctx.data: dict[str, Any] — 按 "node_id:output_name" 索引
- ctx.read(node_id, output_name) / ctx.write(node_id, output_name, value)
- ctx.find_by_type(type_name) — 按类型查找上游产出

向后兼容：
- 保留 ctx.collected / ctx.media / ctx.scripts 等属性
- 通过 property 从 ctx.data 中动态读取
- 旧节点直接读 ctx.collected 仍然工作

消息总线：
- ctx.emit(event, data) / ctx.on(event, handler)
- 同步发布，异步消费（通过 asyncio.Queue）
- 事件不持久化，仅运行时有效
"""
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# ═══════════════════════════════════════════════════════
# 阶段产出 DataClass（向后兼容，保留原有定义）
# ═══════════════════════════════════════════════════════

@dataclass
class CollectedData:
    """采集阶段产出"""
    dir: Path
    files: list = field(default_factory=list)
    count: int = 0
    platforms: dict = field(default_factory=dict)


@dataclass
class MediaData:
    """素材下载+识别阶段产出"""
    dir: Path
    manifest_path: Path = None
    manifest: dict = field(default_factory=dict)
    total_items: int = 0
    total_images: int = 0
    total_videos: int = 0
    total_readmes: int = 0


@dataclass
class SelectedData:
    """Director 选题阶段产出"""
    dir: Path
    file: Path = None
    hot_topics: list = field(default_factory=list)
    ai_topics: list = field(default_factory=list)


@dataclass
class ScriptsData:
    """脚本生成阶段产出"""
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)
    total_duration_ms: dict = field(default_factory=dict)


@dataclass
class AudioData:
    """TTS 阶段产出"""
    dir: Path
    durations_path: Path = None
    durations: dict = field(default_factory=dict)
    segments: dict = field(default_factory=dict)


@dataclass
class AlignedData:
    """时间轴对齐阶段产出"""
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)


@dataclass
class OverlayData:
    """Overlay 卡片渲染产出"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0
    failed_count: int = 0


@dataclass
class VisualData:
    """背景视觉层产出"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class Live2DData:
    """Live2D 渲染产出"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class FinalData:
    """最终合成产出"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0
    total_duration_s: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════
# 消息总线
# ═══════════════════════════════════════════════════════

class MessageBus:
    """节点间消息总线 — 发布/订阅模式

    特性：
    - 同步发布，异步消费
    - 事件不持久化，仅运行时有效
    - 不影响拓扑排序（纯通信，不产生数据依赖）
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()

    def on(self, event: str, handler: Callable):
        """订阅事件"""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, data: dict):
        """发布事件（非阻塞，放入队列）"""
        self._queue.put_nowait({"event": event, "data": data})

    async def drain(self):
        """消费队列中的事件（由 executor 调用）"""
        while not self._queue.empty():
            item = self._queue.get_nowait()
            event = item["event"]
            data = item["data"]
            for handler in self._handlers.get(event, []):
                try:
                    result = handler(data)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logging.getLogger("workflow.messagebus").error(
                        f"消息处理器异常 ({event}): {e}"
                    )


# ═══════════════════════════════════════════════════════
# PipelineContext
# ═══════════════════════════════════════════════════════

class PipelineContext:
    """全管线共享的数据上下文

    新设计：产出仓库模式
    - data: dict[str, Any] — 按 "node_id:output_name" 索引
    - read/write 方法操作 data 字典
    - 旧属性（collected/media/scripts 等）通过 property 动态代理

    向后兼容：
    - ctx.collected 仍然可用，自动从 data 中查找类型匹配的产出
    - 旧节点直接读写 ctx.collected 不受影响
    """

    def __init__(
        self,
        date: str = "",
        data_root: Path = None,
        config: dict = None,
        run_id: str = "",
    ):
        self.date = date
        self.data_root = data_root or Path("data")
        self.config = config or {}
        self.run_id = run_id

        # 产出仓库
        self.data: dict[str, Any] = {}

        # 消息总线
        self.message_bus = MessageBus()

        # 独立 logger（不污染 root logger）
        self.logger = logging.getLogger(f"workflow.{run_id}") if run_id else logging.getLogger("workflow")

        # 缓存：旧属性的直接引用（向后兼容优化）
        self._legacy_fields: dict[str, Any] = {}

    # ── 数据读写 ──

    def write(self, node_id: str, output_name: str, value: Any) -> None:
        """写入节点产出"""
        key = f"{node_id}:{output_name}"
        self.data[key] = value
        self.logger.debug(f"ctx.write: {key} = {type(value).__name__}")

    def read(self, node_id: str, output_name: str) -> Any:
        """读取上游节点产出"""
        key = f"{node_id}:{output_name}"
        return self.data.get(key)

    def read_raw(self, key: str) -> Any:
        """通过完整 key 读取（内部用，如 "collect_1:collected"）"""
        return self.data.get(key)

    def find_by_type(self, type_name: str) -> list[Any]:
        """按类型查找所有匹配的产出

        用于多对一场景：节点不关心具体来源，只要类型匹配。
        """
        results = []
        for key, value in self.data.items():
            if type(value).__name__ == type_name:
                results.append(value)
        return results

    def find_latest_by_type(self, type_name: str) -> Any:
        """按类型查找最新的产出（最后写入的）"""
        results = self.find_by_type(type_name)
        return results[-1] if results else None

    # ── 消息总线 ──

    def emit(self, event: str, data: dict) -> None:
        """发布消息总线事件"""
        self.message_bus.emit(event, data)

    def on(self, event: str, handler: Callable) -> None:
        """订阅消息总线事件"""
        self.message_bus.on(event, handler)

    async def drain_messages(self) -> None:
        """消费消息总线队列（由 executor 调用）"""
        await self.message_bus.drain()

    # ── 向后兼容：旧属性代理 ──
    # ctx.collected / ctx.media / ctx.scripts 等
    # 自动从 _legacy_fields 或 data 中查找

    def _get_legacy(self, name: str) -> Any:
        """获取旧属性值"""
        # 优先从 _legacy_fields 取（旧节点直接赋值 ctx.collected = ...）
        if name in self._legacy_fields:
            return self._legacy_fields[name]
        # 尝试从 data 中按类型查找
        type_map = {
            "collected": "CollectedData",
            "media": "MediaData",
            "selected": "SelectedData",
            "scripts": "ScriptsData",
            "audio": "AudioData",
            "aligned": "AlignedData",
            "overlay": "OverlayData",
            "visual": "VisualData",
            "live2d": "Live2DData",
            "final": "FinalData",
        }
        if name in type_map:
            return self.find_latest_by_type(type_map[name])
        return None

    def _set_legacy(self, name: str, value: Any) -> None:
        """设置旧属性值"""
        self._legacy_fields[name] = value
        # 同时写入 data 仓库（用 name 作为 key，方便旧节点读取）
        self.data[f"_legacy:{name}"] = value

    # ── 旧属性 property（向后兼容）──

    @property
    def collected(self) -> Optional[CollectedData]:
        return self._get_legacy("collected")

    @collected.setter
    def collected(self, value):
        self._set_legacy("collected", value)

    @property
    def media(self) -> Optional[MediaData]:
        return self._get_legacy("media")

    @media.setter
    def media(self, value):
        self._set_legacy("media", value)

    @property
    def recognized(self) -> Optional[bool]:
        return self._legacy_fields.get("recognized")

    @recognized.setter
    def recognized(self, value):
        self._legacy_fields["recognized"] = value

    @property
    def transcribed(self) -> Optional[bool]:
        return self._legacy_fields.get("transcribed")

    @transcribed.setter
    def transcribed(self, value):
        self._legacy_fields["transcribed"] = value

    @property
    def selected(self) -> Optional[SelectedData]:
        return self._get_legacy("selected")

    @selected.setter
    def selected(self, value):
        self._set_legacy("selected", value)

    @property
    def scripts(self) -> Optional[ScriptsData]:
        return self._get_legacy("scripts")

    @scripts.setter
    def scripts(self, value):
        self._set_legacy("scripts", value)

    @property
    def audio(self) -> Optional[AudioData]:
        return self._get_legacy("audio")

    @audio.setter
    def audio(self, value):
        self._set_legacy("audio", value)

    @property
    def aligned(self) -> Optional[AlignedData]:
        return self._get_legacy("aligned")

    @aligned.setter
    def aligned(self, value):
        self._set_legacy("aligned", value)

    @property
    def overlay(self) -> Optional[OverlayData]:
        return self._get_legacy("overlay")

    @overlay.setter
    def overlay(self, value):
        self._set_legacy("overlay", value)

    @property
    def visual(self) -> Optional[VisualData]:
        return self._get_legacy("visual")

    @visual.setter
    def visual(self, value):
        self._set_legacy("visual", value)

    @property
    def live2d(self) -> Optional[Live2DData]:
        return self._get_legacy("live2d")

    @live2d.setter
    def live2d(self, value):
        self._set_legacy("live2d", value)

    @property
    def final(self) -> Optional[FinalData]:
        return self._get_legacy("final")

    @final.setter
    def final(self, value):
        self._set_legacy("final", value)
