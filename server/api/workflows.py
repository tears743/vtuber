"""
工作流 CRUD API

REST 路由：
- GET    /api/workflows          工作流列表
- POST   /api/workflows          保存/新建工作流
- GET    /api/workflows/{id}     获取单个
- DELETE /api/workflows/{id}     删除
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "workflows"


class WorkflowCreate(BaseModel):
    name: str
    nodes: list = []
    edges: list = []


class WorkflowUpdate(BaseModel):
    name: str = None
    nodes: list = None
    edges: list = None


def _ensure_dir():
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)


def _list_files() -> list[Path]:
    _ensure_dir()
    return sorted(WORKFLOWS_DIR.glob("*.json"))


def _load(wf_id: str) -> dict:
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{wf_id}' not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(wf_id: str, data: dict):
    _ensure_dir()
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("")
async def list_workflows():
    """获取所有工作流列表"""
    workflows = []
    for path in _list_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                wf = json.load(f)
            workflows.append({
                "id": wf.get("id", path.stem),
                "name": wf.get("name", path.stem),
                "node_count": len(wf.get("nodes", [])),
                "created_at": wf.get("created_at", ""),
                "updated_at": wf.get("updated_at", ""),
            })
        except Exception as e:
            logger.warning(f"加载工作流失败 {path}: {e}")
    return workflows


@router.get("/{wf_id}")
async def get_workflow(wf_id: str):
    """获取单个工作流"""
    return _load(wf_id)


@router.post("")
async def create_workflow(body: WorkflowCreate):
    """新建工作流"""
    wf_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data = {
        "id": wf_id,
        "name": body.name,
        "nodes": body.nodes,
        "edges": body.edges,
        "created_at": now,
        "updated_at": now,
    }
    _save(wf_id, data)
    return data


@router.put("/{wf_id}")
async def update_workflow(wf_id: str, body: WorkflowUpdate):
    """更新工作流"""
    data = _load(wf_id)
    if body.name is not None:
        data["name"] = body.name
    if body.nodes is not None:
        data["nodes"] = body.nodes
    if body.edges is not None:
        data["edges"] = body.edges
    data["updated_at"] = datetime.now().isoformat()
    _save(wf_id, data)
    return data


@router.delete("/{wf_id}")
async def delete_workflow(wf_id: str):
    """删除工作流"""
    path = WORKFLOWS_DIR / f"{wf_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{wf_id}' not found")
    path.unlink()
    return {"status": "deleted", "id": wf_id}
