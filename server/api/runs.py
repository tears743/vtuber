"""Run control API and realtime run WebSocket."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


class RunRequest(BaseModel):
    workflow_id: str
    resume_from_node: Optional[str] = None
    date: Optional[str] = None
    force_no_cache: bool = False


class RunNodeRequest(BaseModel):
    workflow_id: str
    node_id: str
    date: Optional[str] = None


class ClearCacheRequest(BaseModel):
    date: Optional[str] = None


class ClearNodeCacheRequest(BaseModel):
    workflow_id: str
    node_id: str
    date: Optional[str] = None


_ws_clients: list[WebSocket] = []


async def _broadcast(event_type: str, data: dict):
    message = json.dumps(
        {"type": event_type, "data": data, "timestamp": datetime.now().isoformat()},
        ensure_ascii=False,
    )
    disconnected = []
    for ws in _ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


def _load_runtime(workflow_id: str):
    from config_loader import load_config
    from server.api.workflows import _load as load_workflow

    workflow = load_workflow(workflow_id)
    if workflow.get("draft") and workflow.get("validation_errors"):
        raise HTTPException(
            status_code=400,
            detail="该工作流仍是草稿且存在校验问题，请先修复节点或连线后再运行。",
        )
    config = load_config()
    return workflow, config


@router.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info("WebSocket client connected, total=%s", len(_ws_clients))
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        logger.info("WebSocket client disconnected, total=%s", len(_ws_clients))


@router.post("/api/run")
async def start_run(body: RunRequest):
    from server.engine.executor import executor

    workflow, config = _load_runtime(body.workflow_id)
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    executor.set_event_callback(_broadcast)

    async def _run():
        try:
            await executor.execute_workflow(
                workflow,
                config,
                date,
                data_root,
                force_no_cache=body.force_no_cache,
                resume_from_node=body.resume_from_node,
            )
        except Exception as e:
            logger.error("Workflow run failed: %s", e, exc_info=True)
            await _broadcast("run_error", {"error": str(e)})

    asyncio.create_task(_run())

    return {
        "status": "started",
        "workflow_id": body.workflow_id,
        "date": date,
        "resume_from_node": body.resume_from_node,
    }


@router.post("/api/run/stop")
async def stop_run():
    from server.engine.executor import executor

    logger.info(
        "Stop requested: current_run=%s, stop_requested=%s",
        executor.current_run is not None,
        executor._stop_requested,
    )
    result = executor.stop()
    await _broadcast(
        "log",
        {
            "node_id": "",
            "level": "WARNING",
            "message": "用户请求停止执行...",
            "logger": "system",
            "timestamp": __import__("time").time(),
        },
    )
    if result.get("stopped"):
        await _broadcast("run_stopped", {"run_id": result.get("run_id"), "status": "stopped"})
    return {"status": "stop_requested", **result}


@router.get("/api/run/status")
async def get_run_status():
    from server.engine.executor import executor

    if executor.current_run:
        return executor.current_run.to_dict()
    return {"status": "idle"}


@router.get("/api/runs/history/{workflow_id}")
async def get_run_history(workflow_id: str):
    from server.engine.executor import executor

    return {"runs": executor.get_run_history(workflow_id)}


@router.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    from server.engine.executor import executor

    data = executor.get_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return data


@router.post("/api/run/node")
async def run_single_node(body: RunNodeRequest):
    from server.engine.executor import executor

    workflow, config = _load_runtime(body.workflow_id)
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    executor.set_event_callback(_broadcast)

    async def _run():
        try:
            await executor.run_single_node(workflow, config, body.node_id, date, data_root)
        except Exception as e:
            logger.error("Manual node run failed: %s", e, exc_info=True)
            await _broadcast("run_error", {"error": str(e)})

    asyncio.create_task(_run())

    return {"status": "started", "node_id": body.node_id, "workflow_id": body.workflow_id}


@router.post("/api/cache/clear")
async def clear_cache(body: ClearCacheRequest):
    import shutil
    from config_loader import load_config

    config = load_config()
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    date_dir = data_root / date

    if not date_dir.exists():
        return {"status": "ok", "message": f"Directory does not exist: {date_dir}", "cleared": []}

    keep_dirs = {"logs"}
    cleared = []
    for sub in date_dir.iterdir():
        if sub.is_dir() and sub.name not in keep_dirs:
            shutil.rmtree(sub)
            cleared.append(sub.name)
            logger.info("Cache cleared: %s", sub)

    return {"status": "ok", "date": date, "cleared": cleared}


@router.post("/api/cache/node/clear")
async def clear_node_cache(body: ClearNodeCacheRequest):
    from config_loader import load_config
    from server.engine.node_cache import NodeCacheManager

    config = load_config()
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    manager = NodeCacheManager(data_root, date, body.workflow_id)
    cleared = manager.clear_node(body.node_id)
    return {
        "status": "ok",
        "date": date,
        "workflow_id": body.workflow_id,
        "node_id": body.node_id,
        "cleared": cleared,
        "path": str(manager.node_dir(body.node_id)),
    }
