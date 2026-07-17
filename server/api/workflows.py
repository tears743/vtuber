"""Workflow CRUD, templates, and AI workflow generation APIs."""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])
templates_router = APIRouter(prefix="/api/workflow-templates", tags=["workflow-templates"])

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "workflows"
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "data" / "workflow_templates"
MIGRATION_BACKUP_DIR = WORKFLOWS_DIR / ".backup_before_port_migration"


class WorkflowCreate(BaseModel):
    name: str
    nodes: list = []
    edges: list = []
    draft: bool = False
    validation_errors: list[str] = []
    goal: Optional[str] = None
    plan_text: Optional[str] = None


class WorkflowUpdate(BaseModel):
    name: str = None
    nodes: list = None
    edges: list = None
    draft: Optional[bool] = None
    validation_errors: Optional[list[str]] = None
    goal: Optional[str] = None
    plan_text: Optional[str] = None


class TemplateCreate(BaseModel):
    template_name: str


class WorkflowImport(BaseModel):
    name: str = None
    nodes: list = []
    edges: list = []


class WorkflowAIPreviewRequest(BaseModel):
    model_name: str
    goal: str


class WorkflowAIConfirmRequest(BaseModel):
    workflow: dict
    goal: str = ""
    plan_text: str = ""
    validation_errors: list[str] = []


def _ensure_dir():
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)


def _list_files() -> list[Path]:
    _ensure_dir()
    return sorted(path for path in WORKFLOWS_DIR.glob("*.json") if path.is_file())


def _save(wf_id: str, data: dict):
    _ensure_dir()
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load(wf_id: str) -> dict:
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{wf_id}' not found")
    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    migrated, changed = _migrate_legacy_edges(workflow)
    if changed:
        MIGRATION_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = MIGRATION_BACKUP_DIR / path.name
        if not backup_path.exists():
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(workflow, f, ensure_ascii=False, indent=2)
        migrated["updated_at"] = datetime.now().isoformat()
        _save(wf_id, migrated)
        return migrated
    return workflow


def _available_node_definitions() -> list[dict]:
    from server.nodes.registry import get_all_definitions, list_types

    if not list_types():
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

    return get_all_definitions()


def _node_definition_map() -> dict[str, dict]:
    return {d.get("type"): d for d in _available_node_definitions() if d.get("type")}


def _known_node_types() -> set[str]:
    return set(_node_definition_map().keys())


def _infer_source_handle(node_type: str, definitions: dict[str, dict] | None = None) -> str:
    definitions = definitions or _node_definition_map()
    outputs = (definitions.get(node_type, {}) or {}).get("outputs", []) or []
    return (outputs[0] or {}).get("name", "output") if outputs else "output"


def _infer_target_handle(node_type: str, definitions: dict[str, dict] | None = None) -> str:
    definitions = definitions or _node_definition_map()
    inputs = (definitions.get(node_type, {}) or {}).get("inputs", []) or []
    for item in inputs:
        if item.get("name") == "upstream":
            return "upstream"
    for item in inputs:
        if item.get("required", True):
            return item.get("name", "input")
    return (inputs[0] or {}).get("name", "input") if inputs else "input"


