"""
节点定义 API — 供前端获取节点库

REST 路由：
- GET /api/nodes           获取所有节点类型定义 + 全局配置 + 节点包列表
- GET /api/nodes/categories  按分类获取
"""
import logging

from fastapi import APIRouter

from server.nodes.registry import get_all_definitions, get_definitions_by_category, get_node_packs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("")
async def list_node_definitions():
    """获取所有节点类型定义（供前端节点库渲染）

    返回:
        nodes: 节点定义列表（含 inputs/outputs/config_schema/icon/color/version）
        node_packs: 节点包列表（含版本/来源）
        global_config: 全局配置（模型池等，供 type=model 的字段渲染下拉框）
    """
    # 加载全局配置中的模型列表
    model_names = []
    try:
        from config_loader import load_config
        config = load_config()
        models = config.get("models", {})
        model_names = list(models.keys())
    except Exception:
        pass

    return {
        "nodes": get_all_definitions(),
        "node_packs": get_node_packs(),
        "global_config": {
            "models": model_names,
        },
    }


@router.get("/categories")
async def list_node_categories():
    """按分类获取节点定义"""
    return get_definitions_by_category()
