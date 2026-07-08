"""
节点注册表

自动发现并注册所有 BaseNode 子类，提供：
- @node 装饰器注册（新方式，支持版本/图标等元信息）
- @register 装饰器（旧方式，向后兼容）
- __init_subclass__ 自动注册（无需装饰器）
- 按 type 获取节点类
- 获取所有节点类型定义（供前端节点库）
- 按 category 分组
- 节点别名支持（重命名迁移）
"""
import logging
from typing import Type, Optional

from server.nodes.base import BaseNode

logger = logging.getLogger(__name__)

# 全局注册表
_registry: dict[str, Type[BaseNode]] = {}

# 节点别名（旧 type 名 → 新 type 名）
_type_aliases: dict[str, str] = {}

# 节点包信息
_node_packs: dict[str, dict] = {}


# ═══════════════════════════════════════════════════════
# 注册函数
# ═══════════════════════════════════════════════════════

def node(
    node_type: str,
    version: str = "1.0.0",
    icon: str = None,
    color: str = None,
    author: str = None,
    deprecated: bool = False,
    aliases: list[str] = None,
    **kwargs,
):
    """新装饰器：注册节点类，支持元信息

    Usage:
        @node("collect", version="1.0.0", icon="🕷️", color="#4CAF50")
        class CollectNode(BaseNode):
            ...
    """
    def decorator(cls: Type[BaseNode]) -> Type[BaseNode]:
        cls.type = node_type
        cls.version = version
        if icon:
            cls.icon = icon
        if color:
            cls.color = color
        if author:
            cls.author = author
        if deprecated:
            cls.deprecated = deprecated

        # 注册额外属性
        for k, v in kwargs.items():
            setattr(cls, k, v)

        _register_node(cls)

        # 注册别名
        if aliases:
            for alias in aliases:
                _type_aliases[alias] = node_type

        return cls

    return decorator


def register(node_cls: Type[BaseNode]) -> Type[BaseNode]:
    """旧装饰器：注册节点类（向后兼容）

    Usage:
        @register
        class CollectNode(BaseNode):
            type = "collect"
            ...
    """
    _register_node(node_cls)
    return node_cls


def _register_node(node_cls: Type[BaseNode]) -> None:
    """内部注册逻辑"""
    if not node_cls.type:
        raise ValueError(f"Node class {node_cls.__name__} must define 'type'")

    if node_cls.type in _registry:
        existing = _registry[node_cls.type]
        logger.warning(
            f"Node type '{node_cls.type}' already registered "
            f"({existing.__name__} → {node_cls.__name__}), overwriting"
        )

    _registry[node_cls.type] = node_cls
    logger.info(f"Registered node: {node_cls.type} v{node_cls.version} ({node_cls.label})")


# ═══════════════════════════════════════════════════════
# 查询函数
# ═══════════════════════════════════════════════════════

def get_node_class(node_type: str) -> Type[BaseNode]:
    """根据 type 获取节点类（支持别名）"""
    # 检查别名
    actual_type = _type_aliases.get(node_type, node_type)

    if actual_type not in _registry:
        raise KeyError(
            f"Unknown node type: '{node_type}'. "
            f"Available: {list(_registry.keys())}"
        )

    return _registry[actual_type]


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


def get_node_packs() -> list[dict]:
    """获取所有已注册的节点包信息"""
    return list(_node_packs.values())


def register_node_pack(name: str, info: dict) -> None:
    """注册节点包信息"""
    _node_packs[name] = info


def create_node(node_type: str, node_id: str, config: Optional[dict] = None) -> BaseNode:
    """工厂函数：根据 type 和 config 创建节点实例"""
    cls = get_node_class(node_type)

    # 配置迁移（如果 config 中有 version 信息）
    if config and "_version" in config:
        old_version = config.pop("_version")
        if old_version != cls.version:
            config = cls.migrate_config(old_version, config)

    return cls(node_id=node_id, config=config)