def _load_llm_model(model_name: str) -> dict:
    from server.api.settings import _load_settings

    settings = _load_settings()
    cfg = settings.get("models", {}).get(model_name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    caps = cfg.get("capabilities", [])
    if not isinstance(caps, list):
        caps = []
    if "text" not in caps and "coding" not in caps:
        raise HTTPException(status_code=400, detail="请选择具备 text 或 coding 能力的模型")
    return cfg


def _sanitize_id(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    return text or fallback


def _layout_nodes(nodes: list[dict], edges: list[dict]) -> list[dict]:
    node_ids = [n.get("id") for n in nodes]
    incoming = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        target = edge.get("target")
        if target in incoming:
            incoming[target] += 1

    levels = {node_id: 0 if incoming.get(node_id, 0) == 0 else 1 for node_id in node_ids}
    for _ in range(max(len(node_ids), 1)):
        changed = False
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source in levels and target in levels and levels[target] <= levels[source]:
                levels[target] = levels[source] + 1
                changed = True
        if not changed:
            break

    rows: dict[int, int] = {}
    for node in nodes:
        pos = node.get("position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            continue
        level = levels.get(node.get("id"), 0)
        row = rows.get(level, 0)
        rows[level] = row + 1
        node["position"] = {"x": 120 + level * 260, "y": 120 + row * 140}
    return nodes


def _normalize_workflow(workflow: dict) -> dict:
    raw_nodes = workflow.get("nodes", [])
    raw_edges = workflow.get("edges", [])
    nodes = []
    definitions = _node_definition_map()

    for index, item in enumerate(raw_nodes if isinstance(raw_nodes, list) else []):
        if not isinstance(item, dict):
            continue
        node_type = item.get("type", "")
        node_id = _sanitize_id(item.get("id"), f"{node_type or 'node'}_{index + 1}")
        config = item.get("config", {})
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "position": item.get("position") if isinstance(item.get("position"), dict) else {},
                "config": config if isinstance(config, dict) else {},
                "inputs": (definitions.get(node_type, {}) or {}).get("inputs", []),
                "outputs": (definitions.get(node_type, {}) or {}).get("outputs", []),
            }
        )

    node_type_by_id = {node["id"]: node["type"] for node in nodes}
    edges = []
    for item in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "")
        target = item.get("target", "")
        edges.append(
            {
                "source": source,
                "source_handle": item.get("source_handle")
                or item.get("sourceHandle")
                or _infer_source_handle(node_type_by_id.get(source, ""), definitions),
                "target": target,
                "target_handle": item.get("target_handle")
                or item.get("targetHandle")
                or _infer_target_handle(node_type_by_id.get(target, ""), definitions),
            }
        )

    name = str(workflow.get("name") or "AI 生成工作流").strip() or "AI 生成工作流"
    return {"name": name, "nodes": _layout_nodes(nodes, edges), "edges": edges}


def _migrate_legacy_edges(workflow: dict) -> tuple[dict, bool]:
    edges = workflow.get("edges", [])
    if not isinstance(edges, list):
        return workflow, False

    definitions = _node_definition_map()
    node_type_by_id = {
        node.get("id"): node.get("type")
        for node in workflow.get("nodes", [])
        if isinstance(node, dict)
    }
    changed = False
    migrated_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            changed = True
            continue
        source = edge.get("source", "")
        target = edge.get("target", "")
        source_type = node_type_by_id.get(source, "")
        target_type = node_type_by_id.get(target, "")
        source_outputs = {
            item.get("name")
            for item in (definitions.get(source_type, {}) or {}).get("outputs", [])
            if item.get("name")
        }
        target_inputs = {
            item.get("name")
            for item in (definitions.get(target_type, {}) or {}).get("inputs", [])
            if item.get("name")
        }
        source_handle = edge.get("source_handle") or edge.get("sourceHandle")
        target_handle = edge.get("target_handle") or edge.get("targetHandle")
        if not source_handle or (source_outputs and source_handle not in source_outputs):
            source_handle = _infer_source_handle(source_type, definitions)
            changed = True
        if target_inputs and source_handle in target_inputs and target_handle != source_handle:
            target_handle = source_handle
            changed = True
        elif not target_handle or (target_inputs and target_handle not in target_inputs):
            target_handle = _infer_target_handle(target_type, definitions)
            changed = True
        migrated_edges.append(
            {
                "source": source,
                "source_handle": source_handle,
                "target": target,
                "target_handle": target_handle,
            }
        )

    if not changed:
        return workflow, False

    normalized = _normalize_workflow({**workflow, "edges": migrated_edges})
    migrated = dict(workflow)
    migrated["name"] = normalized["name"]
    migrated["nodes"] = normalized["nodes"]
    migrated["edges"] = normalized["edges"]
    return migrated, True


