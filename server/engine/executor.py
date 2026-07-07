"""
执行引擎 — 基于 edges 的拓扑排序 + 同层并发执行

支持三种工作流模式：
- manual: 用户手动触发，一次性 DAG 执行
- scheduled: 定时触发器驱动
- listener: 长连接监听器驱动

特性：
- edges 决定执行顺序（前端连线 = 后端执行序）
- 同层节点 asyncio.gather 并行
- 完整生命周期调度（prepare → validate → check_cache → execute → finalize）
- 独立 logger（不污染 root logger）
- WebSocket 实时状态推送
"""
import asyncio
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
from server.nodes.base import BaseNode, TriggerNode, ListenerNode
from server.nodes.registry import create_node

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 状态定义
# ═══════════════════════════════════════════════════════

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
            "current_nodes": self.current_nodes,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


# ═══════════════════════════════════════════════════════
# 日志 Handler
# ═══════════════════════════════════════════════════════

class WebSocketLogHandler(logging.Handler):
    """拦截日志，通过 asyncio Queue 推送到前端"""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self._queue = queue
        self._current_nodes: list[str] = []

    def set_current_nodes(self, node_ids: list[str]):
        self._current_nodes = node_ids

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            for node_id in self._current_nodes:
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


# ═══════════════════════════════════════════════════════
# 拓扑排序（基于 edges，返回分层结果）
# ═══════════════════════════════════════════════════════

def topological_sort(
    nodes: list[BaseNode],
    edges: list[dict],
) -> list[list[BaseNode]]:
    """基于 edges 构建显式 DAG，返回分层结果

    Args:
        nodes: 节点实例列表
        edges: 边列表 [{"source": "a", "target": "b"}, ...]

    Returns:
        分层列表 [[layer0_nodes], [layer1_nodes], ...]
        同层节点可并行执行

    Raises:
        ValueError: 存在循环依赖
    """
    node_map = {n.id: n for n in nodes}
    node_ids = set(node_map.keys())

    # 构建邻接表 + 入度表
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_ids and tgt in node_ids:
            adj[src].append(tgt)
            in_degree[tgt] += 1

    # Kahn 算法分层
    layers: list[list[BaseNode]] = []
    processed = set()

    while len(processed) < len(node_ids):
        # 找出当前入度为 0 的节点（同层）
        layer_ids = [
            nid for nid in node_ids
            if nid not in processed and in_degree[nid] == 0
        ]

        if not layer_ids:
            # 剩余节点都有入度 → 循环依赖
            remaining = [nid for nid in node_ids if nid not in processed]
            raise ValueError(f"存在循环依赖! 无法排序的节点: {remaining}")

        # 按 node_id 排序保证确定性
        layer_ids.sort()

        # 获取节点实例
        layer_nodes = [node_map[nid] for nid in layer_ids]
        layers.append(layer_nodes)

        # 标记已处理，减少下游入度
        for nid in layer_ids:
            processed.add(nid)
            for downstream in adj[nid]:
                in_degree[downstream] -= 1

    return layers


# ═══════════════════════════════════════════════════════
# 执行器
# ═══════════════════════════════════════════════════════

