"""
运行控制 API + WebSocket 实时推送

REST:
- POST   /api/run            启动执行
- POST   /api/run/stop       停止执行
- GET    /api/run/status     获取执行状态

WebSocket:
- WS     /ws/run             实时状态推送
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


class RunRequest(BaseModel):
    workflow_id: str
    date: Optional[str] = None  # 默认今天
    force_no_cache: bool = False  # 强制重跑，忽略缓存


# WebSocket 连接池
_ws_clients: list[WebSocket] = []


async def _broadcast(event_type: str, data: dict):
    """广播事件给所有 WebSocket 客户端"""
    message = json.dumps({"type": event_type, "data": data, "timestamp": datetime.now().isoformat()}, ensure_ascii=False)
    disconnected = []
    for ws in _ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_clients.remove(ws)


@router.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    """WebSocket 连接：实时推送执行状态"""
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info(f"WebSocket 客户端连接 (总: {len(_ws_clients)})")
    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
        logger.info(f"WebSocket 客户端断开 (剩余: {len(_ws_clients)})")


@router.post("/api/run")
async def start_run(body: RunRequest):
    """启动工作流执行"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from server.engine.executor import executor
    from server.api.workflows import _load as load_workflow
    from config_loader import load_config

    # 加载工作流
    workflow = load_workflow(body.workflow_id)
    config = load_config()

    # 日期
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))

    # 设置 WebSocket 回调
    executor.set_event_callback(_broadcast)

    # 后台执行
    async def _run():
        try:
            await executor.execute_workflow(workflow, config, date, data_root, force_no_cache=body.force_no_cache)
        except Exception as e:
            logger.error(f"工作流执行异常: {e}", exc_info=True)
            await _broadcast("run_error", {"error": str(e)})

    asyncio.create_task(_run())

    return {
        "status": "started",
        "workflow_id": body.workflow_id,
        "date": date,
    }


@router.post("/api/run/stop")
async def stop_run():
    """停止当前执行"""
    from server.engine.executor import executor
    logger.info(f"停止请求: current_run={executor.current_run is not None}, stop_requested={executor._stop_requested}")
    if executor._current_ctx:
        logger.info(f"ctx id={id(executor._current_ctx)}, ctx._stop_requested={getattr(executor._current_ctx, '_stop_requested', 'NOT_SET')}")
    else:
        logger.info("ctx=None")
    executor.stop()
    logger.info(f"停止后: stop_requested={executor._stop_requested}")
    if executor._current_ctx:
        logger.info(f"ctx._stop_requested after stop={getattr(executor._current_ctx, '_stop_requested', 'NOT_SET')}")
    # 推送停止事件到前端
    await _broadcast("log", {
        "node_id": "",
        "level": "WARNING",
        "message": "用户请求停止执行...",
        "logger": "system",
        "timestamp": __import__("time").time(),
    })
    return {"status": "stop_requested"}


@router.get("/api/run/status")
async def get_run_status():
    """获取当前执行状态"""
    from server.engine.executor import executor
    if executor.current_run:
        return executor.current_run.to_dict()
    return {"status": "idle"}


@router.get("/api/runs/history/{workflow_id}")
async def get_run_history(workflow_id: str):
    """获取某个工作流的运行历史"""
    from server.engine.executor import executor
    return {"runs": executor.get_run_history(workflow_id)}


@router.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    """获取某次运行的详细状态 + 日志"""
    from server.engine.executor import executor
    data = executor.get_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return data


class RunNodeRequest(BaseModel):
    workflow_id: str
    node_id: str
    date: Optional[str] = None


@router.post("/api/run/node")
async def run_single_node(body: RunNodeRequest):
    """手动触发单个节点执行"""
    from server.engine.executor import executor
    from server.api.workflows import _load as load_workflow
    from config_loader import load_config

    workflow = load_workflow(body.workflow_id)
    config = load_config()
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    executor.set_event_callback(_broadcast)

    async def _run():
        try:
            await executor.run_single_node(workflow, config, body.node_id, date, data_root)
        except Exception as e:
            logger.error(f"手动触发失败: {e}", exc_info=True)
            await _broadcast("run_error", {"error": str(e)})

    asyncio.create_task(_run())

    return {"status": "started", "node_id": body.node_id, "workflow_id": body.workflow_id}


class ClearCacheRequest(BaseModel):
    date: Optional[str] = None  # 默认今天


@router.post("/api/cache/clear")
async def clear_cache(body: ClearCacheRequest):
    """清除指定日期的全部产出缓存"""
    import shutil
    from config_loader import load_config

    config = load_config()
    date = body.date or datetime.now().strftime("%Y-%m-%d")
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    date_dir = data_root / date

    if not date_dir.exists():
        return {"status": "ok", "message": f"目录不存在: {date_dir}", "cleared": []}

    # 清除所有产出目录（保留 collected 和 logs）
    keep_dirs = {"logs"}  # 保留日志
    cleared = []
    for sub in date_dir.iterdir():
        if sub.is_dir() and sub.name not in keep_dirs:
            shutil.rmtree(sub)
            cleared.append(sub.name)
            logger.info(f"缓存清除: {sub}")

    return {"status": "ok", "date": date, "cleared": cleared}