def _prevalidate_workflow_payload(workflow: dict) -> list[str]:
    errors = []
    raw_nodes = workflow.get("nodes", [])
    raw_edges = workflow.get("edges", [])
    raw_ids = []

    if not isinstance(raw_nodes, list):
        errors.append("nodes 必须是数组")
        raw_nodes = []
    if not isinstance(raw_edges, list):
        errors.append("edges 必须是数组")
        raw_edges = []

    for idx, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            errors.append(f"第 {idx + 1} 个节点必须是对象")
            continue
        node_id = _sanitize_id(node.get("id"), "")
        if node_id:
            raw_ids.append(node_id)
        if "config" in node and not isinstance(node.get("config"), dict):
            errors.append(f"节点 {node_id or idx + 1} 的 config 必须是对象")

    seen = set()
    for node_id in raw_ids:
        if node_id in seen:
            errors.append(f"节点 id 重复: {node_id}")
        seen.add(node_id)
    return errors


def _validate_workflow_graph(workflow: dict) -> list[str]:
    errors = []
    known_types = _known_node_types()
    seen_ids = set()
    nodes = workflow.get("nodes", []) if isinstance(workflow.get("nodes", []), list) else []
    edges = workflow.get("edges", []) if isinstance(workflow.get("edges", []), list) else []

    for idx, node in enumerate(nodes):
        node_id = node.get("id")
        node_type = node.get("type")
        if not node_id:
            errors.append(f"第 {idx + 1} 个节点缺少 id")
            continue
        if node_id in seen_ids:
            errors.append(f"节点 id 重复: {node_id}")
        seen_ids.add(node_id)
        if node_type not in known_types:
            errors.append(f"节点 {node_id} 使用了不存在的类型: {node_type}")
        if not isinstance(node.get("config", {}), dict):
            errors.append(f"节点 {node_id} 的 config 必须是对象")

    for idx, edge in enumerate(edges):
        source = edge.get("source")
        target = edge.get("target")
        if source not in seen_ids:
            errors.append(f"第 {idx + 1} 条连线 source 不存在: {source}")
        if target not in seen_ids:
            errors.append(f"第 {idx + 1} 条连线 target 不存在: {target}")
        if source and target and source == target:
            errors.append(f"第 {idx + 1} 条连线不能连接节点自身: {source}")
    return errors


def _validate_workflow_ports(workflow: dict) -> list[str]:
    errors = []
    definitions = _node_definition_map()
    nodes = workflow.get("nodes", []) if isinstance(workflow.get("nodes", []), list) else []
    edges = workflow.get("edges", []) if isinstance(workflow.get("edges", []), list) else []
    node_types = {node.get("id"): node.get("type") for node in nodes if isinstance(node, dict)}
    node_ids = set(node_types.keys())
    incoming_by_target_handle: dict[tuple[str, str], int] = {}

    for idx, edge in enumerate(edges):
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids or target not in node_ids:
            continue
        source_handle = edge.get("source_handle") or edge.get("sourceHandle")
        target_handle = edge.get("target_handle") or edge.get("targetHandle")
        source_outputs = {
            item.get("name"): item
            for item in (definitions.get(node_types.get(source), {}) or {}).get("outputs", [])
            if item.get("name")
        }
        target_inputs = {
            item.get("name"): item
            for item in (definitions.get(node_types.get(target), {}) or {}).get("inputs", [])
            if item.get("name")
        }
        if not source_handle:
            errors.append(f"第 {idx + 1} 条连线缺少 source_handle")
            continue
        if not target_handle:
            errors.append(f"第 {idx + 1} 条连线缺少 target_handle")
            continue
        if source_handle not in source_outputs:
            errors.append(f"第 {idx + 1} 条连线 source_handle 不存在: {source}.{source_handle}")
            continue
        if target_handle not in target_inputs:
            errors.append(f"第 {idx + 1} 条连线 target_handle 不存在: {target}.{target_handle}")
            continue
        out_type = source_outputs[source_handle].get("type", "*")
        in_type = target_inputs[target_handle].get("type", "*")
        if out_type != "*" and in_type != "*" and out_type != in_type:
            errors.append(f"第 {idx + 1} 条连线类型不兼容: {out_type} -> {in_type}")
        key = (target, target_handle)
        incoming_by_target_handle[key] = incoming_by_target_handle.get(key, 0) + 1
        if incoming_by_target_handle[key] > 1 and not target_inputs[target_handle].get("multi", False):
            errors.append(f"输入端口不允许多连: {target}.{target_handle}")
    return errors


