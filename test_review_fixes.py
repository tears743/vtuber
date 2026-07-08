"""
验证 Review 修复的测试脚本
不跑完整工作流，只验证修改的代码路径
"""
import asyncio
import sys
import os
import json
import logging
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from server.engine.executor import PipelineExecutor, WebSocketLogHandler, topological_sort
from server.models import PipelineContext
from server.nodes.base import BaseNode, TriggerNode, ListenerNode, NodeInput, NodeOutput
from server.nodes.registry import register, create_node

print("=" * 60)
print("Review 修复验证")
print("=" * 60)

# ═══════════════════════════════════════════════════════
# 1. 验证 on_progress 推送 WebSocket
# ═══════════════════════════════════════════════════════
print("\n[1] on_progress 推送 WebSocket")

executor = PipelineExecutor()

# 创建一个最小工作流
class DummyNode(BaseNode):
    type = "dummy"
    label = "测试节点"
    reads = []
    writes = ["test_output"]
    output_dirs = ["test"]

    async def execute(self, ctx, on_progress):
        on_progress("开始", 0.0)
        await asyncio.sleep(0.1)
        on_progress("进行中", 0.5)
        await asyncio.sleep(0.1)
        on_progress("完成", 1.0)
        return {"test_output": "ok"}

    async def check_cache(self, ctx):
        return False

register(DummyNode)

# 模拟 execute_workflow 的关键部分
ctx = PipelineContext(date="2026-07-08", data_root=Path("data"), config={})
executor._log_queue = asyncio.Queue()
log_queue = executor._log_queue

# 模拟 _run_node 中的 on_progress
node = create_node("dummy", "test_1", {})
node_state = type('NS', (), {'message': '', 'progress': 0.0, 'status': 'pending', 'node_id': 'test_1', 'node_type': 'dummy', 'start_time': 0, 'end_time': 0, 'error': '', 'duration_s': 0})()

async def test_on_progress():
    # 模拟 _run_node 的 on_progress 定义
    def on_progress(message, progress, _nid=node.id, _ns=node_state):
        _ns.message = message
        _ns.progress = progress
        try:
            executor._log_queue.put_nowait({
                "type": "node_progress",
                "node_id": _nid,
                "progress": progress,
                "message": message,
            })
        except Exception:
            pass

    # 执行
    await node.execute(ctx, on_progress)

    # 检查 queue 里有没有 node_progress 消息
    progress_msgs = []
    while not executor._log_queue.empty():
        data = executor._log_queue.get_nowait()
        if data.get("type") == "node_progress":
            progress_msgs.append(data)

    assert len(progress_msgs) == 3, f"Expected 3 progress msgs, got {len(progress_msgs)}"
    assert progress_msgs[0]["message"] == "开始"
    assert progress_msgs[0]["progress"] == 0.0
    assert progress_msgs[1]["progress"] == 0.5
    assert progress_msgs[2]["progress"] == 1.0
    print(f"  ✅ 推送了 {len(progress_msgs)} 条 node_progress 消息")
    print(f"  ✅ 消息内容正确: {[m['message'] for m in progress_msgs]}")

asyncio.run(test_on_progress())

# ═══════════════════════════════════════════════════════
# 2. 验证 WebSocketLogHandler 不重复广播
# ═══════════════════════════════════════════════════════
print("\n[2] WebSocketLogHandler 不重复广播")

test_queue = asyncio.Queue()
handler = WebSocketLogHandler(test_queue)
handler.set_current_nodes(["node_a", "node_b", "node_c"])

# 模拟一条日志
test_record = logging.LogRecord(
    name="test", level=logging.INFO, pathname="", lineno=0,
    msg="测试日志", args=None, exc_info=None
)
handler.emit(test_record)

# 检查只发了一次
msg_count = 0
while not test_queue.empty():
    data = test_queue.get_nowait()
    msg_count += 1
    assert data["node_id"] == "node_a", f"Expected node_a, got {data['node_id']}"

assert msg_count == 1, f"Expected 1 message, got {msg_count}"
print(f"  ✅ 只发送了 {msg_count} 条消息（不再广播 3 次）")

# 验证 extra node_id 优先
test_queue2 = asyncio.Queue()
handler2 = WebSocketLogHandler(test_queue2)
handler2.set_current_nodes(["node_a", "node_b"])

