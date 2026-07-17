import ast
import inspect
import importlib
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/custom-nodes", tags=["custom-nodes"])

COMMUNITY_DIR = Path(__file__).parent.parent.parent / "nodes" / "community"
VALID_NODE_MODES = {"auto", "processor", "model", "agent", "trigger", "listener"}


class CreateNodeRequest(BaseModel):
    description: str
    preview: bool = False
    code: Optional[str] = None
    model_name: Optional[str] = None
    node_mode: str = "auto"
    tool_names: list[str] = Field(default_factory=list)


class UpdateNodeRequest(BaseModel):
    description: str = ""
    code: str


class EditNodeAIRequest(BaseModel):
    model_name: str
    instruction: str
    code: Optional[str] = None


NODE_REFERENCE_PACKS = {
    "processor": {
        "label": "Deterministic processor",
        "summary": (
            "Use for deterministic processing like download, tts, align, compose. "
            "Read upstream values from ctx, run local/file/service work, and write structured results back to ctx. "
            "Do not generate an agent loop."
        ),
        "constraints": [
            "Subclass BaseNode.",
            "Implement async execute(self, ctx, on_progress).",
            "Declare inputs and outputs with NodeInput/NodeOutput.",
            "Read upstream data with self.get_input() or self.get_inputs().",
            "Return a dict like {'result': value}; do not write ctx.result.",
            "Call on_progress(message, progress) at meaningful stages.",
            "For long-running or multi-step work, check getattr(ctx, '_stop_requested', False) between steps and raise asyncio.CancelledError().",
        ],
        "snippet": r'''
import asyncio
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register

@register
class ExampleProcessNode(BaseNode):
    type = "example_process"
    label = "Example Process"
    category = "Data Processing"
    inputs = [NodeInput(name="input", type="*", label="Input", required=True)]
    outputs = [NodeOutput(name="result", type="JSON", label="Result")]
    output_dirs = ["result"]
    config_schema = {
        "option": {"type": "string", "label": "Option", "default": ""}
    }

    async def execute(self, ctx, on_progress):
        on_progress("Start processing...", 0.0)
        if getattr(ctx, "_stop_requested", False):
            raise asyncio.CancelledError()
        upstream = self.get_input("input")
        output_dir = ctx.data_root / ctx.date / "result"
        output_dir.mkdir(parents=True, exist_ok=True)
        if getattr(ctx, "_stop_requested", False):
            raise asyncio.CancelledError()
        result = {"dir": str(output_dir), "upstream_type": type(upstream).__name__}
        on_progress("Done", 1.0)
        return {"result": result}
''',
    },
    "model": {
        "label": "Model calling node",
        "summary": (
            "Use for recognize-like single-step or short LLM/Vision calls. "
            "Expose only a runtime model field. Resolve base_url/api_key/model from ctx.config['models']."
        ),
        "constraints": [
            "Subclass BaseNode.",
            "Implement async execute(self, ctx, on_progress).",
            "Declare inputs and outputs with NodeInput/NodeOutput.",
            "Read upstream data with self.get_input() or self.get_inputs().",
            "Return a dict like {'result': value}; do not write ctx.result.",
            "Expose only config_schema.model for runtime model selection.",
            "Never hard-code base_url, api_key, or provider model names in generated code.",
            "Check getattr(ctx, '_stop_requested', False) before and after external/model calls and raise asyncio.CancelledError().",
        ],
        "snippet": r'''
import asyncio
from openai import OpenAI
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register

@register
class ExampleModelNode(BaseNode):
    type = "example_model"
    label = "Example Model Node"
    category = "Content Processing"
    inputs = [NodeInput(name="input", type="*", label="Input", required=True)]
    outputs = [NodeOutput(name="result", type="JSON", label="Result")]
    config_schema = {
        "model": {"type": "model", "label": "Model", "default": ""}
    }

    async def execute(self, ctx, on_progress):
        on_progress("Calling model...", 0.1)
        if getattr(ctx, "_stop_requested", False):
            raise asyncio.CancelledError()
        model_name = self.get_config("model", "")
        model_cfg = (ctx.config or {}).get("models", {}).get(model_name)
        if not model_cfg:
            raise RuntimeError(f"Model is not configured: {model_name}")
        client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])
        response = client.chat.completions.create(
            model=model_cfg["model"],
            messages=[{"role": "user", "content": str(self.get_input("input"))}],
            temperature=0.2,
        )
        if getattr(ctx, "_stop_requested", False):
            raise asyncio.CancelledError()
        on_progress("Model call finished", 1.0)
        return {"result": {"text": response.choices[0].message.content}}
''',
    },
    "agent": {
        "label": "Agent orchestration node",
        "summary": (
            "Use for collect/director-like orchestration, reasoning, planning, validation, and multi-step tasks. "
            "If no custom tools are selected or available, generate a pure LLM agent."
        ),
        "constraints": [
            "Subclass BaseNode.",
            "Implement async execute(self, ctx, on_progress).",
            "Declare inputs=[NodeInput('upstream', type='*', multi=True, required=True)] and outputs=[NodeOutput('result', type='JSON')].",
            "Read upstream data with self.get_inputs('upstream').",
            "Return a dict like {'result': value}; do not write ctx.result.",
            "Expose only model and agent_prompt in config_schema.",
            "Resolve runtime model config from ctx.config['models'].",
            "Limit max steps and handle JSON parse failures, tool failures, and final output validation failures.",
            "Check getattr(ctx, '_stop_requested', False) at the start of every agent step and before/after tool or model calls; raise asyncio.CancelledError() when set.",
            "Use only the generation-time selected tool whitelist.",
        ],
        "snippet": r'''
import asyncio
import json
from openai import OpenAI
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register

@register
class ExampleAgentNode(BaseNode):
    type = "example_agent"
    label = "Example Agent"
    category = "Content Processing"
    inputs = [NodeInput(name="upstream", type="*", label="Upstream", multi=True, required=True)]
    outputs = [NodeOutput(name="result", type="JSON", label="Result")]
    allowed_tools = []
    config_schema = {
        "model": {"type": "model", "label": "Model", "default": ""},
        "agent_prompt": {"type": "text", "label": "Agent Prompt", "default": "Finish the task and return JSON."}
    }

    async def execute(self, ctx, on_progress):
        on_progress("Agent initializing...", 0.0)
        model_name = self.get_config("model", "")
        model_cfg = (ctx.config or {}).get("models", {}).get(model_name)
        if not model_cfg:
            raise RuntimeError(f"Model is not configured: {model_name}")
        client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])

        messages = [
            {"role": "system", "content": self.get_config("agent_prompt", "")},
            {"role": "user", "content": json.dumps({"date": ctx.date, "upstream": self.get_inputs("upstream")}, ensure_ascii=False, default=str)},
        ]
        max_steps = 6
        final = None
        for step in range(max_steps):
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()
            on_progress(f"Agent step {step + 1}/{max_steps}", 0.1 + step * 0.12)
            response = client.chat.completions.create(
                model=model_cfg["model"],
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            if getattr(ctx, "_stop_requested", False):
                raise asyncio.CancelledError()
            content = response.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "Return valid JSON only."})
                continue
            if data.get("final") is True:
                final = data
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Continue, or return final=true with the final JSON."})

        if final is None:
            raise RuntimeError("Agent did not produce a final result within max_steps")
        on_progress("Agent finished", 1.0)
        return {"result": final}
''',
    },
    "trigger": {
        "label": "Trigger entry node",
        "summary": (
            "Use for workflow entry events such as cron, webhook, or manual triggers. "
            "Reference cron_trigger: subclass TriggerNode and implement listen(ctx, emit)."
        ),
        "constraints": [
            "Subclass TriggerNode.",
            "Implement async listen(self, ctx, emit).",
            "Call await emit(event_data) when the event fires.",
            "Do not implement this as BaseNode.execute.",
        ],
        "snippet": r'''
import asyncio
from datetime import datetime
from server.nodes.base import NodeOutput, TriggerNode
from server.nodes.registry import node

@node("example_trigger", version="1.0.0", author="ai-generated")
class ExampleTriggerNode(TriggerNode):
    label = "Example Trigger"
    category = "Trigger"
    outputs = [NodeOutput(name="trigger", type="Trigger", label="Trigger Signal")]
    config_schema = {
        "interval_seconds": {"type": "int", "label": "Interval Seconds", "default": 60}
    }

    async def listen(self, ctx, emit):
        while True:
            if getattr(ctx, "_stop_requested", False):
                break
            await asyncio.sleep(self.get_config("interval_seconds", 60))
            await emit({"triggered_at": datetime.now().isoformat()})
''',
    },
    "listener": {
        "label": "Listener node",
        "summary": (
            "Use for long-running external message listeners. Reference wechat_channel: subclass ListenerNode, "
            "prepare connections, loop in listen, optionally implement send_reply, and clean up in finalize."
        ),
        "constraints": [
            "Subclass ListenerNode.",
            "Implement async listen(self, ctx, emit).",
            "Optionally implement prepare, send_reply, and finalize.",
            "Do not implement this as a normal processor.",
        ],
        "snippet": r'''
import asyncio
from server.nodes.base import ListenerNode, NodeInput, NodeOutput
from server.nodes.registry import node

@node("example_listener", version="1.0.0", author="ai-generated")
class ExampleListenerNode(ListenerNode):
    label = "Example Listener"
    category = "Listener"
    bidirectional = True
    inputs = [NodeInput(name="reply", type="Reply", label="Reply", connected=True, required=False)]
    outputs = [NodeOutput(name="message", type="Message", label="Message")]
    config_schema = {
        "api_base": {"type": "string", "label": "API Base", "default": ""}
    }

    async def prepare(self, ctx):
        self._running = True

    async def listen(self, ctx, emit):
        while self._running:
            if getattr(ctx, "_stop_requested", False):
                break
            await asyncio.sleep(5)
            # await emit({"text": "message"})

    async def send_reply(self, ctx, reply_data):
        pass

    async def finalize(self, ctx, success):
        self._running = False
''',
    },
}


