"""
节点包加载器

支持三种安装方式：
1. 本地目录：vf-node.yaml 所在目录
2. Git URL：git clone 到 nodes/community/ 目录
3. pip 包：通过 entry_points 机制发现

加载流程：
1. discover_nodes() — 扫描 server/nodes/builtin/ 内置节点
2. discover_node_packs() — 扫描 nodes/community/ 社区节点包
3. discover_pip_nodes() — 扫描 pip 安装的节点包
"""
import importlib
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from server.nodes.registry import register_node_pack

logger = logging.getLogger(__name__)


@dataclass
class NodePackInfo:
    """节点包信息"""
    name: str
    version: str
    author: str = ""
    description: str = ""
    homepage: str = ""
    license: str = ""
    path: str = ""
    source: str = "local"  # local | git | pip
    enabled: bool = True
    git_url: str = ""
    pip_name: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "homepage": self.homepage,
            "license": self.license,
            "path": self.path,
            "source": self.source,
            "enabled": self.enabled,
            "git_url": self.git_url,
            "pip_name": self.pip_name,
        }


class NodePackLoader:
    """节点包加载器 — 管理 builtin/community/pip 三种来源的节点包"""

    # 节点包根目录
    BUILTIN_DIR = Path(__file__).parent / "builtin"
    COMMUNITY_DIR = Path(__file__).parent.parent.parent / "nodes" / "community"

    def __init__(self):
        self._packs: dict[str, NodePackInfo] = {}
        self._builtin_registered = False

    def load_all(self) -> int:
        """加载所有节点包（builtin + community + pip）

        Returns:
            加载的节点模块总数
        """
        count = 0

        # 1. 内置节点
        count += self._load_builtin()

        # 2. 社区节点包
        count += self._load_community()

        # 3. pip 安装的节点包
        count += self._load_pip()

        logger.info(f"节点包加载完成: {len(self._packs)} 个包, {count} 个节点模块")
        return count

    def _load_builtin(self) -> int:
        """加载内置节点"""
        from server.nodes.registry import discover_nodes

        count = discover_nodes(str(self.BUILTIN_DIR))

        # 注册内置节点包信息
        builtin_info = NodePackInfo(
            name="builtin",
            version="1.0.0",
            author="videofactory",
            description="内置节点",
            path=str(self.BUILTIN_DIR),
            source="builtin",
        )
        self._packs["builtin"] = builtin_info
        register_node_pack("builtin", builtin_info.to_dict())
        self._builtin_registered = True

        return count

    def _load_community(self) -> int:
        """加载社区节点包（nodes/community/ 目录）"""
        if not self.COMMUNITY_DIR.exists():
            return 0

        count = 0
        for pack_dir in self.COMMUNITY_DIR.iterdir():
            if not pack_dir.is_dir():
                continue

            manifest = pack_dir / "vf-node.yaml"
            if not manifest.exists():
                continue

            try:
                info = self._parse_manifest(manifest)
                info.path = str(pack_dir)
                info.source = "local"

                # 检查是否被禁用
                disabled_file = pack_dir / ".disabled"
                if disabled_file.exists():
                    info.enabled = False

                if not info.enabled:
                    logger.info(f"节点包已禁用: {info.name}")
                    self._packs[info.name] = info
                    register_node_pack(info.name, info.to_dict())
                    continue

                # 导入节点模块
                module_count = self._import_nodes(pack_dir, info)
                count += module_count

                self._packs[info.name] = info
                register_node_pack(info.name, info.to_dict())

            except Exception as e:
                logger.error(f"加载节点包失败 {pack_dir.name}: {e}")

        return count

    def _load_pip(self) -> int:
        """加载 pip 安装的节点包（通过 entry_points）"""
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return 0

        count = 0
        try:
            eps = entry_points()
            # Python 3.10+ 支持 select
            if hasattr(eps, "select"):
                vf_eps = eps.select(group="vf_node_packs")
            else:
                vf_eps = eps.get("vf_node_packs", [])

            for ep in vf_eps:
                try:
                    ep.load()  # 触发模块导入，注册节点
                    count += 1
                    logger.info(f"加载 pip 节点包: {ep.name}")

                    info = NodePackInfo(
                        name=ep.name,
                        version="0.0.0",
                        source="pip",
                        pip_name=ep.name,
                    )
                    self._packs[ep.name] = info
                    register_node_pack(ep.name, info.to_dict())

                except Exception as e:
                    logger.error(f"加载 pip 节点包失败 {ep.name}: {e}")

        except Exception as e:
            logger.debug(f"pip entry_points 扫描失败: {e}")

        return count

    def _parse_manifest(self, manifest_path: Path) -> NodePackInfo:
        """解析 vf-node.yaml 清单文件"""
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return NodePackInfo(
            name=data.get("name", manifest_path.parent.name),
            version=data.get("version", "0.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            homepage=data.get("homepage", ""),
            license=data.get("license", ""),
        )

    def _import_nodes(self, pack_dir: Path, info: NodePackInfo) -> int:
        """导入节点包中的节点模块"""
        manifest = pack_dir / "vf-node.yaml"
        with open(manifest, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        nodes_list = data.get("nodes", [])
        if not nodes_list:
            return 0

        # 将包目录加入 sys.path
        if str(pack_dir) not in sys.path:
            sys.path.insert(0, str(pack_dir))

        count = 0
        for node_entry in nodes_list:
            node_path = node_entry.get("path", "")
            if not node_path:
                continue

            module_name = node_path.replace("/", ".").replace(".py", "")
            try:
                importlib.import_module(module_name)
                count += 1
                logger.debug(f"导入节点: {info.name}/{module_name}")
            except Exception as e:
                logger.error(f"导入节点失败 {info.name}/{module_name}: {e}")

        return count

    # ── 安装管理 ──

    async def install_from_git(self, git_url: str, branch: str = None) -> NodePackInfo:
        """从 Git URL 安装节点包"""
        import asyncio
        import re

        # 从 URL 推导包名
        match = re.search(r'/([^/]+?)(\.git)?$', git_url.rstrip('/'))
        pack_name = match.group(1) if match else "unknown_pack"

        # 确保目录存在
        self.COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
        target_dir = self.COMMUNITY_DIR / pack_name

        if target_dir.exists():
            raise FileExistsError(f"节点包已存在: {pack_name}")

        # git clone
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([git_url, str(target_dir)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"git clone 失败: {stderr.decode()}")

        # 解析清单
        manifest = target_dir / "vf-node.yaml"
        if not manifest.exists():
            raise FileNotFoundError(f"节点包缺少 vf-node.yaml: {pack_name}")

        info = self._parse_manifest(manifest)
        info.path = str(target_dir)
        info.source = "git"
        info.git_url = git_url

        # 导入节点
        self._import_nodes(target_dir, info)

        self._packs[info.name] = info
        register_node_pack(info.name, info.to_dict())

        logger.info(f"Git 安装节点包成功: {info.name} v{info.version}")
        return info

    async def install_from_local(self, local_path: str) -> NodePackInfo:
        """从本地路径安装节点包（创建软链接）"""
        import shutil

        src = Path(local_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"路径不存在: {src}")

        manifest = src / "vf-node.yaml"
        if not manifest.exists():
            raise FileNotFoundError(f"节点包缺少 vf-node.yaml: {src}")

        info = self._parse_manifest(manifest)

        self.COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
        target = self.COMMUNITY_DIR / info.name

        if target.exists():
            raise FileExistsError(f"节点包已存在: {info.name}")

        # 复制（不创建软链接，避免跨盘问题）
        shutil.copytree(str(src), str(target))

        info.path = str(target)
        info.source = "local"

        self._import_nodes(target, info)

        self._packs[info.name] = info
        register_node_pack(info.name, info.to_dict())

        logger.info(f"本地安装节点包成功: {info.name} v{info.version}")
        return info

    async def install_from_pip(self, pip_name: str) -> NodePackInfo:
        """从 pip 安装节点包"""
        import asyncio

        cmd = [sys.executable, "-m", "pip", "install", pip_name]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"pip install 失败: {stderr.decode()}")

        # 加载 entry_points
        count = self._load_pip()

        info = self._packs.get(pip_name)
        if not info:
            info = NodePackInfo(
                name=pip_name,
                version="0.0.0",
                source="pip",
                pip_name=pip_name,
            )
            self._packs[pip_name] = info
            register_node_pack(pip_name, info.to_dict())

        logger.info(f"pip 安装节点包成功: {pip_name}")
        return info

    async def remove(self, name: str) -> bool:
        """卸载节点包"""
        import shutil

        info = self._packs.get(name)
        if not info:
            return False

        if info.source == "builtin":
            raise ValueError("内置节点包不可卸载")

        # 删除目录
        if info.path and Path(info.path).exists():
            shutil.rmtree(info.path)

        # 从注册表移除（节点类仍保留在内存中，重启后消失）
        del self._packs[name]

        logger.info(f"卸载节点包: {name}")
        return True

    def enable(self, name: str) -> bool:
        """启用节点包"""
        info = self._packs.get(name)
        if not info:
            return False

        info.enabled = True
        disabled_file = Path(info.path) / ".disabled"
        if disabled_file.exists():
            disabled_file.unlink()

        return True

    def disable(self, name: str) -> bool:
        """禁用节点包"""
        info = self._packs.get(name)
        if not info:
            return False

        info.enabled = False
        disabled_file = Path(info.path) / ".disabled"
        disabled_file.touch()

        return True

    def list_packs(self) -> list[NodePackInfo]:
        """列出所有节点包"""
        return list(self._packs.values())

    def get_pack(self, name: str) -> Optional[NodePackInfo]:
        """获取节点包信息"""
        return self._packs.get(name)


# 全局加载器实例
pack_loader = NodePackLoader()