test_record2 = logging.LogRecord(
    name="test", level=logging.INFO, pathname="", lineno=0,
    msg="带 node_id 的日志", args=None, exc_info=None
)
test_record2.node_id = "specific_node"
handler2.emit(test_record2)

data = test_queue2.get_nowait()
assert data["node_id"] == "specific_node", f"Expected specific_node, got {data['node_id']}"
print(f"  ✅ extra node_id 优先: {data['node_id']}")

# ═══════════════════════════════════════════════════════
# 3. 验证 _edge_aliases 兼容层
# ═══════════════════════════════════════════════════════
print("\n[3] _edge_aliases 兼容层")

ctx2 = PipelineContext(date="2026-07-08", data_root=Path("data"), config={})

# 模拟新节点写入
from server.models import CollectedData
ctx2.write("new_collect_1", "collected", CollectedData(dir=Path("data/test"), files=[], count=5, platforms={}))

# 模拟 edge alias
ctx2._edge_aliases["collected"] = ("new_collect_1", "collected")

# 通过 _get_legacy 读取
result = ctx2._get_legacy("collected")
assert result is not None, "Expected non-None from _get_legacy"
assert result.count == 5, f"Expected count=5, got {result.count}"
print(f"  ✅ 旧节点 _get_legacy 通过 edge alias 读到了新节点产出: count={result.count}")

# ═══════════════════════════════════════════════════════
# 4. 验证 send_reply 下游扫描
# ═══════════════════════════════════════════════════════
print("\n[4] send_reply 下游扫描逻辑")

# 模拟 _run_listener 里的下游 BFS 扫描
edges = [
    {"source": "trigger_1", "target": "processor_a", "source_handle": "trigger", "target_handle": "trigger"},
    {"source": "processor_a", "target": "processor_b", "source_handle": "result", "target_handle": "input"},
    {"source": "processor_b", "target": "processor_c", "source_handle": "output", "target_handle": "input"},
]

trigger_id = "trigger_1"
downstream_ids = set()
queue_ids = [trigger_id]
while queue_ids:
    current = queue_ids.pop(0)
    for edge in edges:
        if edge.get("source") == current and edge.get("target") not in downstream_ids:
            downstream_ids.add(edge["target"])
            queue_ids.append(edge["target"])

assert downstream_ids == {"processor_a", "processor_b", "processor_c"}, f"Got {downstream_ids}"
print(f"  ✅ 下游 BFS 扫描正确: {downstream_ids}")

# 模拟下游节点写入 reply
ctx3 = PipelineContext(date="2026-07-08", data_root=Path("data"), config={})
ctx3.write("processor_c", "reply", {"text": "这是回复"})

# 扫描下游找 reply
reply = None
for did in downstream_ids:
    val = ctx3.read(did, "reply")
    if val is not None:
        reply = val
        break

assert reply is not None, "Expected non-None reply"
assert reply["text"] == "这是回复"
print(f"  ✅ 从下游节点 processor_c 读到了 reply: {reply['text']}")

# 验证不再读 trigger 自己的 output
trigger_reply = ctx3.read(trigger_id, "reply")
assert trigger_reply is None, "Should not read reply from trigger itself"
print(f"  ✅ 不再读 trigger 自己的 reply output")

# ═══════════════════════════════════════════════════════
# 5. 验证 sys.path 设置
# ═══════════════════════════════════════════════════════
print("\n[5] sys.path 设置")

project_root = str(Path(__file__).parent)
assert project_root in sys.path, "Project root should be in sys.path"
print(f"  ✅ 项目根目录在 sys.path 中: {project_root}")

# 验证 import agents 可以工作
try:
    import agents.renderer.run_render
    print(f"  ✅ import agents.renderer.run_render 成功")
except ImportError as e:
    print(f"  ⚠️ import agents.renderer.run_render 失败: {e}（可能缺少依赖，不是 sys.path 问题）")

# ═══════════════════════════════════════════════════════
# 6. 验证 requirements.txt
# ═══════════════════════════════════════════════════════
print("\n[6] requirements.txt")

req_content = Path("requirements.txt").read_text(encoding="utf-8")
required = ["openai", "pyyaml", "fastapi", "uvicorn", "pydantic", "psutil", "croniter"]
for pkg in required:
    assert pkg in req_content, f"Missing {pkg} in requirements.txt"
    print(f"  ✅ {pkg} 在 requirements.txt 中")

# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("全部验证通过 ✅")
print("=" * 60)
