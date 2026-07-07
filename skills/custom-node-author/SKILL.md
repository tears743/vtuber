---
name: "custom-node-author"
description: "Creates or edits handwritten VideoFactory nodes and node packs. Invoke when the user asks to manually implement a custom node, trigger, listener, or node pack in this workspace."
---

# Custom Node Author

Use this skill when the user wants to handwrite a custom VideoFactory node in the current workspace.

This skill is specifically for the current node runtime in `videoFactory-node-opt`, not for generic plugin systems.

## When To Invoke

Invoke this skill when the user asks to:

- create a new custom node
- handwrite a Processor / Trigger / Listener node
- add a new node pack or installable node package skeleton
- adapt an old node to the new `BaseNode` runtime
- expose node config and connection schema to the frontend
- add cache logic, lifecycle hooks, or runtime metadata to a node

Do not invoke this skill for:

- generic Python utilities unrelated to the node system
- pure frontend UI work with no node/runtime change
- simple code review with no node authoring

## Source Of Truth

Before editing, always align with the current workspace docs and runtime:

- `docs/CUSTOM_NODES.md`
- `docs/NODE_SYSTEM_RUNTIME.md`
- `server/nodes/base.py`
- `server/nodes/registry.py`
- `server/models.py`
- `server/engine/executor.py`

If the request touches a specific built-in node, also inspect that node and its neighboring runtime files.

## Core Rules

### 1. Use node terminology

Use `node`, `node pack`, `node runtime`.

Do not introduce `plugin` terminology for this system.

### 2. Separate config from connections

Keep these concerns separate:

- `config_schema`: properties panel fields
- `inputs` / `outputs`: canvas connection handles

Do not convert config fields into connection handles unless the runtime already explicitly requires it.

### 3. Match the runtime model

The current system supports three node kinds:

- `processor`
- `trigger`
- `listener`

Choose the right base class:

- `BaseNode` for one-shot processing
- `TriggerNode` for scheduled/event emitters
- `ListenerNode` for long-lived incoming channels

### 4. Respect current execution semantics

The runtime is edge-driven.

- canvas edges determine execution order
- same-layer nodes may run concurrently
- outputs are written into `ctx.data`
- progress must use `on_progress(message, progress)`

### 5. Be conservative with caching

Default to `cacheable = False`.

Only enable caching when the hit semantics are explicit.

If the node is non-idempotent or depends on live external state, prefer:

- no cache, or
- custom `check_cache()` with clear rules

### 6. Use global model config correctly

If the node lets the user choose an LLM, prefer a `config_schema` field with:

```python
{
    "type": "model",
    "label": "模型",
    "default": "deepseek-v4-flash"
}
```

Resolve the actual model details from global config at runtime rather than hardcoding provider fields into the node schema.

## Implementation Workflow

### Step 1. Understand the intent

Determine:

- node kind: Processor / Trigger / Listener
- expected inputs
- expected outputs
- whether the node should be installable as part of a node pack
- whether caching is safe
- whether the frontend needs property panel support

If the request is ambiguous, clarify before writing code.

### Step 2. Inspect adjacent patterns

Look for similar nodes already in the repo.

Examples:

- processor patterns: `collect`, `director`, `tts`
- trigger pattern: `cron_trigger`
- listener patterns: `wechat_channel`, `feishu_channel`, `dingtalk_channel`

Reuse existing conventions for:

- metadata
- logging
- cache restore
- error handling
- output typing

### Step 3. Author the node

At minimum define:

```python
class MyNode(BaseNode):
    type = "my_node"
    label = "My Node"
    category = "Custom"
    description = "..."
    version = "1.0.0"
    author = "..."
    icon = "⚙️"
    color = "#78909C"
```

Then add:

- `inputs`
- `outputs`
- `config_schema`
- `execute()` or `listen()`

### Step 4. Integrate with runtime

Make sure the node can be discovered and used by the current system.

Typical requirements:

- register with `@node(...)` or existing registration mechanism
- keep output names stable
- ensure the frontend can render the node definition
- ensure upstream/downstream types make sense

### Step 5. Validate

After editing:

- run focused syntax / diagnostics checks
- inspect for config-vs-input confusion
- confirm async method signatures match the runtime
- confirm restore / cache methods are awaitable when needed

Do not run workflows unless the user explicitly asked to run them.

## Templates

### Minimal Processor

```python
from server.nodes.base import BaseNode, NodeOutput
from server.nodes.registry import node


@node("hello_world", version="1.0.0", author="you")
class HelloNode(BaseNode):
    label = "Hello World"
    category = "Custom"
    description = "Example processor node"

    outputs = [
        NodeOutput(name="greeting", type="string", label="Greeting"),
    ]

    config_schema = {
        "name": {
            "type": "string",
            "label": "Name",
            "default": "World",
        }
    }

    async def execute(self, ctx, on_progress):
        on_progress("Generating greeting...", 0.5)
        return {"greeting": f"Hello, {self.get_config('name', 'World')}!"}
```

### Minimal Trigger

```python
import asyncio
from datetime import datetime

from server.nodes.base import TriggerNode, NodeOutput
from server.nodes.registry import node


@node("demo_trigger", version="1.0.0")
class DemoTriggerNode(TriggerNode):
    label = "Demo Trigger"
    category = "Trigger"

    outputs = [
        NodeOutput(name="trigger", type="Trigger", label="Trigger"),
    ]

    config_schema = {
        "interval_s": {"type": "int", "label": "Interval", "default": 60, "min": 1}
    }

    async def listen(self, ctx, emit):
        while True:
            await asyncio.sleep(self.get_config("interval_s", 60))
            await emit({"triggered_at": datetime.now().isoformat()})
```

### Minimal Listener

```python
from server.nodes.base import ListenerNode, NodeInput, NodeOutput
from server.nodes.registry import node


@node("demo_listener", version="1.0.0")
class DemoListenerNode(ListenerNode):
    label = "Demo Listener"
    category = "Listener"
    bidirectional = True

    inputs = [
        NodeInput(name="reply", type="Reply", label="Reply", connected=True),
    ]
    outputs = [
        NodeOutput(name="message", type="Message", label="Message"),
    ]

    async def listen(self, ctx, emit):
        await emit({"message": {"text": "hello"}})

    async def send_reply(self, ctx, reply_data):
        ctx.logger.info(f"reply => {reply_data}")
```

## Node Pack Checklist

If the user asks for an installable node pack, create or verify:

- `skills/...` only if they asked for a skill in the project
- `vf-node.yaml`
- `nodes/*.py`
- optional `web/index.js`
- dependency declarations
- version field
- changelog entries if needed

Example manifest:

```yaml
name: my_nodes
version: 1.0.0
author: Your Name
description: My custom nodes
nodes:
  - path: nodes/hello.py
dependencies:
  python:
    - requests>=2.28
  vf: ">=0.1.0"
```

## Handoff Format

When you finish, report:

1. which files were created or updated
2. what node kind and runtime behavior were implemented
3. whether caching was enabled or intentionally left off
4. whether frontend config / handles were added
5. what was validated statically
6. what still requires runtime verification