def _load_llm_model(model_name: Optional[str] = None) -> dict:
    from server.api.settings import _load_settings

    settings = _load_settings()
    models = settings.get("models", {})
    if model_name:
        cfg = models.get(model_name)
        if not cfg:
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
        caps = cfg.get("capabilities", [])
        if not isinstance(caps, list):
            caps = []
        if "text" not in caps and "coding" not in caps:
            raise HTTPException(status_code=400, detail="Please choose a text or coding capable model")
        return cfg

    for cfg in models.values():
        caps = cfg.get("capabilities", [])
        if isinstance(caps, list) and "coding" in caps:
            return cfg
    raise HTTPException(status_code=400, detail="No coding capable model is configured")


def _extract_python_code(text: str) -> str:
    matches = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[0].strip()
    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[0].strip()
    if "class " in text and ("BaseNode" in text or "TriggerNode" in text or "ListenerNode" in text):
        return text.strip()
    raise HTTPException(status_code=500, detail="LLM response did not contain valid Python code")


def _extract_node_type(code: str) -> str:
    match = re.search(r'@node\s*\(\s*["\']([^"\']+)["\']', code)
    if match:
        return match.group(1)
    match = re.search(r'^\s*type\s*=\s*["\']([^"\']+)["\']', code, re.MULTILINE)
    if match:
        return match.group(1)
    raise HTTPException(status_code=500, detail="Cannot extract node type from generated code")


