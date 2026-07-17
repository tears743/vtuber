"""
执行引擎 - 基于 edges 的拓扑排序和同层并发执行。

支持三种工作流模式：
- manual: 用户手动触发，一次性 DAG 执行
- scheduled: 定时触发器驱动
- listener: 长连接监听器驱动

特性：
- edges 决定执行顺序（前端连线 = 后端执行顺序）
- 同层节点通过 asyncio.gather 并行执行
- 完整生命周期调度（prepare -> validate -> check_cache -> execute -> finalize）
- 独立 logger（不污染 root logger）
- WebSocket 实时状态推送
"""
import asyncio
import inspect
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from server.models import PipelineContext
from server.engine.node_cache import NodeCacheManager
from server.nodes.base import BaseNode, TriggerNode, ListenerNode
from server.nodes.registry import create_node

logger = logging.getLogger(__name__)
PROGRESS_HEARTBEAT_SECONDS = 5.0


async def _resolve_maybe_awaitable(value):
    """Await lifecycle hooks only when their implementation is asynchronous."""
    if inspect.isawaitable(value):
        return await value
    return value


# 状态定义

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
    node_states: dict = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    current_nodes: list = field(default_factory=list)  # 当前执行的节点（并发时多个）
    date: str = ""  # 运行日期

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "date": self.date,
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
            "current_nodes": self.current_nodes,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


# 日志 Handler

class WebSocketLogHandler(logging.Handler):
    """拦截日志，通过 asyncio Queue 推送到前端。"""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self._queue = queue
        self._current_nodes: list[str] = []

    def set_current_nodes(self, node_ids: list[str]):
        self._current_nodes = node_ids

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            # 优先使用 record 自带的 node_id（通过 extra={"node_id": ...} 传入）
            node_id = getattr(record, "node_id", None)
            if not node_id:
                # 没有显式 node_id 时，使用 current_nodes 的第一个（不广播）
                node_id = self._current_nodes[0] if self._current_nodes else None
            data = {
                "node_id": node_id,
                "level": record.levelname,
                "message": msg,
                "logger": record.name,
                "timestamp": record.created,
            }
            self._queue.put_nowait(data)
        except Exception:
            pass


# 拓扑排序（基于 edges，返回分层结果）

def topological_sort(
    nodes: list[BaseNode],
    edges: list[dict],
) -> list[list[BaseNode]]:
    """Build DAG layers from explicit workflow edges."""
    node_map = {n.id: n for n in nodes}
    node_ids = set(node_map.keys())

    # 构建邻接表和入度表
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_ids and tgt in node_ids:
            adj[src].append(tgt)
            in_degree[tgt] += 1

    # 使用 Kahn 算法分层
    layers: list[list[BaseNode]] = []
    processed = set()

    while len(processed) < len(node_ids):
        # 找出当前入度为 0 的节点（同层）
        layer_ids = [
            nid for nid in node_ids
            if nid not in processed and in_degree[nid] == 0
        ]

        if not layer_ids:
            # 剩余节点都有入度，说明存在循环依赖
            remaining = [nid for nid in node_ids if nid not in processed]
            raise ValueError(f"存在循环依赖，无法排序的节点: {remaining}")

        # 按 node_id 排序，保证结果确定
        layer_ids.sort()

        # 获取节点实例
        layer_nodes = [node_map[nid] for nid in layer_ids]
        layers.append(layer_nodes)

        # 标记为已处理，并减少下游节点入度
        for nid in layer_ids:
            processed.add(nid)
            for downstream in adj[nid]:
                in_degree[downstream] -= 1

    return layers


# 执行器

