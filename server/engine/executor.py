"""
执行引擎 — 拓扑排序 + 顺序/并行执行

根据节点 reads/writes 自动推导执行顺序，
通过 WebSocket 推送实时状态 + 日志落文件。
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
from pathlib import Path

from server.models import PipelineContext
from server.nodes.base import BaseNode
from server.nodes.registry import create_node

logger = logging.getLogger(__name__)


class WebSocketLogHandler(logging.Handler):
    """拦截 logging 日志，通过 asyncio Queue 推送到前端"""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self._queue = queue
        self._current_node = ""

    def set_current_node(self, node_id: str):
        self._current_node = node_id

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            data = {
                "node_id": self._current_node,
                "level": record.levelname,
                "message": msg,
                "logger": record.name,
                "timestamp": record.created,
            }
            self._queue.put_nowait(data)
        except Exception:
            pass


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeState:
    node_id: str
    node_type: str
    status: NodeStatus = NodeStatus.PENDING
    progress: float = 0.0
    message: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    error: str = ""
    duration_s: float = 0.0


@dataclass
class RunState:
    run_id: str
    workflow_id: str
    status: str = "pending"  # pending | running | completed | failed | stopped
    node_states: dict = field(default_factory=dict)  # node_id -> NodeState
    start_time: float = 0.0
    end_time: float = 0.0
    current_node: str = ""
    logs: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "node_states": {
                nid: {
                    "node_id": ns.node_id,
                    "node_type": ns.node_type,
                    "status": ns.status.value,
                    "progress": ns.progress,
                    "message": ns.message,
                    "duration_s": ns.duration_s,
                    "error": ns.error,
                }
                for nid, ns in self.node_states.items()
            },
            "current_node": self.current_node,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


def topological_sort(nodes: list[BaseNode]) -> list[BaseNode]:
    """根据 reads/writes 推导执行顺序（Kahn's algorithm）"""
    writers: dict[str, list[str]] = defaultdict(list)
    node_map = {n.id: n for n in nodes}

    for node in nodes:
        for key in node.writes:
            writers[key].append(node.id)

    deps: dict[str, set] = {n.id: set() for n in nodes}
    for node in nodes:
        for key in node.reads:
            for writer_id in writers.get(key, []):
                if writer_id != node.id:
                    deps[node.id].add(writer_id)

    in_degree = {nid: len(d) for nid, d in deps.items()}
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    result = []

    while queue:
        queue.sort()
        current = queue.pop(0)
        result.append(node_map[current])

        for nid, d in deps.items():
            if current in d:
                d.remove(current)
                in_degree[nid] -= 1
                if in_degree[nid] == 0:
                    queue.append(nid)

    if len(result) != len(nodes):
        executed = {n.id for n in result}
        remaining = [n.id for n in nodes if n.id not in executed]
        raise ValueError(f"存在循环依赖! 无法排序的节点: {remaining}")

    return result