def _extract_node_artifact(text: str) -> str:
    return _extract_python_code(text)


def _validate_node_artifact(code: str) -> list[str]:
    errors = []
    if not code:
        return ["Python node code is missing."]
    tree = None
    try:
        compile(code, "<generated_node>", "exec")
    except SyntaxError as e:
        errors.append(f"Generated node code has syntax error: {e}")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    try:
        _extract_node_type(code)
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        errors.append(f"Cannot extract node type: {detail}")
    errors.extend(_validate_port_contract(code, tree))
    errors.extend(_validate_model_config_schema(code))
    return errors


def _validate_port_contract(code: str, tree: ast.AST | None) -> list[str]:
    errors = []
    if "ctx.result" in code:
        errors.append("Generated nodes must return {'output_name': value}; do not write ctx.result.")
    if re.search(r"^\s*reads\s*=\s*\[", code, re.MULTILINE):
        errors.append("Generated nodes must use NodeInput inputs instead of reads=[...].")
    if re.search(r"^\s*writes\s*=\s*\[", code, re.MULTILINE):
        errors.append("Generated nodes must use NodeOutput outputs instead of writes=[...].")
    if 'reads = ["collected"]' in code or "reads = ['collected']" in code:
        errors.append('Hard-coded reads=["collected"] is not allowed for generated nodes.')

    if tree is None:
        return errors

    for cls in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        base_names = {
            getattr(base, "id", getattr(base, "attr", ""))
            for base in cls.bases
        }
        is_processor = "BaseNode" in base_names
        is_trigger_or_listener = bool({"TriggerNode", "ListenerNode"} & base_names)
        if not is_processor or is_trigger_or_listener:
            continue

        assignments = {
            target.id
            for stmt in cls.body
            if isinstance(stmt, ast.Assign)
            for target in stmt.targets
            if isinstance(target, ast.Name)
        }
        if "inputs" not in assignments:
            errors.append(f"Processor/Agent class {cls.name} must declare inputs = [NodeInput(...)]")
        if "outputs" not in assignments:
            errors.append(f"Processor/Agent class {cls.name} must declare outputs = [NodeOutput(...)]")

        execute_fn = next(
            (stmt for stmt in cls.body if isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == "execute"),
            None,
        )
        if execute_fn is None:
            errors.append(f"Processor/Agent class {cls.name} must implement async execute().")
            continue
        has_dict_return = any(
            isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict)
            for stmt in ast.walk(execute_fn)
        )
        if not has_dict_return and "return {" not in code:
            errors.append(f"execute() in {cls.name} must return a dict of output values.")

        is_agent = "agent_prompt" in code or "allowed_tools" in assignments or "allowed_tools" in code
        if is_agent:
            if "upstream" not in code or "multi=True" not in code or 'type="*"' not in code:
                errors.append("Agent nodes must declare a wildcard multi input named upstream.")
            if 'get_inputs("upstream"' not in code and "get_inputs('upstream'" not in code:
                errors.append("Agent nodes must read upstream data with self.get_inputs('upstream').")
            if "_stop_requested" not in code or "CancelledError" not in code:
                errors.append("Agent nodes must check ctx._stop_requested each step and raise asyncio.CancelledError() when stopped.")

        has_loop_or_external_call = (
            any(isinstance(n, (ast.For, ast.AsyncFor, ast.While)) for n in ast.walk(execute_fn))
            or "client.chat.completions.create" in code
            or "tool_registry.execute" in code
            or "asyncio.to_thread" in code
            or "subprocess" in code
        )
        if has_loop_or_external_call and ("_stop_requested" not in code or "CancelledError" not in code):
            errors.append(
                f"Long-running execute() in {cls.name} must check ctx._stop_requested and raise asyncio.CancelledError()."
            )
    return errors


