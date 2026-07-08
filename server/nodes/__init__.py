"""
server.nodes — 节点体系包

导入此包时自动发现并注册所有内置节点。
"""
# 导出核心类和函数
from server.nodes.base import BaseNode, NodeInput, NodeOutput, TriggerNode, ListenerNode
from server.nodes.registry import (
    node, register, create_node, get_node_class,
    get_all_definitions, get_definitions_by_category,
    list_types, list_aliases,
    discover_nodes, discover_node_packs,
    get_node_packs, register_node_pack,
)