class PipelineExecutor:
    """管线执行器"""

    def __init__(self):
        self._current_run: Optional[RunState] = None
        self._stop_requested = False
        self._event_callback: Optional[Callable] = None

    @property
    def current_run(self) -> Optional[RunState]:
        return self._current_run

    def set_event_callback(self, callback: Callable):
        """设置事件回调（用于 WebSocket 推送）"""
        self._event_callback = callback

    async def _emit(self, event_type: str, data: dict):
        """发送事件"""
        if self._event_callback:
            await self._event_callback(event_type, data)

    def stop(self):
        """请求停止执行"""
        self._stop_requested = True

    async def execute_workflow(
        self,
        workflow: dict,
        config: dict,
        date: str,
        data_root: Path,
        force_no_cache: bool = False,
    ) -> RunState:
        """执行工作流"""
        import uuid

        run_id = str(uuid.uuid4())[:8]
        self._stop_requested = False
        self._force_no_cache = force_no_cache

        # 构建 Context
        ctx = PipelineContext(
            date=date,
            data_root=data_root,
            config=config,
        )

        # 创建节点实例
        nodes = []
        for node_def in workflow.get("nodes", []):
            node = create_node(
                node_type=node_def["type"],
                node_id=node_def["id"],
                config=node_def.get("config", {}),
            )
            nodes.append(node)

        # 拓扑排序
        sorted_nodes = topological_sort(nodes)

        # 初始化运行状态
        self._current_run = RunState(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            start_time=time.time(),
            node_states={
                n.id: NodeState(node_id=n.id, node_type=n.type)
                for n in sorted_nodes
            },
        )

        await self._emit("run_start", {"run_id": run_id})

        # ── 日志系统 ──
        # 1. 本地日志文件
        log_dir = data_root / date / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"run_{run_id}_{datetime.now().strftime('%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))

        # 2. WebSocket 推送 handler（通过 Queue）
        log_queue = asyncio.Queue()
        ws_handler = WebSocketLogHandler(log_queue)
        ws_handler.setLevel(logging.INFO)
        ws_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
        root_logger.addHandler(ws_handler)

        # 后台 task：从 queue 取日志/进度并推送到前端
        async def _drain_logs():
            while True:
                try:
                    data = await asyncio.wait_for(log_queue.get(), timeout=0.5)
                    if isinstance(data, dict) and data.get("type") == "node_progress":
                        await self._emit("node_progress", {
                            "node_id": data["node_id"],
                            "progress": data["progress"],
                            "message": data["message"],
                        })
                    else:
                        await self._emit("log", data)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    # 推送剩余
                    while not log_queue.empty():
                        data = log_queue.get_nowait()
                        if isinstance(data, dict) and data.get("type") == "node_progress":
                            await self._emit("node_progress", {
                                "node_id": data["node_id"],
                                "progress": data["progress"],
                                "message": data["message"],
                            })
                        else:
                            await self._emit("log", data)
                    break

        drain_task = asyncio.create_task(_drain_logs())

        logger.info(f"=== 工作流启动: {workflow.get('id')} | 日期: {date} | run_id: {run_id} ===")
        logger.info(f"日志文件: {log_file}")

        try:
            # 依次执行
            for node in sorted_nodes:
                if self._stop_requested:
                    self._current_run.status = "stopped"
                    await self._emit("run_stopped", {"run_id": run_id})
                    logger.info("用户请求停止，终止执行")
                    break

                node_state = self._current_run.node_states[node.id]
                self._current_run.current_node = node.id
                ws_handler.set_current_node(node.id)

                # 校验
                errors = node.validate(ctx)
                if errors:
                    node_state.status = NodeStatus.SKIPPED
                    node_state.message = f"跳过: {'; '.join(errors)}"
                    logger.info(f"[{node.id}] 跳过: {'; '.join(errors)}")
                    await self._emit("node_skipped", {
                        "node_id": node.id, "reason": errors
                    })
                    continue

                # 缓存检查：如果产出已存在则跳过
                if not self._force_no_cache and node.check_cache(ctx):
                    node.restore_cache(ctx)  # 从磁盘恢复 ctx 数据
                    node_state.status = NodeStatus.COMPLETED
                    node_state.message = "缓存命中，跳过"
                    node_state.progress = 1.0
                    logger.info(f"[{node.id}] ⚡ 缓存命中，跳过执行")
                    await self._emit("node_cached", {
                        "node_id": node.id, "message": "缓存命中"
                    })
                    continue

                # 执行
                node_state.status = NodeStatus.RUNNING
                node_state.start_time = time.time()
                logger.info(f"[{node.id}] ▶ 开始执行 ({node.type})")
                await self._emit("node_start", {"node_id": node.id, "type": node.type})

                def on_progress(message: str, progress: float, _nid=node.id, _ns=node_state):
                    _ns.message = message
                    _ns.progress = progress
                    log_queue.put_nowait({
                        "type": "node_progress",
                        "node_id": _nid, "progress": progress, "message": message
                    })

                try:
                    await node.execute(ctx, on_progress)
                    node_state.status = NodeStatus.COMPLETED
                    node_state.end_time = time.time()
                    node_state.duration_s = node_state.end_time - node_state.start_time
                    node_state.progress = 1.0
                    logger.info(f"[{node.id}] ✓ 完成 ({node_state.duration_s:.1f}s)")
                    await self._emit("node_complete", {
                        "node_id": node.id, "duration_s": node_state.duration_s
                    })
                except Exception as e:
                    node_state.status = NodeStatus.FAILED
                    node_state.error = str(e)
                    node_state.end_time = time.time()
                    node_state.duration_s = node_state.end_time - node_state.start_time
                    logger.error(f"[{node.id}] ✗ 失败: {e}", exc_info=True)
                    await self._emit("node_error", {
                        "node_id": node.id, "error": str(e)
                    })
                    self._current_run.status = "failed"
                    break
            else:
                self._current_run.status = "completed"

            self._current_run.end_time = time.time()
            self._current_run.current_node = ""
            total_time = self._current_run.end_time - self._current_run.start_time
            logger.info(f"=== 工作流结束: {self._current_run.status} | 总耗时: {total_time:.1f}s ===")
            await self._emit("run_end", self._current_run.to_dict())

        finally:
            # 停止 drain task 并刷新剩余日志
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError:
                pass
            # 卸载 handlers
            root_logger.removeHandler(file_handler)
            root_logger.removeHandler(ws_handler)
            file_handler.close()

        return self._current_run


# 全局执行器实例
executor = PipelineExecutor()