def list_types() -> list[str]:
    """列出所有已注册的节点类型"""
    return list(_registry.keys())


def list_aliases() -> dict[str, str]:
    """列出所有别名映射"""
    return dict(_type_aliases)


# ═══════════════════════════════════════════════════════
# 自动发现
# ═══════════════════════════════════════════════════════

def discover_nodes(builtin_dir: str = None) -> int:
    """自动发现并导入 builtin 目录下的所有节点模块

    扫描 server/nodes/builtin/ 目录下的所有 .py 文件（排除 __init__），
    导入它们以触发 @node/@register 装饰器。

    Args:
        builtin_dir: 内置节点目录路径（默认 server/nodes/builtin/）

    Returns:
        导入的模块数量
    """
    import importlib
    import pkgutil
    from pathlib import Path

    if builtin_dir is None:
        builtin_dir = Path(__file__).parent / "builtin"
    else:
        builtin_dir = Path(builtin_dir)

    if not builtin_dir.exists():
        return 0

    count = 0
    for finder, name, is_pkg in pkgutil.iter_modules([str(builtin_dir)]):
        if name.startswith("_"):
            continue
        try:
            importlib.import_module(f"server.nodes.builtin.{name}")
            count += 1
            logger.debug(f"Discovered node module: builtin.{name}")
        except Exception as e:
            logger.error(f"Failed to import node module builtin.{name}: {e}")

    logger.info(f"Auto-discovered {count} node modules from {builtin_dir}")
    return count


def discover_node_packs(packs_dir: str = None) -> int:
    """自动发现并导入 community 节点包

    扫描 nodes/community/ 目录下的所有子目录，
    每个子目录包含 vf-node.yaml 清单文件。

    Args:
        packs_dir: 节点包目录路径（默认 nodes/community/）

    Returns:
        导入的节点包数量
    """
    import importlib
    import sys
    import yaml
    from pathlib import Path

    if packs_dir is None:
        # 项目根目录下的 nodes/community/
        project_root = Path(__file__).parent.parent.parent
        packs_dir = project_root / "nodes" / "community"
    else:
        packs_dir = Path(packs_dir)

    if not packs_dir.exists():
        return 0

    count = 0
    for pack_dir in packs_dir.iterdir():
        if not pack_dir.is_dir():
            continue

        manifest = pack_dir / "vf-node.yaml"
        if not manifest.exists():
            continue

        try:
            # 解析清单
            with open(manifest, "r", encoding="utf-8") as f:
                info = yaml.safe_load(f)

            pack_name = info.get("name", pack_dir.name)

            # 注册节点包信息
            register_node_pack(pack_name, {
                "name": pack_name,
                "version": info.get("version", "0.0.0"),
                "author": info.get("author", ""),
                "description": info.get("description", ""),
                "homepage": info.get("homepage", ""),
                "license": info.get("license", ""),
                "path": str(pack_dir),
                "source": "local",
                "enabled": True,
            })

            # 导入节点模块
            nodes_list = info.get("nodes", [])
            for node_entry in nodes_list:
                node_path = node_entry.get("path", "")
                if not node_path:
                    continue

                # 将包目录加入 sys.path
                if str(pack_dir) not in sys.path:
                    sys.path.insert(0, str(pack_dir))

                # 导入模块（去掉 .py 后缀）
                module_name = node_path.replace("/", ".").replace(".py", "")
                try:
                    importlib.import_module(module_name)
                    count += 1
                    logger.debug(f"Discovered node from pack {pack_name}: {module_name}")
                except Exception as e:
                    logger.error(f"Failed to import node module {module_name} from pack {pack_name}: {e}")

        except Exception as e:
            logger.error(f"Failed to load node pack {pack_dir.name}: {e}")

    logger.info(f"Auto-discovered {count} nodes from {len(list(packs_dir.iterdir()))} packs in {packs_dir}")
    return count