def _validate_model_config_schema(code: str) -> list[str]:
    uses_runtime_model = (
        'get_config("model"' in code
        or "get_config('model'" in code
        or '.get("models"' in code
        or ".get('models'" in code
    )
    if not uses_runtime_model:
        return []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "config_schema" for target in node.targets):
            continue
        try:
            schema = ast.literal_eval(node.value)
        except Exception:
            continue
        model_field = schema.get("model") if isinstance(schema, dict) else None
        if isinstance(model_field, dict) and model_field.get("type") == "model":
            return []
        return ['Runtime model nodes must declare config_schema["model"] with type "model".']

    return ['Runtime model nodes must include config_schema["model"] with type "model".']


def _tool_catalog(tool_names: list[str]) -> list[dict]:
    try:
        from server.tools.registry import tool_registry

        if not tool_registry.list_tools():
            tool_registry.load_all()
        tools = tool_registry.list_tools()
    except Exception as e:
        logger.warning("Failed to load custom tools for node generation: %s", e)
        return []

    selected = set(tool_names or [])
    result = []
    for tool in tools:
        name = tool.get("name")
        if selected and name not in selected:
            continue
        result.append(
            {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
                "skill": (tool.get("skill_markdown") or "")[:1200],
            }
        )
    return result


def _project_context_text() -> str:
    """Build stable project context for custom node generation prompts."""

    project_root = Path(__file__).parent.parent.parent
    node_dirs = [
        {
            "path": "server/nodes/",
            "purpose": "Built-in processor nodes and core node APIs. Legacy video pipeline nodes also live here.",
        },
        {
            "path": "server/nodes/builtin/",
            "purpose": "Built-in Trigger/Listener/channel nodes discovered automatically.",
        },
        {
            "path": "nodes/community/<pack>/",
            "purpose": "User/custom node packages. Each package contains vf-node.yaml and node.py.",
        },
        {
            "path": "server/nodes/base.py",
            "purpose": "BaseNode, TriggerNode, ListenerNode, NodeInput, NodeOutput definitions.",
        },
        {
            "path": "server/engine/executor.py",
            "purpose": "Runtime execution, edge binding, output writing, stop/cancel, and node output cache.",
        },
        {
            "path": "server/models.py",
            "purpose": "PipelineContext and shared data classes such as MediaData, ScriptsData, AudioData.",
        },
    ]

    node_catalog = []
    try:
        try:
            import server.nodes.collect  # noqa: F401
            import server.nodes.download  # noqa: F401
            import server.nodes.recognize  # noqa: F401
            import server.nodes.transcribe  # noqa: F401
            import server.nodes.director  # noqa: F401
            import server.nodes.tts  # noqa: F401
            import server.nodes.fish_tts  # noqa: F401
            import server.nodes.voice_visual_director  # noqa: F401
            import server.nodes.align  # noqa: F401
            import server.nodes.overlay  # noqa: F401
            import server.nodes.visual  # noqa: F401
            import server.nodes.subtitle  # noqa: F401
            import server.nodes.live2d  # noqa: F401
            import server.nodes.compose  # noqa: F401
            from server.nodes.loader import pack_loader

            pack_loader.load_all()
        except Exception as e:
            logger.warning("Failed to preload node registry for prompt: %s", e)

        from server.nodes.registry import _registry, get_all_definitions

        definitions_by_type = {item.get("type"): item for item in get_all_definitions()}
        for node_type, cls in _registry.items():
            definition = definitions_by_type.get(node_type, {})
            source_file = inspect.getsourcefile(cls) or ""
            try:
                source_file = str(Path(source_file).resolve().relative_to(project_root))
            except Exception:
                source_file = str(source_file)
            config_schema = definition.get("config_schema") or {}
            node_catalog.append(
                {
                    "type": definition.get("type", node_type),
                    "label": definition.get("label", ""),
                    "category": definition.get("category", ""),
                    "node_kind": definition.get("node_kind", "processor"),
                    "source": source_file,
                    "inputs": [
                        {
                            "name": port.get("name"),
                            "type": port.get("type", "*"),
                            "required": port.get("required", True),
                            "multi": port.get("multi", False),
                            "label": port.get("label", ""),
                        }
                        for port in (definition.get("inputs") or [])
                    ],
                    "outputs": [
                        {
                            "name": port.get("name"),
                            "type": port.get("type", "*"),
                            "label": port.get("label", ""),
                        }
                        for port in (definition.get("outputs") or [])
                    ],
                    "config_fields": {
                        key: {
                            "type": value.get("type") if isinstance(value, dict) else None,
                            "default": value.get("default") if isinstance(value, dict) else None,
                            "options": value.get("options") if isinstance(value, dict) else None,
                        }
                        for key, value in config_schema.items()
                    },
                    "legacy_reads": definition.get("reads") or [],
                    "legacy_writes": definition.get("writes") or [],
                }
            )
    except Exception as e:
        logger.warning("Failed to build node catalog for prompt: %s", e)
        node_catalog = []

    return f"""## VideoFactory project context

VideoFactory is a local visual workflow system. A workflow is a graph of nodes. Nodes declare typed input/output ports, receive upstream data through graph edges, run Python logic, and return output objects for downstream nodes. The runtime also keeps legacy compatibility fields on `PipelineContext` for older video pipeline nodes.

### Important node/source directories
```yaml
{yaml.dump(node_dirs, allow_unicode=True, sort_keys=False).strip()}
```

### Runtime dataflow principle
- New nodes should use ComfyUI-style ports: `inputs = [NodeInput(...)]` and `outputs = [NodeOutput(...)]`.
- Workflow edges use `source_handle` and `target_handle`. The executor binds `target_handle` to a source ref like `source_node_id:source_handle`.
- In `execute()`, read upstream data with `self.get_input("port")`; use `self.get_inputs("port")` only for `multi=True` ports.
- `execute()` must return a dict keyed by output port names, for example `return {{"scripts": scripts_data}}`.
- The executor writes returned values to `ctx.data` as `node_id:output_name`, so downstream nodes can read by connected ports.
- If a downstream legacy node expects `ctx.scripts`, `ctx.media`, `ctx.audio`, etc., set that context field and also return the matching output dict.
- Legacy `reads`/`writes` are compatibility only. Do not use them as the main contract for newly generated processor/agent nodes.
- Type matching is structural at the graph level: exact types should match, while `*` can accept anything. Use specific types like `MediaData`, `ScriptsData`, `AudioData` when the downstream contract is known.
- Trigger/Listener nodes are entry/event nodes and implement `listen()`, not normal `execute()`.

### Existing registered nodes
Use these as the current source of truth for available node types, ports, config fields, and source files.
```yaml
{yaml.dump(node_catalog, allow_unicode=True, sort_keys=False).strip()}
```
"""


