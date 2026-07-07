"""
节点包 API

REST 路由：
- GET    /api/node-packs              列出所有节点包
- GET    /api/node-packs/updates      检查可用更新
- POST   /api/node-packs/install      安装节点包
- POST   /api/node-packs/{name}/update
- POST   /api/node-packs/{name}/enable
- POST   /api/node-packs/{name}/disable
- DELETE /api/node-packs/{name}
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/node-packs", tags=["node-packs"])


class InstallRequest(BaseModel):
    source: str  # git URL | 本地路径 | pip 包名
    branch: str = None  # git 分支（可选）


@router.get("")
async def list_node_packs():
    """列出所有节点包（含版本/来源/启用状态）"""
    from server.nodes.loader import pack_loader

    packs = [pack.to_dict() for pack in pack_loader.list_packs()]
    return {"node_packs": packs}


@router.get("/updates")
async def check_updates():
    """检查所有 Git 安装节点包的可用更新"""
    from server.nodes.loader import pack_loader
    from server.nodes.pack_manager import NodePackManager

    manager = NodePackManager(pack_loader)
    updates = await manager.check_updates()
    return {"updates": [u.to_dict() for u in updates]}


@router.post("/install")
async def install_pack(req: InstallRequest):
    """安装节点包

    source 可以是：
    - Git URL (https://github.com/... or git@github.com:...)
    - 本地路径 (/path/to/pack)
    - pip 包名 (some-vf-node-pack)
    """
    from server.nodes.loader import pack_loader

    try:
        source = req.source
        if source.startswith("http") or source.startswith("git@") or source.startswith("ssh://git"):
            info = await pack_loader.install_from_git(source, req.branch)
        elif source.startswith("/") or source.startswith("./") or "\\" in source:
            info = await pack_loader.install_from_local(source)
        else:
            info = await pack_loader.install_from_pip(source)

        return {"status": "installed", "pack": info.to_dict()}

    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"安装节点包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/update")
async def update_pack(name: str):
    """更新指定节点包"""
    from server.nodes.loader import pack_loader
    from server.nodes.pack_manager import NodePackManager

    manager = NodePackManager(pack_loader)
    try:
        success = await manager.update(name)
        if success:
            pack = pack_loader.get_pack(name)
            return {"status": "updated", "pack": pack.to_dict() if pack else None}
        else:
            raise HTTPException(status_code=400, detail=f"更新失败: {name}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"更新节点包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/enable")
async def enable_pack(name: str):
    """启用节点包"""
    from server.nodes.loader import pack_loader

    success = pack_loader.enable(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"节点包不存在: {name}")
    return {"status": "enabled", "name": name}


@router.post("/{name}/disable")
async def disable_pack(name: str):
    """禁用节点包"""
    from server.nodes.loader import pack_loader

    success = pack_loader.disable(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"节点包不存在: {name}")
    return {"status": "disabled", "name": name}


@router.delete("/{name}")
async def remove_pack(name: str):
    """卸载节点包"""
    from server.nodes.loader import pack_loader

    try:
        success = await pack_loader.remove(name)
        if not success:
            raise HTTPException(status_code=404, detail=f"节点包不存在: {name}")
        return {"status": "removed", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"卸载节点包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
