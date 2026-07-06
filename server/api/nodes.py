"""
节点定义 API — 供前端获取节点库

REST 路由：
- GET /api/nodes           获取所有节点类型定义
- GET /api/nodes/categories  按分类获取
"""
from fastapi import APIRouter

from server.nodes.registry import get_all_definitions, get_definitions_by_category

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("")
async def list_node_definitions():
    """获取所有节点类型定义（供前端节点库渲染）"""
    return get_all_definitions()


@router.get("/categories")
async def list_node_categories():
    """按分类获取节点定义"""
    return get_definitions_by_category()