def _reference_text(node_mode: str) -> str:
    mode = (node_mode or "auto").strip()
    if mode != "auto" and mode in NODE_REFERENCE_PACKS:
        pack = NODE_REFERENCE_PACKS[mode]
        constraints = "\n".join(f"- {item}" for item in pack["constraints"])
        return f"""## User selected reference type: {pack['label']}

### When to use it
{pack['summary']}

### Structural constraints
{constraints}

### Compact reference code
```python
{pack['snippet'].strip()}
```
"""

    decision = "\n".join(
        f"- {key}: {pack['label']}. {pack['summary']}"
        for key, pack in NODE_REFERENCE_PACKS.items()
    )
    mini_refs = "\n\n".join(
        (
            f"### {key}: {pack['label']}\n"
            f"{pack['summary']}\n"
            "Structural constraints:\n"
            + "\n".join(f"- {item}" for item in pack["constraints"])
            + f"\n```python\n{pack['snippet'].strip()}\n```"
        )
        for key, pack in NODE_REFERENCE_PACKS.items()
    )
    return f"""## No reference type selected: decide the node type first

Decision table:
{decision}

Deterministic processing: like download/tts/align/compose.
Model calling processing: like recognize.
Orchestration/reasoning/multi-step work: like collect/director, suitable for agent.
Event entry: Trigger/Listener.

After deciding, generate only one best-fit node type. Do not mix modes.

## Available reference packs
{mini_refs}
"""