def _validate_workflow(workflow: dict) -> list[str]:
    errors = _validate_workflow_graph(workflow)
    for err in _validate_workflow_ports(workflow):
        if err not in errors:
            errors.append(err)
    return errors


def _build_workflow_prompt(goal: str) -> str:
    node_lines = []
    for d in _available_node_definitions():
        node_lines.append(
            {
                "type": d.get("type"),
                "label": d.get("label"),
                "inputs": d.get("inputs", []),
                "outputs": d.get("outputs", []),
                "config_schema": d.get("config_schema", {}),
                "node_kind": d.get("node_kind", "processor"),
            }
        )

    return f"""You are a VideoFactory workflow generation agent.
Generate a workflow plan and graph for the user goal using only available node types.

Rules:
- Output JSON only. No Markdown.
- Top-level keys: name, plan_text, nodes, edges.
- Every node must include id, type, config, and optional position.
- Every edge must include source, source_handle, target, target_handle.
- source_handle must exist in the source node outputs.
- target_handle must exist in the target node inputs.
- Port types must match unless either side is "*".
- Do not generate source/target-only edges.
- If validation fails, repair the JSON instead of explaining.
- plan_text must be Chinese and explain the workflow steps, why nodes connect, and what users need to configure.

available_nodes:
{json.dumps(node_lines, ensure_ascii=False, indent=2)}

用户目标:
{goal}
"""


def _extract_json_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _extract_workflow_artifact(text: str) -> dict:
    return _extract_json_object(text)


def _validate_workflow_artifact(raw: dict) -> list[str]:
    pre_errors = _prevalidate_workflow_payload(raw)
    workflow = _normalize_workflow(raw)
    graph_errors = _validate_workflow(workflow)
    return pre_errors + [err for err in graph_errors if err not in pre_errors]


def _ensure_templates_dir():
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _list_template_files() -> list[Path]:
    _ensure_templates_dir()
    return sorted(TEMPLATES_DIR.glob("*.json"))


def _load_template(name: str) -> dict:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_template(name: str, data: dict):
    _ensure_templates_dir()
    path = TEMPLATES_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("")
async def list_workflows():
    workflows = []
    for path in _list_files():
        try:
            wf = _load(path.stem)
            workflows.append(
                {
                    "id": wf.get("id", path.stem),
                    "name": wf.get("name", path.stem),
                    "node_count": len(wf.get("nodes", [])),
                    "created_at": wf.get("created_at", ""),
                    "updated_at": wf.get("updated_at", ""),
                    "draft": bool(wf.get("draft", False)),
                    "validation_errors": wf.get("validation_errors", []),
                }
            )
        except Exception as e:
            logger.warning("Failed to load workflow %s: %s", path, e)
    return workflows


@router.get("/{wf_id}")
async def get_workflow(wf_id: str):
    return _load(wf_id)