class PipelineExecutor:
    """管线执行器 — 支持 manual / scheduled / listener 三种模式"""

    def __init__(self):
        self._current_run: Optional[RunState] = None
        self._stop_requested: bool = False
        self._event_callback: Optional[Callable] = None
        self._force_no_cache: bool = False

    @property
    def current_run(self) -> Optional[RunState]:
        return self._current_run

    def set_event_callback(self, callback: Callable):
        self._event_callback = callback

    async def _emit(self, event_type: str, data: dict):
        if self._event_callback:
            await self._event_callback(event_type, data)

    def stop(self):
        """请求停止执行 — 设置标志位 + 终止子进程"""
        self._stop_requested = True
        # 终止所有由节点启动的子进程（kukutool 下载等）
        self._terminate_subprocesses()

    def _terminate_subprocesses(self):
        """终止所有正在运行的子进程"""
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

    # ═══════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════

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
        """执行工作流

        Args:
            workflow: 工作流 JSON dict
            config: 全局配置
            date: 日期字符串
            data_root: 数据根目录
            force_no_cache: 强制不使用缓存
            resume_from_node: 从指定节点恢复（跳过之前的节点）
            dry_run: 只校验不执行
        """
        run_id = str(uuid.uuid4())[:8]
        self._stop_requested = False
        self._force_no_cache = force_no_cache

        mode = workflow.get("mode", "manual")

        # 构建 Context
        ctx = PipelineContext(
            date=date,
            data_root=data_root,
            config=config,
            run_id=run_id,
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

        # 注入 edge 映射到节点的 connected inputs
        self._inject_edge_bindings(nodes, workflow.get("edges", []))

        # 初始化运行状态
        self._current_run = RunState(
            run_id=run_id,
            workflow_id=workflow.get("id", "unknown"),
            status="running",
            start_time=time.time(),
            node_states={
                n.id: NodeState(node_id=n.id, node_type=n.type)
                for n in nodes
            },
        )

        await self._emit("run_start", {"run_id": run_id, "mode": mode})

        # 设置日志（含 WebSocket 推送）
        log_queue = asyncio.Queue()
        self._setup_logging(ctx, run_id, date, data_root, log_queue)

        # 后台 task：从 queue 取日志推送到前端
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

        try:
            if mode == "manual":
                await self._execute_manual(nodes, workflow.get("edges", []), ctx, resume_from_node, dry_run)
            elif mode in ("scheduled", "listener"):
                await self._execute_triggered(nodes, workflow.get("edges", []), ctx, dry_run)
            else:
                raise ValueError(f"Unknown workflow mode: {mode}")

            if not self._stop_requested:
                self._current_run.status = "completed"

        except Exception as e:
            self._current_run.status = "failed"
            ctx.logger.error(f"工作流执行失败: {e}", exc_info=True)
            await self._emit("run_error", {"error": str(e)})

        finally:
            # 停止 drain task 并清理
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError:
                pass

            self._current_run.end_time = time.time()
            self._current_run.current_nodes = []
            total_time = self._current_run.end_time - self._current_run.start_time
            ctx.logger.info(f"工作流结束: {self._current_run.status} | 耗时: {total_time:.1f}s")
            await self._emit("run_end", self._current_run.to_dict())

            # 清理 logger handlers
            for h in list(ctx.logger.handlers):
                ctx.logger.removeHandler(h)
                if hasattr(h, 'close'):
                    h.close()

        return self._current_run

    # ═══════════════════════════════════════════════════════
    # Manual 模式：一次性 DAG 执行
    # ═══════════════════════════════════════════════════════

    async def _execute_manual(
        self,
        nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
        resume_from_node: str = None,
        dry_run: bool = False,
    ):
        """手动模式：拓扑排序 + 同层并发"""
        # 过滤掉触发器/监听器节点（manual 模式不执行它们）
        processor_nodes = [
            n for n in nodes
            if not isinstance(n, (TriggerNode, ListenerNode))
        ]

        # 拓扑排序
        layers = topological_sort(processor_nodes, edges)
        ctx.logger.info(f"拓扑排序: {len(layers)} 层, {len(processor_nodes)} 个节点")

        # resume: 跳过指定节点之前的层
        if resume_from_node:
            layers = self._skip_layers_before(layers, resume_from_node)
            ctx.logger.info(f"从节点 {resume_from_node} 恢复, 剩余 {len(layers)} 层")

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
        """执行一层节点（并发）"""
        node_ids = [n.id for n in layer]
        self._current_run.current_nodes = node_ids

        ctx.logger.info(f"执行层: {node_ids}")

        if dry_run:
            # dry-run: 只跑 validate，不执行
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

        # 并发执行
        tasks = [self._run_node(node, ctx) for node in layer]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查失败
        for node, result in zip(layer, results):
            if isinstance(result, Exception):
                node_state = self._current_run.node_states[node.id]
                if node_state.status != NodeStatus.FAILED:
                    # gather 返回的异常但 _run_node 内部没处理到
                    node_state.status = NodeStatus.FAILED
                    node_state.error = str(result)
                # 根据 on_failure 策略
                if node.on_failure == "abort":
                    raise result
                # skip 策略：继续执行后续层

    # ═══════════════════════════════════════════════════════
    # Triggered 模式：定时/监听器驱动
    # ═══════════════════════════════════════════════════════

    async def _execute_triggered(
        self,
        nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
        dry_run: bool = False,
    ):
        """触发器/监听器模式：启动长驻监听"""
        triggers = [
            n for n in nodes
            if isinstance(n, (TriggerNode, ListenerNode))
        ]

        if not triggers:
            raise ValueError("triggered 模式工作流必须包含至少一个 Trigger/Listener 节点")

        ctx.logger.info(f"启动 {len(triggers)} 个触发器/监听器")

        if dry_run:
            ctx.logger.info("dry-run: 跳过监听器启动")
            return

        # 为每个触发器/监听器启动独立的监听 task
        tasks = [
            asyncio.create_task(self._run_listener(t, nodes, edges, ctx))
            for t in triggers
        ]

        # 等待所有监听器（通常永不退出，除非用户 stop）
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_listener(
        self,
        trigger: BaseNode,
        all_nodes: list[BaseNode],
        edges: list[dict],
        ctx: PipelineContext,
    ):
        """单个触发器/监听器的长驻循环"""

        async def emit(event_data: dict):
            """触发下游子图执行"""
            # 1. 写入触发器产出
            output_name = trigger.outputs[0].name if trigger.outputs else "trigger"
            ctx.write(trigger.id, output_name, event_data)

            # 2. 获取下游子图
            downstream_layers = self._get_downstream_subgraph(trigger.id, all_nodes, edges)

            # 3. 执行下游子图
            for layer in downstream_layers:
                if self._stop_requested:
                    break
                await self._execute_layer(layer, ctx)
                await ctx.drain_messages()

            # 4. 双向通道：取下游 reply 产出，发送回复
            if getattr(trigger, "bidirectional", False):
                reply = ctx.read(trigger.id, "reply")
                if reply is None:
                    reply = ctx.find_latest_by_type("Reply")
                if reply and hasattr(trigger, "send_reply"):
                    await trigger.send_reply(ctx, reply)

        # 生命周期
        try:
            ctx.logger.info(f"启动监听器: {trigger.id} ({trigger.type})")
            await trigger.prepare(ctx)
            await trigger.listen(ctx, emit)
        except asyncio.CancelledError:
            ctx.logger.info(f"监听器 {trigger.id} 被取消")
        except Exception as e:
            ctx.logger.error(f"监听器 {trigger.id} 异常: {e}", exc_info=True)
            await self._emit("node_error", {"node_id": trigger.id, "error": str(e)})
        finally:
            await trigger.finalize(ctx, success=False)
            ctx.logger.info(f"监听器 {trigger.id} 已停止")

    def _get_downstream_subgraph(
        self,
        trigger_id: str,
        all_nodes: list[BaseNode],
        edges: list[dict],
    ) -> list[list[BaseNode]]:
        """从 trigger_id 出发，沿 edges 获取所有下游 Processor 节点的拓扑分层"""
        node_map = {n.id: n for n in all_nodes}

        # BFS 收集下游节点
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

    # ═══════════════════════════════════════════════════════
    # 单节点执行（完整生命周期）
    # ═══════════════════════════════════════════════════════

    async def _run_node(self, node: BaseNode, ctx: PipelineContext) -> None:
        """执行单个节点（完整生命周期）"""
        node_state = self._current_run.node_states[node.id]
        node._ctx = ctx  # 注入 ctx 供 get_input 使用

        success = False

        try:
            # prepare
            try:
                await node.prepare(ctx)
            except Exception as e:
                ctx.logger.error(f"[{node.id}] prepare 失败: {e}")
                node_state.status = NodeStatus.SKIPPED
                node_state.message = f"prepare 失败: {e}"
                await self._emit("node_skipped", {"node_id": node.id, "reason": [str(e)]})
                return

            # validate
            errors = await node.validate(ctx)
            if errors:
                node_state.status = NodeStatus.SKIPPED
                node_state.message = f"跳过: {'; '.join(errors)}"
                ctx.logger.info(f"[{node.id}] 跳过: {'; '.join(errors)}")
                await self._emit("node_skipped", {"node_id": node.id, "reason": errors})
                return

            # check_cache
            if not self._force_no_cache and await node.check_cache(ctx):
                await node.restore_cache(ctx)
                node_state.status = NodeStatus.COMPLETED
                node_state.message = "缓存命中"
                node_state.progress = 1.0
                ctx.logger.info(f"[{node.id}] 缓存命中")
                await self._emit("node_cached", {"node_id": node.id})
                success = True
                return

            # execute（含 retry 逻辑）
            node_state.status = NodeStatus.RUNNING
            node_state.start_time = time.time()
            ctx.logger.info(f"[{node.id}] 开始执行 ({node.type})")
            await self._emit("node_start", {"node_id": node.id, "type": node.type})

            def on_progress(message: str, progress: float, _nid=node.id, _ns=node_state):
                _ns.message = message
                _ns.progress = progress

            max_attempts = 1 + (node.max_retries if node.on_failure == "retry" else 0)

            for attempt in range(1, max_attempts + 1):
                try:
                    outputs = await node.execute(ctx, on_progress)

                    # 写入产出到 ctx.data
                    if outputs and isinstance(outputs, dict):
                        for output_name, value in outputs.items():
                            ctx.write(node.id, output_name, value)

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
                        # 重新 prepare
                        try:
                            await node.prepare(ctx)
                        except Exception:
                            pass
                    else:
                        # 最后一次尝试也失败
                        node_state.status = NodeStatus.FAILED
                        node_state.error = str(e)
                        node_state.end_time = time.time()
                        node_state.duration_s = node_state.end_time - node_state.start_time
                        ctx.logger.error(f"[{node.id}] 失败（{max_attempts}次重试后）: {e}", exc_info=True)
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
                        # on_failure=abort 时抛出（由 _execute_layer 处理）
                        elif node.on_failure == "abort":
                            raise

        finally:
            # finalize（无论成功失败都调用）
            try:
                await node.finalize(ctx, success)
            except Exception as e:
                ctx.logger.warning(f"[{node.id}] finalize 异常: {e}")

    def _progress_callback(self, node_id: str, progress: float, message: str):
        """进度回调（线程安全版，通过 call_soon 调度）"""
        if self._event_callback:
            # 注意：这里不能 await，由 _emit 的调用方处理
            pass

    # ═══════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════

    def _inject_edge_bindings(self, nodes: list[BaseNode], edges: list[dict]):
        """将 edge 映射注入到节点的 connected inputs

        edge 格式: {"source": "a", "target": "b", "source_handle": "collected", "target_handle": "collected"}
        → 找到 target 节点中 name == target_handle 的 input，设置 connected_from = "a:collected"
        """
        node_map = {n.id: n for n in nodes}

        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            src_handle = edge.get("source_handle", "")
            tgt_handle = edge.get("target_handle", "")

            if tgt not in node_map:
                continue

            target_node = node_map[tgt]

            # 在 target 节点的 inputs 中找匹配的 connected input
            for inp in target_node.inputs:
                if inp.connected and (inp.name == tgt_handle or not tgt_handle):
                    inp.connected_from = f"{src}:{src_handle}" if src_handle else f"{src}:output"
                    break

            # 旧方式：reads 兼容（直接设置 ctx 属性名映射）
            # 如果节点没有 inputs 声明但用 reads，靠 edges 里的 source_handle 对齐

    def _skip_layers_before(self, layers: list[list[BaseNode]], resume_node_id: str) -> list[list[BaseNode]]:
        """跳过指定节点之前的层"""
        for i, layer in enumerate(layers):
            if any(n.id == resume_node_id for n in layer):
                return layers[i:]
        return layers

    def _setup_logging(self, ctx: PipelineContext, run_id: str, date: str, data_root: Path, log_queue: asyncio.Queue = None):
        """设置日志（独立 logger + 文件 + WebSocket 推送）"""
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

        # WebSocket 推送 handler（通过 queue → drain task → _emit → 前端）
        if log_queue:
            ws_handler = WebSocketLogHandler(log_queue)
            ws_handler.setLevel(logging.INFO)
            ws_handler.setFormatter(logging.Formatter("%(message)s"))
            ctx.logger.addHandler(ws_handler)

        ctx.logger.setLevel(logging.DEBUG)
        ctx.logger.info(f"日志文件: {log_file}")

        # 同时把 agents 层的日志也路由到 ctx.logger
        # agents.collector / agents.director / agents.renderer 的日志会通过 root logger 传播
        # 需要额外挂到 agents logger 上
        for agent_logger_name in ["agents", "agents.collector", "agents.director", "agents.renderer"]:
            agent_logger = logging.getLogger(agent_logger_name)
            if file_handler not in agent_logger.handlers:
                agent_logger.addHandler(file_handler)
            if log_queue:
                ws_handler_agent = WebSocketLogHandler(log_queue)
                ws_handler_agent.setLevel(logging.INFO)
                ws_handler_agent.setFormatter(logging.Formatter("%(message)s"))
                agent_logger.addHandler(ws_handler_agent)
            agent_logger.setLevel(logging.DEBUG)


# 全局执行器实例
executor = PipelineExecutor()