def _build_prompt(req: CreateNodeRequest) -> str:
    mode = (req.node_mode or "auto").strip()
    if mode not in VALID_NODE_MODES:
        mode = "auto"

    tools = _tool_catalog(req.tool_names) if mode in {"auto", "agent"} else []
    tool_section = "No custom tools are available. If generating an Agent node, make it a pure LLM Agent and do not call tool_registry."
    if tools:
        tool_section = yaml.dump(tools, allow_unicode=True, sort_keys=False)

    return f"""You are writing a VideoFactory custom node. Generate one complete Python file for the user's requirement.

## Global rules
- Output exactly one ```python code block, with no extra explanation.
- The generated file must compile.
- Use existing project APIs: `server.nodes.base` and `server.nodes.registry`.
- Never hard-code `base_url`, `api_key`, or provider model names in node code.
- Nodes that need runtime LLM access must expose only `model` in config_schema and resolve config through `(ctx.config or {{}}).get("models", {{}}).get(model_name)`.
- The generation-time LLM and the runtime node LLM are separate. Do not bake the generation model into node code.
- Normal processor nodes must not contain an agent loop. Generate an Agent only when the selected type is agent or auto mode clearly needs planning/reasoning/multi-step orchestration.
- Call `on_progress(message, progress)` for processors/model/agent nodes.
- Generated processor/model/agent nodes must be stoppable: import `asyncio` when needed, check `getattr(ctx, "_stop_requested", False)` between expensive steps, before/after model/tool/subprocess calls, and inside loops; raise `asyncio.CancelledError()` when it is set.
- Processor nodes implement `execute(self, ctx, on_progress)`. Trigger/Listener nodes implement `listen(self, ctx, emit)`.
- Processor/model/agent nodes must declare `inputs = [NodeInput(...)]` and `outputs = [NodeOutput(...)]`.
- Read upstream data with `self.get_input("port_name")` or `self.get_inputs("port_name")`.
- `execute()` must return a dict mapping output port names to values, for example `return {{"result": value}}`.
- Do not use `reads = [...]`, `writes = [...]`, or `ctx.result = ...` in generated processor/model/agent nodes.
- Agent default ports must be `inputs = [NodeInput(name="upstream", type="*", multi=True, required=True)]` and `outputs = [NodeOutput(name="result", type="JSON")]`.
- If generated code writes local files, include the file path or directory path in the returned output dict so node output caching can collect it.

{_project_context_text()}

{_reference_text(mode)}

## Agent tool constraints
- Only Agent nodes may use tools.
- If the tool list is empty, generate a pure LLM Agent.
- If the tool list is non-empty, hard-code the whitelist to only the selected tools.
- To call tools, use `from server.tools.registry import tool_registry` and `tool_registry.execute(tool_name, params)`.
- Agent code must limit max steps and handle JSON parse failures, tool failures, and final output validation failures.
- Agent code must check `ctx._stop_requested` at the start of every step and before/after every model/tool call.

### Available custom tools
```yaml
{tool_section}
```

## User requirement
{req.description}
"""