class PipelineExecutor:
    """管线执行器，支持 manual / scheduled / listener 三种模式。"""

    def __init__(self):
        self._current_run: Optional[RunState] = None
        self._current_ctx: Optional[PipelineContext] = None
        self._stop_requested: bool = False
        self._event_callback: Optional[Callable] = None
        self._force_no_cache: bool = False
        self._node_cache: Optional[NodeCacheManager] = None
        self._workflow_edges: list[dict] = []
        self._running_tasks: set[asyncio.Task] = set()
        self._run_log_handlers: list[tuple[logging.Logger, logging.Handler]] = []
        # 日志序号（每次运行独立计数）
        self._log_seq: int = 0
        # 初始化 SQLite 存储
        from server.engine.run_store import init_db
        init_db()

    def _cleanup_run_log_handlers(self, ctx: PipelineContext) -> None:
        handlers_to_close: list[logging.Handler] = []

        for logger_obj, handler in list(self._run_log_handlers):
            handlers_to_close.append(handler)
            try:
                logger_obj.removeHandler(handler)
            except Exception:
                pass

        for handler in list(ctx.logger.handlers):
            handlers_to_close.append(handler)
            try:
                ctx.logger.removeHandler(handler)
            except Exception:
                pass

        seen = set()
        for handler in handlers_to_close:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            if hasattr(handler, "close"):
                try:
                    handler.close()
                except Exception:
                    pass

        self._run_log_handlers = []

    @property
    def current_run(self) -> Optional[RunState]:
        return self._current_run

    def get_run_history(self, workflow_id: str) -> list[dict]:
        """获取指定工作流的运行历史（从 SQLite 查询）。"""
        from server.engine.run_store import get_run_history, reconcile_running_runs
        active_run_id = (
            self._current_run.run_id
            if self._current_run
            and self._current_run.workflow_id == workflow_id
            and self._current_run.status == "running"
            else None
        )
        reconcile_running_runs(workflow_id=workflow_id, active_run_id=active_run_id)
        return get_run_history(workflow_id)

    def get_run(self, run_id: str) -> Optional[dict]:
        """获取指定运行的详细状态和日志（从 SQLite 查询）。"""
        from server.engine.run_store import get_run_detail, reconcile_running_runs
        active_run_id = (
            self._current_run.run_id
            if self._current_run
            and self._current_run.status == "running"
            else None
        )
        reconcile_running_runs(active_run_id=active_run_id)
        return get_run_detail(run_id)

    def set_event_callback(self, callback: Callable):
        self._event_callback = callback

    async def _emit(self, event_type: str, data: dict):
        if self._event_callback:
            await self._event_callback(event_type, data)

    def _node_states_payload(self) -> dict:
        if not self._current_run:
            return {}
        return {
            nid: {
                "node_id": ns.node_id,
                "node_type": ns.node_type,
                "status": ns.status.value,
                "progress": ns.progress,
                "message": ns.message,
                "duration_s": ns.duration_s,
                "error": ns.error,
            }
            for nid, ns in self._current_run.node_states.items()
        }

    def stop(self) -> dict:
        """Request the current run to stop."""
        if not self._current_run or self._current_run.status != "running":
            return {
                "stopped": False,
                "reason": "no running workflow",
                "run_id": self._current_run.run_id if self._current_run else None,
                "status": self._current_run.status if self._current_run else "idle",
            }

        self._stop_requested = True
        # 同步到 ctx，让长驻节点（如 cron_trigger）能够检测到停止请求
        if self._current_ctx:
            self._current_ctx._stop_requested = True
        if self._current_run:
            self._current_run.status = "stopped"
            now = time.time()
            self._current_run.end_time = now
            for node_id in list(self._current_run.current_nodes):
                node_state = self._current_run.node_states.get(node_id)
                if node_state and node_state.status == NodeStatus.RUNNING:
                    node_state.status = NodeStatus.SKIPPED
                    node_state.message = "stopped by user"
                    node_state.end_time = now
                    if node_state.start_time:
                        node_state.duration_s = now - node_state.start_time
            self._current_run.current_nodes = []
        for task in list(self._running_tasks):
            task.cancel()
        # 终止所有由节点启动的子进程（如 kukutool 下载进程）
        self._terminate_subprocesses()
        if self._current_run:
            from server.engine.run_store import update_run_status
            update_run_status(
                self._current_run.run_id,
                "stopped",
                end_time=self._current_run.end_time,
                node_states=self._node_states_payload(),
                current_nodes=[],
            )
            return {
                "stopped": True,
                "run_id": self._current_run.run_id,
                "status": "stopped",
            }
        return {"stopped": False, "reason": "no running workflow", "run_id": None, "status": "idle"}

    def _terminate_subprocesses(self):
        """Terminate child processes started by nodes."""
        import subprocess
        import psutil

        try:
            current_pid = __import__("os").getpid()
            parent = psutil.Process(current_pid)
            for child in parent.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    # 主入口

    async def execute_workflow(
        self,
        workflow: dict,
        config: dict,
        date: str,
        data_root: Path,
        force_no_cache: bool = False,
        resume_from_node: str = None,
        dry_run: bool = False,
    ) -> RunState:
        """Execute a workflow."""
        run_id = str(uuid.uuid4())[:8]
        self._stop_requested = False
        self._running_tasks.clear()
        self._force_no_cache = force_no_cache
        self._workflow_edges = workflow.get("edges", [])

        # 确保项目根目录在 sys.path 中（兼容 uvicorn reload 子进程）
        import sys as _sys
        _project_root = str(Path(__file__).parent.parent.parent)
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)

        mode = workflow.get("mode", "manual")

        # 构建 Context
        ctx = PipelineContext(
            date=date,
            data_root=data_root,
            config=config,
            run_id=run_id,
        )
        self._current_ctx = ctx
        self._node_cache = NodeCacheManager(data_root, date, workflow.get("id", "unknown"))

        # 创建节点实例
        nodes = []
        for node_def in workflow.get("nodes", []):
            node = create_node(
                node_type=node_def["type"],
                node_id=node_def["id"],
                config=node_def.get("config", {}),
            )
            nodes.append(node)

        # 将 edge 映射注入节点的 connected inputs
        self._inject_edge_bindings(nodes, workflow.get("edges", []), ctx)

        # 初始化运行状态
        self._current_run = RunState(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            start_time=time.time(),
            date=date,
            node_states={
                n.id: NodeState(node_id=n.id, node_type=n.type)
                for n in nodes
            },
        )

        # 初始化日志缓存
        self._log_seq = 0

        # 将运行记录保存到 SQLite
        from server.engine.run_store import save_run as _save_run
        _save_run(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            date=date,
            start_time=self._current_run.start_time,
            end_time=0,
            current_nodes=[],
            node_states={},
        )

        await self._emit("run_start", {"run_id": run_id, "mode": mode})

        # 设置日志（包含 WebSocket 推送）
        self._log_queue = asyncio.Queue()
        log_queue = self._log_queue
        self._setup_logging(ctx, run_id, date, data_root, log_queue)

        # 后台任务：从 queue 读取日志，推送到前端并写入 SQLite
        from server.engine.run_store import append_log as _append_log

        async def _drain_logs():
            while True:
                data = await log_queue.get()
                if data is None:
                    break
                self._log_seq += 1
                _append_log(run_id, self._log_seq, data)
                if isinstance(data, dict) and data.get("type") == "node_progress":
                    await self._emit("node_progress", {
                        "node_id": data["node_id"],
                        "progress": data["progress"],
                        "message": data["message"],
                    })
                else:
                    await self._emit("log", data)

        drain_task = asyncio.create_task(_drain_logs())

        try:
            if mode == "manual":
                await self._execute_manual(nodes, workflow.get("edges", []), ctx, resume_from_node, dry_run)
            elif mode in ("scheduled", "listener"):
                await self._execute_triggered(nodes, workflow.get("edges", []), ctx, dry_run)
            else:
                raise ValueError(f"Unknown workflow mode: {mode}")

            if not self._stop_requested:
                self._current_run.status = "completed"
            else:
                self._current_run.status = "stopped"
                ctx.logger.info("Run stopped by user")
                await self._emit("run_stopped", {"run_id": run_id})

        except Exception as e:
            self._current_run.status = "failed"
            ctx._abort_requested = True
            ctx._abort_reason = f"workflow failed: {e}"
            ctx.logger.error(f"工作流执行失败: {e}", exc_info=True)
            await self._emit("run_error", {"error": str(e)})

        finally:
            await log_queue.put(None)
            await drain_task

            self._current_run.end_time = time.time()
            self._current_run.current_nodes = []
            total_time = self._current_run.end_time - self._current_run.start_time
            ctx.logger.info(f"工作流结束: {self._current_run.status} | 耗时: {total_time:.1f}s")
            await self._emit("run_end", self._current_run.to_dict())

            # 将最终状态保存到 SQLite
            from server.engine.run_store import save_run as _save_run
            _save_run(
                run_id=run_id,
                workflow_id=self._current_run.workflow_id,
                status=self._current_run.status,
                date=self._current_run.date,
                start_time=self._current_run.start_time,
                end_time=self._current_run.end_time,
                current_nodes=self._current_run.current_nodes,
                node_states={
                    nid: {
                        "node_id": ns.node_id,
                        "node_type": ns.node_type,
                        "status": ns.status.value,
                        "progress": ns.progress,
                        "message": ns.message,
                        "duration_s": ns.duration_s,
                        "error": ns.error,
                    }
                    for nid, ns in self._current_run.node_states.items()
                },
            )

            self._cleanup_run_log_handlers(ctx)

        return self._current_run

    # Manual 模式：一次性 DAG 执行

    async def _execute_manual(
        self,
        nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
        resume_from_node: str = None,
        dry_run: bool = False,
    ):
        """手动模式：拓扑排序并同层并发执行。"""
        # 过滤 Trigger/Listener 节点（manual 模式不执行它们）
        processor_nodes = [
            n for n in nodes
            if not isinstance(n, (TriggerNode, ListenerNode))
        ]

        # 拓扑排序
        layers = topological_sort(processor_nodes, edges)
        ctx.logger.info(f"Topological sort: {len(layers)} layers, {len(processor_nodes)} nodes")

        # 恢复运行：跳过指定节点之前的层
        if resume_from_node:
            self._restore_upstream_caches(processor_nodes, edges, ctx, resume_from_node)
            layers = self._skip_layers_before(layers, resume_from_node)
            ctx.logger.info(f"Resume from node {resume_from_node}, remaining layers={len(layers)}")

        # 逐层执行
        for layer_idx, layer in enumerate(layers):
            if self._stop_requested:
                self._current_run.status = "stopped"
                await self._emit("run_stopped", {"run_id": self._current_run.run_id})
                break

            # 同层并发
            await self._execute_layer(layer, ctx, dry_run)

            # 消费消息总线
            await ctx.drain_messages()

    async def _execute_layer(self, layer: list[BaseNode], ctx: PipelineContext, dry_run: bool = False):
        """Execute one DAG layer."""
        node_ids = [n.id for n in layer]
        self._current_run.current_nodes = node_ids

        ctx.logger.info(f"执行层: {node_ids}")

        if dry_run:
            # dry-run：只执行 validate，不运行节点
            for node in layer:
                node_state = self._current_run.node_states[node.id]
                errors = await node.validate(ctx)
                if errors:
                    node_state.status = NodeStatus.SKIPPED
                    node_state.message = f"校验失败: {'; '.join(errors)}"
                else:
                    node_state.status = NodeStatus.COMPLETED
                    node_state.message = "dry-run: 校验通过"
                    node_state.progress = 1.0
            return

        if self._stop_requested:
            return

        tasks = {
            asyncio.create_task(self._run_node(node, ctx)): node
            for node in layer
        }
        self._running_tasks.update(tasks.keys())
        try:
            pending = set(tasks.keys())
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)
                for task in done:
                    node = tasks[task]
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        node_state = self._current_run.node_states[node.id]
                        reason = getattr(ctx, "_abort_reason", "") or "stopped by user"
                        node_state.status = NodeStatus.SKIPPED
                        node_state.message = reason
                        if not getattr(ctx, "_abort_requested", False):
                            self._current_run.status = "stopped"
                        continue
                    except Exception as result:
                        node_state = self._current_run.node_states[node.id]
                        if node_state.status != NodeStatus.FAILED:
                            node_state.status = NodeStatus.FAILED
                            node_state.error = str(result)
                        if node.on_failure == "abort":
                            self._current_run.status = "failed"
                            ctx._abort_requested = True
                            ctx._abort_reason = f"节点 {node.id} 失败，取消同层未完成节点"
                            if pending:
                                for pending_task in pending:
                                    pending_task.cancel()
                                await asyncio.gather(*pending, return_exceptions=True)
                                pending.clear()
                            raise

                if self._stop_requested and pending:
                    for pending_task in pending:
                        pending_task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    pending.clear()
                    return
        finally:
            for task in tasks.keys():
                self._running_tasks.discard(task)

    # Triggered 模式：由定时器或监听器驱动

    async def _execute_triggered(
        self,
        nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
        dry_run: bool = False,
    ):
        """Start trigger/listener mode."""
        triggers = [
            n for n in nodes
            if isinstance(n, (TriggerNode, ListenerNode))
        ]

        if not triggers:
            raise ValueError("triggered 模式的工作流必须至少包含一个 Trigger/Listener 节点")

        ctx.logger.info(f"Starting {len(triggers)} trigger/listener nodes")

        if dry_run:
            ctx.logger.info("dry-run: skip listener startup")
            return

        # 为每个触发器或监听器启动独立的监听任务
        tasks = [
            asyncio.create_task(self._run_listener(t, nodes, edges, ctx))
            for t in triggers
        ]
        self._running_tasks.update(tasks)

        # 等待所有监听器（通常不会退出，除非用户停止运行）
        try:
            await asyncio.gather(*tasks)
        except Exception:
            self._current_run.status = "failed"
            pending = [task for task in tasks if not task.done()]
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            raise
        finally:
            for task in tasks:
                self._running_tasks.discard(task)

    async def _run_listener(
        self,
        trigger: BaseNode,
        all_nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
    ):
        """运行单个触发器或监听器的长驻循环。"""
        node_state = self._current_run.node_states.get(trigger.id) if self._current_run else None
        listener_started = time.monotonic()
        event_count = 0

        if node_state:
            node_state.status = NodeStatus.RUNNING
            node_state.start_time = time.time()
            node_state.progress = 0.0
            node_state.message = "监听中..."
        await self._emit("node_start", {"node_id": trigger.id, "type": trigger.type})

        async def listener_heartbeat():
            while True:
                await asyncio.sleep(15)
                elapsed_s = int(time.monotonic() - listener_started)
                message = f"监听中 · 已运行 {elapsed_s // 60}分{elapsed_s % 60:02d}秒 · 已接收 {event_count} 个事件"
                if node_state:
                    node_state.message = message
                await self._emit(
                    "node_progress",
                    {"node_id": trigger.id, "progress": 0.0, "message": message},
                )

        heartbeat_task = asyncio.create_task(listener_heartbeat())

        async def emit(event_data: dict):
            """触发下游子图执行。"""
            nonlocal event_count
            event_count += 1
            event_message = f"收到第 {event_count} 个事件，执行下游节点..."
            if node_state:
                node_state.message = event_message
            await self._emit(
                "node_progress",
                {"node_id": trigger.id, "progress": 0.0, "message": event_message},
            )
            # 1. 写入触发器产出
            output_name = trigger.outputs[0].name if trigger.outputs else "trigger"
            ctx.write(trigger.id, output_name, event_data)
            ctx.logger.info(f"emit 触发: {trigger.id} -> {output_name}")

            # 2. 获取下游子图
            downstream_layers = self._get_downstream_subgraph(trigger.id, all_nodes, edges)
            ctx.logger.info(f"下游子图: {len(downstream_layers)} 层, edges={len(edges)}")

            # 3. 执行下游子图
            for i, layer in enumerate(downstream_layers):
                if self._stop_requested:
                    ctx.logger.info(f"emit: stop_requested=True, 跳过层 {i}")
                    break
                ctx.logger.info(f"执行下游层 {i}: {[n.id for n in layer]}")
                await self._execute_layer(layer, ctx)
                await ctx.drain_messages()
            ctx.logger.info(f"emit: 下游执行完成, stop_requested={self._stop_requested}")

            # 4. 双向通道：读取下游 reply 产出并发送回复
            if getattr(trigger, "bidirectional", False):
                # 扫描下游节点 outputs 中类型为 Reply 的产出
                reply = None
                downstream_ids = set()
                queue_ids = [trigger.id]
                while queue_ids:
                    current = queue_ids.pop(0)
                    for edge in edges:
                        if edge.get("source") == current and edge.get("target") not in downstream_ids:
                            downstream_ids.add(edge["target"])
                            queue_ids.append(edge["target"])
                for did in downstream_ids:
                    val = ctx.read(did, "reply")
                    if val is not None:
                        reply = val
                        break
                if reply is None:
                    reply = ctx.find_latest_by_type("Reply")
                if reply and hasattr(trigger, "send_reply"):
                    await trigger.send_reply(ctx, reply)

        # 生命周期
        try:
            ctx.logger.info(f"Starting listener {trigger.id} ({trigger.type})")
            await trigger.prepare(ctx)
            ctx.logger.info(f"Listener {trigger.id} prepare complete, starting listen()")
            await trigger.listen(ctx, emit)
            ctx.logger.info(f"Listener {trigger.id} returned, stop_requested={self._stop_requested}, ctx_stop={getattr(ctx, '_stop_requested', 'N/A')}")
        except asyncio.CancelledError:
            ctx.logger.info(f"Listener {trigger.id} cancelled")
        except Exception as e:
            if self._current_run:
                self._current_run.status = "failed"
            ctx._abort_requested = True
            ctx._abort_reason = f"监听器 {trigger.id} 异常: {e}"
            ctx.logger.error(f"监听器 {trigger.id} 异常: {e}", exc_info=True)
            await self._emit("node_error", {"node_id": trigger.id, "error": str(e)})
            await self._emit("log", {
                "node_id": trigger.id,
                "level": "ERROR",
                "message": f"监听器 {trigger.id} 异常: {e}",
                "logger": "workflow",
                "timestamp": time.time(),
            })
            await self._emit("run_error", {"error": str(e)})
            raise
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await trigger.finalize(ctx, success=False)
            if node_state:
                node_state.end_time = time.time()
                node_state.duration_s = node_state.end_time - node_state.start_time
                node_state.message = "监听已停止"
            ctx.logger.info(f"监听器 {trigger.id} 已停止，进入 finally")

    def _get_downstream_subgraph(
        self,
        trigger_id: str,
        all_nodes: list[BaseNode],
        edges: list[dict],
    ) -> list[list[BaseNode]]:
        """Return downstream processor layers from a trigger node."""
        node_map = {n.id: n for n in all_nodes}

        # 使用 BFS 收集下游节点
        downstream_ids = set()
        queue = [trigger_id]
        while queue:
            current = queue.pop(0)
            for edge in edges:
                if edge.get("source") == current and edge.get("target") not in downstream_ids:
                    downstream_ids.add(edge["target"])
                    queue.append(edge["target"])

        # 过滤出 Processor 节点
        downstream_nodes = [
            node_map[nid] for nid in downstream_ids
            if nid in node_map
            and not isinstance(node_map[nid], (TriggerNode, ListenerNode))
        ]

        # 拓扑排序
        downstream_edges = [
            e for e in edges
            if e.get("source") in downstream_ids and e.get("target") in downstream_ids
        ]
        return topological_sort(downstream_nodes, downstream_edges)

    # 单节点手动触发

    async def run_single_node(
        self,
        workflow: dict,
        config: dict,
        node_id: str,
        date: str,
        data_root: Path,
    ) -> RunState:
        """Run one node manually."""
        import sys as _sys
        _project_root = str(Path(__file__).parent.parent.parent)
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)

        run_id = str(uuid.uuid4())[:8]
        self._stop_requested = False
        self._running_tasks.clear()
        self._log_seq = 0
        self._force_no_cache = False

        # 构建节点实例
        from server.nodes.registry import _registry
        wf_nodes_raw = workflow.get("nodes", [])
        edges = workflow.get("edges", [])
        self._workflow_edges = edges
        self._node_cache = NodeCacheManager(data_root, date, workflow.get("id", "unknown"))
        nodes = []
        for n in wf_nodes_raw:
            cls = _registry.get(n["type"])
            if not cls:
                continue
            node = cls(node_id=n["id"], config=n.get("config", {}))
            nodes.append(node)

        # 构建 Context
        ctx = PipelineContext(
            date=date,
            data_root=data_root,
            config=config,
            run_id=run_id,
        )
        self._current_ctx = ctx

        # 注入 edge bindings
        self._inject_edge_bindings(nodes, edges, ctx)

        # 查找目标节点
        node_map = {n.id: n for n in nodes}
        target_node = node_map.get(node_id)
        if not target_node:
            raise ValueError(f"Node {node_id} not found")

        # 初始化 RunState
        self._current_run = RunState(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            start_time=time.time(),
            date=date,
            node_states={
                n.id: NodeState(node_id=n.id, node_type=n.type)
                for n in nodes
            },
        )

        # 保存到 SQLite
        from server.engine.run_store import save_run as _save_run, append_log as _append_log
        _save_run(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            date=date,
            start_time=self._current_run.start_time,
            end_time=0,
            current_nodes=[],
            node_states={},
        )

        # 设置日志
        self._log_queue = asyncio.Queue()
        log_queue = self._log_queue
        self._setup_logging(ctx, run_id, date, data_root, log_queue)

        await self._emit("run_start", {"run_id": run_id, "mode": "manual_node"})

        # drain task
        async def _drain_logs():
            while True:
                data = await log_queue.get()
                if data is None:
                    break
                self._log_seq += 1
                _append_log(run_id, self._log_seq, data)
                if isinstance(data, dict) and data.get("type") == "node_progress":
                    await self._emit("node_progress", {
                        "node_id": data["node_id"],
                        "progress": data["progress"],
                        "message": data["message"],
                    })
                else:
                    await self._emit("log", data)

        drain_task = asyncio.create_task(_drain_logs())

        try:
            if isinstance(target_node, TriggerNode):
                # Trigger 节点：启动 listen() 定时循环，到期后自动触发下游
                ctx.logger.info(f"启动 Trigger 节点定时循环: {target_node.id}")
                await self._run_listener(target_node, nodes, edges, ctx)
            else:
                # 普通节点：直接执行
                ctx.logger.info(f"手动执行节点: {target_node.id}")
                await self._execute_layer([target_node], ctx)

            if not self._stop_requested:
                self._current_run.status = "completed"
            else:
                self._current_run.status = "stopped"
                ctx.logger.info("执行被用户停止，设置 status=stopped")
                await self._emit("run_stopped", {"run_id": run_id})

        except Exception as e:
            self._current_run.status = "failed"
            ctx.logger.error(f"手动触发失败: {e}", exc_info=True)
            await self._emit("run_error", {"error": str(e)})

        finally:
            ctx.logger.info(f"run_single_node 进入 finally, status={self._current_run.status}")
            await log_queue.put(None)
            await drain_task

            self._current_run.end_time = time.time()
            self._current_run.current_nodes = []
            total_time = self._current_run.end_time - self._current_run.start_time
            ctx.logger.info(f"手动触发结束: {self._current_run.status} | 耗时: {total_time:.1f}s")
            await self._emit("run_end", self._current_run.to_dict())

            # 将最终状态保存到 SQLite
            ctx.logger.info(f"SQLite 保存: run_id={run_id}, status={self._current_run.status}")
            _save_run(
                run_id=run_id,
                workflow_id=self._current_run.workflow_id,
                status=self._current_run.status,
                date=self._current_run.date,
                start_time=self._current_run.start_time,
                end_time=self._current_run.end_time,
                current_nodes=self._current_run.current_nodes,
                node_states={
                    nid: {
                        "node_id": ns.node_id,
                        "node_type": ns.node_type,
                        "status": ns.status.value,
                        "progress": ns.progress,
                        "message": ns.message,
                        "duration_s": ns.duration_s,
                        "error": ns.error,
                    }
                    for nid, ns in self._current_run.node_states.items()
                },
            )
            ctx.logger.info("SQLite 保存完成")

            self._cleanup_run_log_handlers(ctx)

        return self._current_run

    # 单节点执行（完整生命周期）

    async def _run_node(self, node: BaseNode, ctx: PipelineContext) -> None:
        """执行单个节点的完整生命周期。"""
        node_state = self._current_run.node_states[node.id]
        node._ctx = ctx  # 注入 ctx，供 get_input 使用

        success = False

        try:
            if self._stop_requested:
                node_state.status = NodeStatus.SKIPPED
                node_state.message = "stopped by user"
                return

            # prepare
            try:
                await node.prepare(ctx)
            except Exception as e:
                ctx.logger.error(f"[{node.id}] prepare 失败: {e}")
                node_state.status = NodeStatus.SKIPPED
                node_state.message = f"prepare 失败: {e}"
                await self._emit("node_skipped", {"node_id": node.id, "reason": [str(e)]})
                return

            if self._stop_requested:
                node_state.status = NodeStatus.SKIPPED
                node_state.message = "stopped by user"
                await self._emit("node_skipped", {"node_id": node.id, "reason": ["stopped by user"]})
                return

            # validate
            errors = await node.validate(ctx)
            if errors:
                node_state.status = NodeStatus.SKIPPED
                node_state.message = f"跳过: {'; '.join(errors)}"
                ctx.logger.info(f"[{node.id}] 跳过: {'; '.join(errors)}")
                await self._emit("node_skipped", {"node_id": node.id, "reason": errors})
                return

            if self._stop_requested:
                node_state.status = NodeStatus.SKIPPED
                node_state.message = "stopped by user"
                await self._emit("node_skipped", {"node_id": node.id, "reason": ["stopped by user"]})
                return

            node_cache_key = None
            if self._node_cache and not isinstance(node, (TriggerNode, ListenerNode)):
                node_cache_key = self._node_cache.cache_key(node, ctx, self._workflow_edges)
            if node_cache_key and self._node_cache and not self._force_no_cache:
                cache_dir = self._node_cache.cache_dir(node.id, node_cache_key)
                if self._node_cache.restore(node, ctx, cache_dir):
                    node_state.status = NodeStatus.COMPLETED
                    node_state.message = "node output cache hit"
                    node_state.progress = 1.0
                    ctx.logger.info(f"[{node.id}] node output cache hit")
                    await self._emit("node_cached", {"node_id": node.id})
                    success = True
                    return

            # The port-aware output cache is authoritative for workflow runs. Falling
            # back to output-directory checks after a node cache clear would skip the
            # node without restoring its typed outputs into ctx.data.
            if self._node_cache is None and not self._force_no_cache and await node.check_cache(ctx):
                await _resolve_maybe_awaitable(node.restore_cache(ctx))
                node_state.status = NodeStatus.COMPLETED
                node_state.message = "缓存命中"
                node_state.progress = 1.0
                ctx.logger.info(f"[{node.id}] 缓存命中")
                await self._emit("node_cached", {"node_id": node.id})
                success = True
                return

            # execute（包含 retry 逻辑）
            node_state.status = NodeStatus.RUNNING
            node_state.start_time = time.time()
            ctx.logger.info(f"[{node.id}] 开始执行 ({node.type})")
            await self._emit("node_start", {"node_id": node.id, "type": node.type})

            progress_loop = asyncio.get_running_loop()
            progress_state = {"message": "正在执行...", "progress": 0.01}

            def on_progress(message: str, progress: float, _nid=node.id, _ns=node_state):
                try:
                    normalized_progress = min(1.0, max(0.0, float(progress)))
                except Exception:
                    normalized_progress = progress_state["progress"]
                normalized_message = str(message or progress_state["message"] or "正在执行...")

                def _publish_progress():
                    published_progress = max(progress_state["progress"], normalized_progress)
                    progress_state["message"] = normalized_message
                    progress_state["progress"] = published_progress
                    _ns.message = normalized_message
                    _ns.progress = published_progress
                    self._log_queue.put_nowait({
                        "type": "node_progress",
                        "node_id": _nid,
                        "progress": published_progress,
                        "message": normalized_message,
                    })

                try:
                    if asyncio.get_running_loop() is progress_loop:
                        _publish_progress()
                    else:
                        progress_loop.call_soon_threadsafe(_publish_progress)
                except RuntimeError:
                    progress_loop.call_soon_threadsafe(_publish_progress)

            async def _execute_with_heartbeat():
                execute_task = asyncio.create_task(node.execute(ctx, on_progress))
                attempt_started = time.monotonic()
                try:
                    while True:
                        done, _ = await asyncio.wait(
                            {execute_task},
                            timeout=PROGRESS_HEARTBEAT_SECONDS,
                        )
                        if execute_task in done:
                            return await execute_task

                        elapsed_s = int(time.monotonic() - attempt_started)
                        if elapsed_s >= 60:
                            elapsed_text = f"{elapsed_s // 60}分{elapsed_s % 60:02d}秒"
                        else:
                            elapsed_text = f"{elapsed_s}秒"
                        heartbeat_message = f"{progress_state['message']} · 已运行 {elapsed_text}"
                        node_state.message = heartbeat_message
                        node_state.progress = progress_state["progress"]
                        self._log_queue.put_nowait({
                            "type": "node_progress",
                            "node_id": node.id,
                            "progress": progress_state["progress"],
                            "message": heartbeat_message,
                        })
                except BaseException:
                    if not execute_task.done():
                        execute_task.cancel()
                        await asyncio.gather(execute_task, return_exceptions=True)
                    raise

            on_progress("正在执行...", 0.01)

            max_attempts = 1 + (node.max_retries if node.on_failure == "retry" else 0)

            for attempt in range(1, max_attempts + 1):
                try:
                    if self._stop_requested:
                        raise asyncio.CancelledError()
                    outputs = await _execute_with_heartbeat()
                    if self._stop_requested:
                        raise asyncio.CancelledError()

                    # 将节点产出写入 ctx.data
                    if outputs and isinstance(outputs, dict):
                        for output_name, value in outputs.items():
                            ctx.write(node.id, output_name, value)

                    if self._node_cache and not isinstance(node, (TriggerNode, ListenerNode)):
                        if node_cache_key is None:
                            node_cache_key = self._node_cache.cache_key(node, ctx, self._workflow_edges)
                        try:
                            self._node_cache.save(node, ctx, node_cache_key, outputs if isinstance(outputs, dict) else {}, self._workflow_edges)
                        except Exception as e:
                            ctx.logger.warning(f"[{node.id}] node cache save failed: {e}")

                    node_state.status = NodeStatus.COMPLETED
                    node_state.end_time = time.time()
                    node_state.duration_s = node_state.end_time - node_state.start_time
                    node_state.progress = 1.0
                    ctx.logger.info(f"[{node.id}] 完成 ({node_state.duration_s:.1f}s)")
                    await self._emit("node_complete", {
                        "node_id": node.id,
                        "duration_s": node_state.duration_s,
                    })
                    success = True
                    break  # 成功，退出 retry 循环

                except asyncio.CancelledError:
                    cancel_reason = (
                        getattr(ctx, "_abort_reason", "")
                        if getattr(ctx, "_abort_requested", False)
                        else "stopped by user"
                    )
                    node_state.status = NodeStatus.SKIPPED
                    node_state.message = cancel_reason
                    node_state.end_time = time.time()
                    node_state.duration_s = node_state.end_time - node_state.start_time if node_state.start_time else 0
                    ctx.logger.info(f"[{node.id}] {cancel_reason}")
                    await self._emit("node_skipped", {"node_id": node.id, "reason": [cancel_reason]})
                    raise
                except Exception as e:
                    if attempt < max_attempts:
                        ctx.logger.warning(
                            f"[{node.id}] 第 {attempt}/{max_attempts} 次失败: {e}, "
                            f"{node.retry_delay}s 后重试..."
                        )
                        await self._emit("node_progress", {
                            "node_id": node.id,
                            "progress": 0.0,
                            "message": f"重试 {attempt}/{max_attempts}...",
                        })
                        await asyncio.sleep(node.retry_delay)
                        # 重新执行 prepare
                        try:
                            await node.prepare(ctx)
                        except Exception:
                            pass
                    else:
                        # 最后一次尝试仍然失败
                        node_state.status = NodeStatus.FAILED
                        node_state.error = str(e)
                        node_state.end_time = time.time()
                        node_state.duration_s = node_state.end_time - node_state.start_time
                        ctx.logger.error(f"[{node.id}] failed after {max_attempts} attempts: {e}", exc_info=True)
                        await self._emit("node_error", {"node_id": node.id, "error": str(e)})

                        # on_error 钩子
                        try:
                            await node.on_error(ctx, e)
                        except Exception:
                            pass

                        # on_failure=skip 时不中断管线
                        if node.on_failure == "skip":
                            ctx.logger.info(f"[{node.id}] on_failure=skip, 继续执行后续节点")
                            success = False
                        # on_failure=abort 时抛出异常，由 _execute_layer 处理
                        elif node.on_failure == "abort":
                            raise

        finally:
            # 无论成功或失败都调用 finalize
            try:
                await node.finalize(ctx, success)
            except Exception as e:
                ctx.logger.warning(f"[{node.id}] finalize 异常: {e}")

    def _progress_callback(self, node_id: str, progress: float, message: str):
        """Progress callback placeholder."""
        if self._event_callback:
            # 此处不能 await，由 _emit 的调用方负责处理
            pass

    # 辅助方法

    def _inject_edge_bindings(self, nodes: list[BaseNode], edges: list[dict], ctx: PipelineContext = None):
        """Bind edge handles to node input ports."""
        node_map = {n.id: n for n in nodes}

        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            src_handle = edge.get("source_handle") or edge.get("sourceHandle") or "output"
            tgt_handle = edge.get("target_handle") or edge.get("targetHandle") or "input"

            if tgt not in node_map:
                continue

            target_node = node_map[tgt]
            matched = False
            for inp in target_node.inputs:
                if inp.name != tgt_handle:
                    continue
                ref = f"{src}:{src_handle}"
                if inp.multi:
                    existing = inp.connected_from
                    if not existing:
                        inp.connected_from = [ref]
                    elif isinstance(existing, list):
                        existing.append(ref)
                    else:
                        inp.connected_from = [existing, ref]
                else:
                    inp.connected_from = ref
                inp.connected = True
                matched = True
                break

            if not matched and not target_node.inputs and tgt_handle and ctx:
                ctx._edge_aliases[tgt_handle] = (src, src_handle)

    def _restore_upstream_caches(self, nodes: list[BaseNode], edges: list[dict], ctx: PipelineContext, target_id: str):
        """Restore cached outputs for all upstream dependencies of target_id."""
        if not self._node_cache:
            return
        node_map = {node.id: node for node in nodes}
        upstream: set[str] = set()

        def visit(node_id: str):
            for edge in edges:
                if edge.get("target") != node_id:
                    continue
                src = edge.get("source")
                if src and src in node_map and src not in upstream:
                    upstream.add(src)
                    visit(src)

        visit(target_id)
        if not upstream:
            return

        ordered = [
            node
            for layer in topological_sort([node_map[nid] for nid in upstream], edges)
            for node in layer
        ]
        missing = []
        for node in ordered:
            cache_dir = self._node_cache.latest_cache_dir(node)
            if not cache_dir or not self._node_cache.restore(node, ctx, cache_dir):
                missing.append(node.id)
                continue
            node_state = self._current_run.node_states.get(node.id)
            if node_state:
                node_state.status = NodeStatus.COMPLETED
                node_state.message = "restored from cache"
                node_state.progress = 1.0
            ctx.logger.info(f"[{node.id}] restored upstream cache")

        if missing:
            raise RuntimeError("缺少上游节点缓存，无法从指定节点恢复: " + ", ".join(missing))

    def _skip_layers_before(self, layers: list[list[BaseNode]], resume_node_id: str) -> list[list[BaseNode]]:
        """跳过指定节点之前的执行层。"""
        for i, layer in enumerate(layers):
            if any(n.id == resume_node_id for n in layer):
                return layers[i:]
        return layers

    def _setup_logging(self, ctx: PipelineContext, run_id: str, date: str, data_root: Path, log_queue: asyncio.Queue = None):
        """设置独立 logger、日志文件和 WebSocket 推送。"""
        self._cleanup_run_log_handlers(ctx)
        for logger_name in ("agents.collector", "agents.director", "agents.renderer"):
            child_logger = logging.getLogger(logger_name)
            for handler in list(child_logger.handlers):
                if isinstance(handler, (logging.FileHandler, WebSocketLogHandler)):
                    child_logger.removeHandler(handler)

        log_dir = data_root / date / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"run_{run_id}_{datetime.now().strftime('%H%M%S')}.log"

        # 文件 handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        ctx.logger.addHandler(file_handler)
        self._run_log_handlers.append((ctx.logger, file_handler))

        # WebSocket 推送 handler（queue -> drain task -> _emit -> 前端）
        ws_handler = None
        if log_queue:
            ws_handler = WebSocketLogHandler(log_queue)
            ws_handler.setLevel(logging.INFO)
            ws_handler.setFormatter(logging.Formatter("%(message)s"))
            ctx.logger.addHandler(ws_handler)
            self._run_log_handlers.append((ctx.logger, ws_handler))

        ctx.logger.setLevel(logging.DEBUG)
        ctx.logger.propagate = False
        ctx.logger.info(f"日志文件: {log_file}")

        # Route all agents.* logs through the top-level agents logger once.
        # Attaching handlers to both parent and child loggers causes duplicate lines.
        agent_logger = logging.getLogger("agents")
        agent_logger.addHandler(file_handler)
        self._run_log_handlers.append((agent_logger, file_handler))
        if ws_handler:
            agent_logger.addHandler(ws_handler)
            self._run_log_handlers.append((agent_logger, ws_handler))
        agent_logger.setLevel(logging.DEBUG)
        agent_logger.propagate = False


# 全局执行器实例
executor = PipelineExecutor()
