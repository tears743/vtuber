"""
节点包版本管理 + 更新检测

功能：
- 检查 Git 安装的节点包是否有新版本
- 拉取远程 changelog
- 执行 git pull 更新
- 语义化版本比较（semver）
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from server.nodes.loader import NodePackLoader, NodePackInfo

logger = logging.getLogger(__name__)


@dataclass
class NodePackUpdateInfo:
    """节点包更新信息"""
    name: str
    current_version: str
    latest_version: str
    changelog: str = ""
    git_url: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "changelog": self.changelog,
            "git_url": self.git_url,
        }


def parse_semver(version: str) -> tuple:
    """解析语义化版本号为 (major, minor, patch) 元组

    支持: 1.2.3, v1.2.3, 1.2.3-rc1, 1.2.3+build5
    """
    # 去掉前缀 v
    version = version.lstrip("v")

    # 只取 major.minor.patch 部分
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return (0, 0, 0)

    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def compare_versions(v1: str, v2: str) -> int:
    """比较两个语义化版本

    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    """
    s1 = parse_semver(v1)
    s2 = parse_semver(v2)
    if s1 < s2:
        return -1
    elif s1 > s2:
        return 1
    return 0


class NodePackManager:
    """节点包管理器 — 版本检测 + 更新"""

    def __init__(self, loader: NodePackLoader):
        self.loader = loader

    async def check_updates(self) -> list[NodePackUpdateInfo]:
        """检查所有 Git 安装节点包的远程版本

        通过 git ls-remote 获取远程 tags，找到最新版本。
        """
        updates = []

        for pack in self.loader.list_packs():
            if pack.source != "git" or not pack.git_url:
                continue

            try:
                latest = await self._fetch_remote_version(pack.git_url)
                if latest and compare_versions(latest, pack.version) > 0:
                    changelog = await self._fetch_changelog(pack, latest)
                    updates.append(NodePackUpdateInfo(
                        name=pack.name,
                        current_version=pack.version,
                        latest_version=latest,
                        changelog=changelog,
                        git_url=pack.git_url,
                    ))
                    logger.info(f"节点包 {pack.name} 有更新: {pack.version} → {latest}")
            except Exception as e:
                logger.warning(f"检查更新失败 {pack.name}: {e}")

        return updates

    async def update(self, name: str) -> bool:
        """更新指定节点包

        Git 包: git pull
        pip 包: pip install --upgrade
        """
        pack = self.loader.get_pack(name)
        if not pack:
            raise ValueError(f"节点包不存在: {name}")

        if pack.source == "git":
            return await self._git_update(pack)
        elif pack.source == "pip":
            return await self._pip_update(pack)
        else:
            logger.warning(f"本地节点包不支持在线更新: {name}")
            return False

    async def _git_update(self, pack: NodePackInfo) -> bool:
        """通过 git pull 更新节点包"""
        pack_path = pack.path
        if not pack_path or not pack_path.exists():
            return False

        cmd = ["git", "-C", str(pack_path), "pull", "--ff-only"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"git pull 失败 {pack.name}: {stderr.decode()}")
            return False

        # 重新解析清单获取新版本
        from pathlib import Path
        manifest = Path(pack_path) / "vf-node.yaml"
        if manifest.exists():
            new_info = self.loader._parse_manifest(manifest)
            pack.version = new_info.version
            pack.description = new_info.description

        logger.info(f"节点包更新成功: {pack.name} → v{pack.version}")
        return True

    async def _pip_update(self, pack: NodePackInfo) -> bool:
        """通过 pip install --upgrade 更新节点包"""
        import sys

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", pack.pip_name]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"pip upgrade 失败 {pack.name}: {stderr.decode()}")
            return False

        logger.info(f"节点包更新成功: {pack.name}")
        return True

    async def _fetch_remote_version(self, git_url: str) -> Optional[str]:
        """获取远程仓库的最新版本号（从 git tags）"""
        cmd = ["git", "ls-remote", "--tags", git_url]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return None

        output = stdout.decode("utf-8", errors="replace")
        versions = []

        for line in output.strip().split("\n"):
            if not line:
                continue
            # 格式: <hash>\trefs/tags/v1.2.3
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            ref = parts[1]
            if ref.startswith("refs/tags/"):
                tag = ref.replace("refs/tags/", "").replace("^{}", "")
                # 过滤非版本格式的 tag
                if re.match(r"v?\d+\.\d+\.\d+", tag):
                    versions.append(tag)

        if not versions:
            return None

        # 取最大版本
        versions.sort(key=parse_semver, reverse=True)
        return versions[0].lstrip("v")

    async def _fetch_changelog(self, pack: NodePackInfo, target_version: str) -> str:
        """获取 changelog（从 vf-node.yaml 的 changelog 字段或 CHANGELOG.md）"""
        from pathlib import Path

        pack_path = Path(pack.path)

        # 尝试从 vf-node.yaml 的 changelog 字段获取
        manifest = pack_path / "vf-node.yaml"
        if manifest.exists():
            import yaml
            with open(manifest, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            changelog = data.get("changelog", {})
            target_key = target_version.lstrip("v")
            if target_key in changelog:
                return changelog[target_key]

        # 尝试从 CHANGELOG.md 获取
        changelog_file = pack_path / "CHANGELOG.md"
        if changelog_file.exists():
            content = changelog_file.read_text(encoding="utf-8")
            # 简单提取目标版本段落
            lines = content.split("\n")
            capture = False
            result = []
            for line in lines:
                if target_version in line or target_version.lstrip("v") in line:
                    capture = True
                    continue
                if capture and line.startswith("#") and target_version not in line:
                    break
                if capture:
                    result.append(line)
            if result:
                return "\n".join(result).strip()

        return ""
