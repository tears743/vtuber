"""
节点注册表

自动发现并注册所有 BaseNode 子类，提供：
- 按 type 获取节点类
- 获取所有节点类型定义（供前端节点库）
- 按 category 分组
"""
import logging
from typing import Type

from server.nodes.base import BaseNode

logger = logging.getLogger(__name__)

# 全局注册表
_registry: dict[str, Type[BaseNode]] = {}


def register(node_cls: Type[BaseNode]) -> Type[BaseNode]:
    """装饰器：注册节点类"""
    if not node_cls.type:
        raise ValueError(f"Node class {node_cls.__name__} must define 'type'")
    if node_cls.type in _registry:
        logger.warning(f"Node type '{node_cls.type}' already registered, overwriting")
    _registry[node_cls.type] = node_cls
    logger.info(f"Registered node: {node_cls.type} ({node_cls.label})")
    return node_cls


def get_node_class(node_type: str) -> Type[BaseNode]:
    """根据 type 获取节点类"""
    if node_type not in _registry:
        raise KeyError(f"Unknown node type: '{node_type}'. Available: {list(_registry.keys())}")
    return _registry[node_type]


def get_all_definitions() -> list[dict]:
    """获取所有已注册节点的定义（供前端渲染节点库）"""
    return [cls.get_definition() for cls in _registry.values()]


def get_definitions_by_category() -> dict[str, list[dict]]:
    """按 category 分组返回节点定义"""
    categories = {}
    for cls in _registry.values():
        cat = cls.category or "其他"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(cls.get_definition())
    return categories


def create_node(node_type: str, node_id: str, config: dict = None) -> BaseNode:
    """工厂函数：根据 type 和 config 创建节点实例"""
    cls = get_node_class(node_type)
    return cls(node_id=node_id, config=config)


def list_types() -> list[str]:
    """列出所有已注册的节点类型"""
    return list(_registry.keys())
