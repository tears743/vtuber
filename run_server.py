"""
VideoFactory Visual Workflow Server

FastAPI 主入口，同时 serve：
1. REST API（工作流/节点/设置/运行）
2. WebSocket（实时状态推送）
3. 前端静态文件（Vite 构建产物）

启动命令: python server.py
"""
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")

# ── 创建 FastAPI 应用 ──
app = FastAPI(
    title="VideoFactory Workflow Server",
    description="可视化节点编排系统后端",
    version="0.1.0",
)

# CORS（开发阶段允许 Vite dev server）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册所有节点（自动发现 + 社区节点包）──
from server.nodes.loader import pack_loader

# 1. 加载内置节点（server/nodes/builtin/ 下的 .py 文件）
# 2. 加载社区节点包（nodes/community/ 下的 vf-node.yaml）
# 3. 加载 pip 安装的节点包（entry_points）
# 同时兼容旧的硬编码 import（旧节点仍从 server/nodes/ 直接导入）
# 旧节点文件不在 builtin/ 目录下，需要显式 import
import server.nodes.collect  # noqa: F401
import server.nodes.download  # noqa: F401
import server.nodes.recognize  # noqa: F401
import server.nodes.transcribe  # noqa: F401
import server.nodes.director  # noqa: F401
import server.nodes.tts  # noqa: F401
import server.nodes.align  # noqa: F401
import server.nodes.overlay  # noqa: F401
import server.nodes.visual  # noqa: F401
import server.nodes.live2d  # noqa: F401
import server.nodes.compose  # noqa: F401

# 加载 builtin + community + pip 节点
pack_loader.load_all()

from server.nodes.registry import list_types
logger.info(f"已注册 {len(list_types())} 个节点类型: {list_types()}")

# ── 注册 API 路由 ──
from server.api.workflows import router as workflows_router
from server.api.nodes import router as nodes_router
from server.api.settings import router as settings_router
from server.api.runs import router as runs_router
from server.api.scripts import router as scripts_router
from server.api.node_packs import router as node_packs_router

app.include_router(workflows_router)
app.include_router(nodes_router)
app.include_router(settings_router)
app.include_router(runs_router)
app.include_router(scripts_router)
app.include_router(node_packs_router)


# ── 健康检查 ──
@app.get("/api/health")
async def health():
    return {"status": "ok", "nodes_registered": len(list_types())}


# ── 前端静态文件 (production build) ──
FRONTEND_DIR = PROJECT_ROOT / "web" / "dist"
if FRONTEND_DIR.exists():
    from fastapi.responses import FileResponse

    # SPA fallback: 非 API/WS 路径返回 index.html
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # 如果请求的是真实存在的静态文件（js/css/图片等），直接返回
        file_path = FRONTEND_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        # 否则返回 index.html 让前端路由处理
        return FileResponse(FRONTEND_DIR / "index.html")

    # 静态资源目录（CSS/JS/fonts 等）
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
    logger.info(f"Serving frontend from: {FRONTEND_DIR}")
else:
    logger.info("前端未构建，跳过静态文件挂载 (开发模式用 Vite dev server)")


# ── 生成默认工作流 ──
def _ensure_default_workflow():
    """首次启动时生成默认工作流"""
    workflows_dir = PROJECT_ROOT / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    default_path = workflows_dir / "default.json"
    if default_path.exists():
        return

    import json
    from datetime import datetime

    default_workflow = {
        "id": "default",
        "name": "VideoFactory 默认管线",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "nodes": [
            {"id": "collect_1", "type": "collect", "position": {"x": 100, "y": 300}, "config": {}},
            {"id": "download_1", "type": "download", "position": {"x": 400, "y": 200}, "config": {}},
            {"id": "recognize_1", "type": "recognize", "position": {"x": 700, "y": 100}, "config": {}},
            {"id": "transcribe_1", "type": "transcribe", "position": {"x": 700, "y": 300}, "config": {}},
            {"id": "director_1", "type": "director", "position": {"x": 1000, "y": 300}, "config": {}},
            {"id": "tts_1", "type": "tts", "position": {"x": 1300, "y": 300}, "config": {}},
            {"id": "align_1", "type": "align", "position": {"x": 1600, "y": 300}, "config": {}},
            {"id": "overlay_1", "type": "overlay", "position": {"x": 1900, "y": 150}, "config": {}},
            {"id": "visual_1", "type": "visual", "position": {"x": 1900, "y": 300}, "config": {}},
            {"id": "live2d_1", "type": "live2d", "position": {"x": 1900, "y": 450}, "config": {}},
            {"id": "compose_1", "type": "compose", "position": {"x": 2200, "y": 300}, "config": {}},
        ],
        "edges": [
            {"source": "collect_1", "target": "download_1"},
            {"source": "download_1", "target": "recognize_1"},
            {"source": "download_1", "target": "transcribe_1"},
            {"source": "collect_1", "target": "director_1"},
            {"source": "recognize_1", "target": "director_1"},
            {"source": "transcribe_1", "target": "director_1"},
            {"source": "director_1", "target": "tts_1"},
            {"source": "tts_1", "target": "align_1"},
            {"source": "align_1", "target": "overlay_1"},
            {"source": "align_1", "target": "visual_1"},
            {"source": "align_1", "target": "live2d_1"},
            {"source": "overlay_1", "target": "compose_1"},
            {"source": "visual_1", "target": "compose_1"},
            {"source": "live2d_1", "target": "compose_1"},
            {"source": "download_1", "target": "visual_1"},
            {"source": "download_1", "target": "compose_1"},
            {"source": "tts_1", "target": "live2d_1"},
        ],
    }

    with open(default_path, "w", encoding="utf-8") as f:
        json.dump(default_workflow, f, ensure_ascii=False, indent=2)
    logger.info("已生成默认工作流: default.json")


@app.on_event("startup")
async def startup():
    _ensure_default_workflow()
    logger.info("VideoFactory Workflow Server 启动完成")


if __name__ == "__main__":
    uvicorn.run(
        "run_server:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT / "server")],
    )