@router.post("")
async def create_workflow(body: WorkflowCreate):
    wf_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    normalized = _normalize_workflow({"name": body.name, "nodes": body.nodes, "edges": body.edges})
    data = {
        "id": wf_id,
        "name": normalized["name"],
        "nodes": normalized["nodes"],
        "edges": normalized["edges"],
        "draft": body.draft,
        "validation_errors": body.validation_errors,
        "goal": body.goal,
        "plan_text": body.plan_text,
        "created_at": now,
        "updated_at": now,
    }
    errors = _validate_workflow(data)
    if errors:
        data["draft"] = True
        data["validation_errors"] = errors
    _save(wf_id, data)
    return data


@router.put("/{wf_id}")
async def update_workflow(wf_id: str, body: WorkflowUpdate):
    data = _load(wf_id)
    raw = {
        "name": body.name if body.name is not None else data.get("name", "workflow"),
        "nodes": body.nodes if body.nodes is not None else data.get("nodes", []),
        "edges": body.edges if body.edges is not None else data.get("edges", []),
    }
    normalized = _normalize_workflow(raw)
    data.update(normalized)
    if body.goal is not None:
        data["goal"] = body.goal
    if body.plan_text is not None:
        data["plan_text"] = body.plan_text
    errors = _validate_workflow(data)
    if body.validation_errors:
        for err in body.validation_errors:
            if err not in errors:
                errors.append(err)
    data["validation_errors"] = errors
    data["draft"] = bool(errors) if body.draft is None else bool(body.draft or errors)
    data["updated_at"] = datetime.now().isoformat()
    _save(wf_id, data)
    return data


@router.delete("/{wf_id}")
async def delete_workflow(wf_id: str):
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{wf_id}' not found")
    path.unlink()
    return {"status": "deleted", "id": wf_id}


@router.post("/{wf_id}/template")
async def save_as_template(wf_id: str, body: TemplateCreate):
    wf = _load(wf_id)
    template_data = {
        "name": body.template_name,
        "source_workflow_id": wf_id,
        "workflow_name": wf.get("name", ""),
        "nodes": wf.get("nodes", []),
        "edges": wf.get("edges", []),
        "draft": wf.get("draft", False),
        "validation_errors": wf.get("validation_errors", []),
        "goal": wf.get("goal"),
        "plan_text": wf.get("plan_text"),
        "created_at": datetime.now().isoformat(),
    }
    _save_template(body.template_name, template_data)
    return {"status": "saved", "template_name": body.template_name}


@router.post("/{wf_id}/duplicate")
async def duplicate_workflow(wf_id: str):
    wf = _load(wf_id)
    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data = {
        "id": new_id,
        "name": f"{wf.get('name', 'workflow')} (副本)",
        "nodes": wf.get("nodes", []),
        "edges": wf.get("edges", []),
        "draft": wf.get("draft", False),
        "validation_errors": wf.get("validation_errors", []),
        "goal": wf.get("goal"),
        "plan_text": wf.get("plan_text"),
        "created_at": now,
        "updated_at": now,
    }
    _save(new_id, data)
    return {"id": new_id, "name": data["name"]}


@router.get("/{wf_id}/export")
async def export_workflow(wf_id: str):
    wf = _load(wf_id)
    return {
        "name": wf.get("name", ""),
        "nodes": wf.get("nodes", []),
        "edges": wf.get("edges", []),
        "draft": wf.get("draft", False),
        "validation_errors": wf.get("validation_errors", []),
        "goal": wf.get("goal"),
        "plan_text": wf.get("plan_text"),
    }


@router.post("/import")
async def import_workflow(body: WorkflowImport):
    wf_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    normalized = _normalize_workflow(
        {"name": body.name or "导入的工作流", "nodes": body.nodes, "edges": body.edges}
    )
    data = {
        "id": wf_id,
        "name": normalized["name"],
        "nodes": normalized["nodes"],
        "edges": normalized["edges"],
        "created_at": now,
        "updated_at": now,
    }
    errors = _validate_workflow(data)
    data["draft"] = bool(errors)
    data["validation_errors"] = errors
    _save(wf_id, data)
    return {"id": wf_id, "name": data["name"]}


