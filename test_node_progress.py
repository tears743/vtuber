"""Progress reporting checks for built-in and custom workflow nodes."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.engine.executor import NodeState, PipelineExecutor, RunState
from server.models import PipelineContext
from server.nodes.base import BaseNode


class _SlowNode(BaseNode):
    type = "test_progress_slow"
    label = "Progress test"

    async def execute(self, ctx, on_progress):
        await asyncio.sleep(0.07)
        return {"result": "ok"}


class _ThreadProgressNode(BaseNode):
    type = "test_progress_thread"
    label = "Thread progress test"

    async def execute(self, ctx, on_progress):
        await asyncio.to_thread(on_progress, "线程任务 1/2", 0.5)
        await asyncio.sleep(0.01)
        return {"result": "ok"}


class NodeProgressTests(unittest.IsolatedAsyncioTestCase):
    async def _run_node(self, node):
        executor = PipelineExecutor()
        executor._log_queue = asyncio.Queue()
        executor._current_run = RunState(
            run_id="progress-test",
            workflow_id="workflow-test",
            status="running",
            node_states={node.id: NodeState(node_id=node.id, node_type=node.type)},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = PipelineContext(
                date="2026-07-16",
                data_root=Path(temp_dir),
                config={},
            )
            with patch("server.engine.executor.PROGRESS_HEARTBEAT_SECONDS", 0.02):
                await executor._run_node(node, ctx)

        messages = []
        while not executor._log_queue.empty():
            messages.append(executor._log_queue.get_nowait())
        return executor, messages

    async def test_slow_node_emits_periodic_heartbeat(self):
        executor, messages = await self._run_node(_SlowNode("slow", {}))

        progress_messages = [item for item in messages if item.get("type") == "node_progress"]
        self.assertTrue(any("已运行" in item.get("message", "") for item in progress_messages))
        self.assertEqual(executor._current_run.node_states["slow"].progress, 1.0)

    async def test_thread_callback_is_forwarded_safely(self):
        _, messages = await self._run_node(_ThreadProgressNode("thread", {}))

        progress_messages = [item for item in messages if item.get("type") == "node_progress"]
        self.assertTrue(
            any(
                item.get("message") == "线程任务 1/2" and item.get("progress") == 0.5
                for item in progress_messages
            )
        )


if __name__ == "__main__":
    unittest.main()
