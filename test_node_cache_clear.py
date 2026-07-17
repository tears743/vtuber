import asyncio
import tempfile
import unittest
from pathlib import Path

from server.engine.executor import NodeState, PipelineExecutor, RunState
from server.engine.node_cache import NodeCacheManager
from server.models import PipelineContext
from server.nodes.base import BaseNode, NodeOutput


class CacheClearProbeNode(BaseNode):
    type = "cache_clear_probe"
    outputs = [NodeOutput("result", type="JSON")]
    cacheable = True
    output_dirs = ["legacy-output"]

    execute_count = 0

    async def execute(self, ctx, on_progress):
        type(self).execute_count += 1
        on_progress("probe", 0.5)
        return {"result": {"execution": type(self).execute_count}}


class NodeCacheClearTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        CacheClearProbeNode.execute_count = 0
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.date = "2026-07-17"
        self.workflow_id = "cache-test"
        self.node_id = "probe-1"

        legacy_dir = self.data_root / self.date / "legacy-output"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "existing.txt").write_text("legacy artifact", encoding="utf-8")

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def _run_node(self):
        node = CacheClearProbeNode(self.node_id)
        ctx = PipelineContext(date=self.date, data_root=self.data_root, run_id="test-run")
        executor = PipelineExecutor()
        executor._current_run = RunState(
            run_id="test-run",
            workflow_id=self.workflow_id,
            status="running",
            node_states={self.node_id: NodeState(node_id=self.node_id, node_type=node.type)},
        )
        executor._node_cache = NodeCacheManager(self.data_root, self.date, self.workflow_id)
        executor._workflow_edges = []
        executor._log_queue = asyncio.Queue()

        await executor._run_node(node, ctx)
        return ctx.read(self.node_id, "result")

    async def test_clear_forces_execution_even_when_legacy_output_directory_exists(self):
        first = await self._run_node()
        self.assertEqual(first, {"execution": 1})

        cached = await self._run_node()
        self.assertEqual(cached, {"execution": 1})
        self.assertEqual(CacheClearProbeNode.execute_count, 1)

        manager = NodeCacheManager(self.data_root, self.date, self.workflow_id)
        self.assertEqual(manager.clear_node(self.node_id), 1)

        rerun = await self._run_node()
        self.assertEqual(rerun, {"execution": 2})
        self.assertEqual(CacheClearProbeNode.execute_count, 2)


if __name__ == "__main__":
    unittest.main()