@router.post("/ai/preview")
async def preview_ai_workflow(body: WorkflowAIPreviewRequest):
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="请输入工作流目标")

    model_cfg = _load_llm_model(body.model_name)
    try:
        from server.ai.generation_agent import run_generation_agent

        result = run_generation_agent(
            model_cfg=model_cfg,
            task_prompt=_build_workflow_prompt(goal),
            system_prompt="You are a VideoFactory workflow planning and graph-generation agent. Output valid JSON only.",
            extract_artifact=_extract_workflow_artifact,
            validate_artifact=_validate_workflow_artifact,
            max_steps=4,
            temperature=0.2,
        )
        if not isinstance(result.artifact, dict):
            raise HTTPException(
                status_code=502,
                detail="AI workflow generation did not return valid JSON: "
                + "; ".join(result.validation_errors),
            )
        raw = result.artifact
        agent_attempts = result.attempts
        agent_validation_errors = result.validation_errors
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM 返回的 JSON 无法解析: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI workflow generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"AI 工作流生成失败: {e}")

    pre_errors = _prevalidate_workflow_payload(raw)
    workflow = _normalize_workflow(raw)
    plan_text = str(raw.get("plan_text") or "").strip()
    if not plan_text:
        plan_text = "已根据目标生成节点图草案，请检查节点和连线后确认。"

    errors = pre_errors + [err for err in _validate_workflow(workflow) if err not in pre_errors]
    return {
        "status": "preview",
        "plan_text": plan_text,
        "workflow": workflow,
        "validation_errors": errors,
        "is_valid": not errors,
        "agent_attempts": agent_attempts,
        "agent_validation_errors": agent_validation_errors,
    }


@router.post("/ai/confirm")
async def confirm_ai_workflow(body: WorkflowAIConfirmRequest):
    pre_errors = _prevalidate_workflow_payload(body.workflow)
    workflow = _normalize_workflow(body.workflow)
    errors = pre_errors + [err for err in _validate_workflow(workflow) if err not in pre_errors]
    for err in body.validation_errors or []:
        if err not in errors:
            errors.append(err)

    wf_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data = {
        "id": wf_id,
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "edges": workflow["edges"],
        "draft": bool(errors),
        "validation_errors": errors,
        "goal": body.goal,
        "plan_text": body.plan_text,
        "created_at": now,
        "updated_at": now,
    }
    _save(wf_id, data)
    return {"id": wf_id, "name": data["name"], "draft": data["draft"], "validation_errors": errors}


@templates_router.get("")
async def list_templates():
    templates = []
    for path in _list_template_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                tpl = json.load(f)
            templates.append(
                {
                    "name": tpl.get("name", path.stem),
                    "workflow_name": tpl.get("workflow_name", ""),
                    "node_count": len(tpl.get("nodes", [])),
                    "created_at": tpl.get("created_at", ""),
                }
            )
        except Exception as e:
            logger.warning("Failed to load template %s: %s", path, e)
    return templates


@templates_router.post("/{name}/create")
async def create_from_template(name: str):
    tpl = _load_template(name)
    wf_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    normalized = _normalize_workflow(
        {"name": tpl.get("workflow_name", name), "nodes": tpl.get("nodes", []), "edges": tpl.get("edges", [])}
    )
    data = {
        "id": wf_id,
        "name": normalized["name"],
        "nodes": normalized["nodes"],
        "edges": normalized["edges"],
        "draft": tpl.get("draft", False),
        "validation_errors": tpl.get("validation_errors", []),
        "goal": tpl.get("goal"),
        "plan_text": tpl.get("plan_text"),
        "created_at": now,
        "updated_at": now,
    }
    _save(wf_id, data)
    return {"id": wf_id, "name": data["name"]}


@templates_router.delete("/{name}")
async def delete_template(name: str):
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    path.unlink()
    return {"status": "deleted", "name": name}