def _call_llm(model_cfg: dict, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])
    response = client.chat.completions.create(
        model=model_cfg["model"],
        messages=[
            {
                "role": "system",
                "content": "You are a senior Python backend engineer generating VideoFactory custom node code.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=model_cfg.get("max_output_tokens", 8192),
        temperature=0.25,
    )
    return response.choices[0].message.content


def _build_edit_prompt(name: str, current_code: str, instruction: str) -> str:
    return f"""You are editing an existing VideoFactory custom node.

Rules:
- Output exactly one ```python code block and no extra explanation.
- Keep the node type exactly "{name}".
- Return the full updated node.py file, not a patch.
- Preserve working behavior unless the user explicitly asks to change it.
- Follow current custom node standards where practical: NodeInput/NodeOutput ports, self.get_input/get_inputs, return output dicts, runtime model selected through config_schema["model"] with type "model".
- Long-running code must check `getattr(ctx, "_stop_requested", False)` between expensive steps and raise `asyncio.CancelledError()` when stopped.
- Do not hard-code API keys, base URLs, or provider model names.

{_project_context_text()}

Current node.py:
```python
{current_code}
```

User edit instruction:
{instruction}
"""


def _validate_ai_edit_artifact(name: str, code: str) -> list[str]:
    errors = _validate_node_artifact(code)
    try:
        node_type = _extract_node_type(code)
        if node_type != name:
            errors.append(f"Edited node type must remain '{name}', got '{node_type}'.")
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        errors.append(f"Cannot extract edited node type: {detail}")
    return errors


def _hot_reload_node(pack_dir: Path) -> None:
    if str(pack_dir) not in sys.path:
        sys.path.insert(0, str(pack_dir))
    if "node" in sys.modules:
        del sys.modules["node"]
    importlib.import_module("node")


def _list_community_nodes() -> list[dict]:
    result = []
    if not COMMUNITY_DIR.exists():
        return result

    for pack_dir in COMMUNITY_DIR.iterdir():
        if not pack_dir.is_dir():
            continue
        manifest = pack_dir / "vf-node.yaml"
        if not manifest.exists():
            continue
        try:
            info = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            enabled = not (pack_dir / ".disabled").exists()
            nodes_list = info.get("nodes", []) or [{"type": pack_dir.name}]
            for node_entry in nodes_list:
                result.append(
                    {
                        "name": info.get("name", pack_dir.name),
                        "type": node_entry.get("type", pack_dir.name),
                        "enabled": enabled,
                        "description": info.get("description", ""),
                        "version": info.get("version", "0.0.0"),
                        "author": info.get("author", ""),
                        "path": str(pack_dir),
                    }
                )
        except Exception as e:
            logger.error("Failed to parse community node %s: %s", pack_dir.name, e)
            result.append(
                {
                    "name": pack_dir.name,
                    "type": pack_dir.name,
                    "enabled": True,
                    "description": f"(manifest parse failed: {e})",
                    "version": "0.0.0",
                    "author": "",
                    "path": str(pack_dir),
                }
            )
    return result


@router.get("")
async def list_custom_nodes():
    return {"nodes": _list_community_nodes()}


@router.get("/{name}")
async def get_custom_node(name: str):
    pack_dir = COMMUNITY_DIR / name
    if not pack_dir.exists():
        raise HTTPException(status_code=404, detail=f"Node '{name}' does not exist")

    node_path = pack_dir / "node.py"
    manifest_path = pack_dir / "vf-node.yaml"
    if not node_path.exists():
        raise HTTPException(status_code=404, detail=f"Node code for '{name}' does not exist")

    manifest = {}
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    return {
        "name": name,
        "type": (manifest.get("nodes") or [{}])[0].get("type", name),
        "description": manifest.get("description", ""),
        "version": manifest.get("version", "1.0.0"),
        "author": manifest.get("author", ""),
        "enabled": not (pack_dir / ".disabled").exists(),
        "path": str(pack_dir),
        "code": node_path.read_text(encoding="utf-8"),
        "manifest": manifest,
    }


@router.post("/create")
async def create_custom_node(req: CreateNodeRequest):
    if req.code:
        code = req.code.strip()
        agent_attempts = 0
        agent_validation_errors = _validate_node_artifact(code)
    else:
        model_cfg = _load_llm_model(req.model_name)
        try:
            from server.ai.generation_agent import run_generation_agent

            result = run_generation_agent(
                model_cfg=model_cfg,
                task_prompt=_build_prompt(req),
                system_prompt="You are a senior Python backend engineer generating VideoFactory custom node code.",
                extract_artifact=_extract_node_artifact,
                validate_artifact=_validate_node_artifact,
                max_steps=4,
                temperature=0.25,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("LLM node generation failed: %s", e, exc_info=True)
            raise HTTPException(status_code=502, detail=f"LLM call failed: {str(e)}")
        if result.validation_errors:
            raise HTTPException(status_code=502, detail="AI node generation validation failed: " + "; ".join(result.validation_errors))
        code = result.artifact
        agent_attempts = result.attempts
        agent_validation_errors = result.validation_errors

    if req.preview:
        return {
            "status": "preview",
            "code": code,
            "agent_attempts": agent_attempts,
            "agent_validation_errors": agent_validation_errors,
        }

    node_type = _extract_node_type(code)
    pack_dir = COMMUNITY_DIR / node_type
    if pack_dir.exists():
        raise HTTPException(status_code=409, detail=f"Node '{node_type}' already exists")

    try:
        compile(code, f"<generated_node_{node_type}>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=500, detail=f"Generated code has syntax error: {e}")

    COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "node.py").write_text(code, encoding="utf-8")

    manifest = {
        "name": node_type,
        "version": "1.0.0",
        "author": "ai-generated",
        "description": req.description,
        "nodes": [{"path": "node.py", "type": node_type}],
    }
    (pack_dir / "vf-node.yaml").write_text(
        yaml.dump(manifest, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    try:
        _hot_reload_node(pack_dir)
    except Exception as e:
        logger.warning("Node saved but hot reload failed: %s", e)

    return {
        "status": "created",
        "name": node_type,
        "type": node_type,
        "path": str(pack_dir),
        "code": code,
        "agent_attempts": agent_attempts,
        "agent_validation_errors": agent_validation_errors,
    }


@router.delete("/{name}")
async def delete_custom_node(name: str):
    pack_dir = COMMUNITY_DIR / name
    if not pack_dir.exists():
        raise HTTPException(status_code=404, detail=f"Node '{name}' does not exist")

    try:
        shutil.rmtree(pack_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    try:
        from server.nodes.registry import _registry

        to_remove = [
            key for key, value in _registry.items()
            if getattr(value, "node_pack", "") == name or key == name
        ]
        for key in to_remove:
            _registry.pop(key, None)
    except Exception:
        pass

    return {"status": "deleted", "name": name}


@router.put("/{name}")
async def update_custom_node(name: str, req: UpdateNodeRequest):
    pack_dir = COMMUNITY_DIR / name
    if not pack_dir.exists():
        raise HTTPException(status_code=404, detail=f"Node '{name}' does not exist")

    code = req.code.strip()
    try:
        compile(code, f"<custom_node_{name}>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Node code has syntax error: {e}")

    node_type = _extract_node_type(code)
    if node_type != name:
        raise HTTPException(
            status_code=400,
            detail=f"Editing cannot change node type from '{name}' to '{node_type}'. Create a new node instead.",
        )

    node_path = pack_dir / "node.py"
    manifest_path = pack_dir / "vf-node.yaml"
    manifest = {}
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    manifest.update(
        {
            "name": name,
            "version": manifest.get("version", "1.0.0"),
            "author": manifest.get("author", "ai-generated"),
            "description": req.description,
            "nodes": [{"path": "node.py", "type": node_type}],
        }
    )

    node_path.write_text(code, encoding="utf-8")
    manifest_path.write_text(
        yaml.dump(manifest, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    try:
        _hot_reload_node(pack_dir)
    except Exception as e:
        logger.warning("Node saved but hot reload failed: %s", e)

    return {
        "status": "updated",
        "name": name,
        "type": node_type,
        "description": req.description,
        "path": str(pack_dir),
    }


@router.post("/{name}/ai-edit")
async def ai_edit_custom_node(name: str, req: EditNodeAIRequest):
    pack_dir = COMMUNITY_DIR / name
    if not pack_dir.exists():
        raise HTTPException(status_code=404, detail=f"Node '{name}' does not exist")

    instruction = req.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Edit instruction is required")

    node_path = pack_dir / "node.py"
    if not node_path.exists() and not req.code:
        raise HTTPException(status_code=404, detail=f"Node code for '{name}' does not exist")

    current_code = (req.code or node_path.read_text(encoding="utf-8")).strip()
    model_cfg = _load_llm_model(req.model_name)

    try:
        from server.ai.generation_agent import run_generation_agent

        result = run_generation_agent(
            model_cfg=model_cfg,
            task_prompt=_build_edit_prompt(name, current_code, instruction),
            system_prompt="You are a senior Python backend engineer editing VideoFactory custom node code.",
            extract_artifact=_extract_node_artifact,
            validate_artifact=lambda code: _validate_ai_edit_artifact(name, code),
            max_steps=4,
            temperature=0.2,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI node edit failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"AI node edit failed: {str(e)}")

    if result.validation_errors:
        raise HTTPException(status_code=502, detail="AI node edit validation failed: " + "; ".join(result.validation_errors))

    return {
        "status": "preview",
        "name": name,
        "code": result.artifact,
        "agent_attempts": result.attempts,
        "agent_validation_errors": result.validation_errors,
    }


@router.post("/{name}/toggle")
async def toggle_custom_node(name: str):
    pack_dir = COMMUNITY_DIR / name
    if not pack_dir.exists():
        raise HTTPException(status_code=404, detail=f"Node '{name}' does not exist")

    disabled_file = pack_dir / ".disabled"
    if disabled_file.exists():
        disabled_file.unlink()
        try:
            _hot_reload_node(pack_dir)
        except Exception as e:
            logger.warning("Hot reload after enabling failed: %s", e)
        return {"status": "enabled", "name": name, "enabled": True}

    disabled_file.touch()
    return {"status": "disabled", "name": name, "enabled": False}
