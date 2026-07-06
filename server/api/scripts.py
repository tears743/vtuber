"""
Scripts API — 脚本时间轴预览

提供脚本数据供前端 Timeline 可视化，不影响渲染流程。
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config_loader import load_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


def _get_data_root() -> Path:
    config = load_config()
    return Path(config.get("paths", {}).get("data_root", "data"))


@router.get("/dates")
async def list_dates():
    """列出所有有脚本的日期"""
    data_root = _get_data_root()
    dates = []
    for d in sorted(data_root.iterdir(), reverse=True):
        if d.is_dir() and (d / "scripts").exists():
            scripts = list((d / "scripts").glob("*.json"))
            has_aligned = (d / "scripts_aligned").exists()
            dates.append({
                "date": d.name,
                "scripts": [s.stem for s in scripts],
                "has_aligned": has_aligned,
            })
    return dates


@router.get("/{date}/{script_id}")
async def get_script(date: str, script_id: str, aligned: bool = False):
    """获取指定脚本内容
    
    Args:
        date: 日期 (YYYY-MM-DD)
        script_id: 脚本 ID (如 hot_daily, ai_daily)
        aligned: 是否返回对齐后的脚本
    """
    data_root = _get_data_root()
    
    if aligned:
        script_path = data_root / date / "scripts_aligned" / f"{script_id}.json"
    else:
        script_path = data_root / date / "scripts" / f"{script_id}.json"
    
    if not script_path.exists():
        raise HTTPException(404, f"脚本不存在: {date}/{script_id} (aligned={aligned})")
    
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    
    return script


@router.get("/{date}/{script_id}/compare")
async def compare_script(date: str, script_id: str):
    """获取对齐前后的脚本对比数据"""
    data_root = _get_data_root()
    
    original_path = data_root / date / "scripts" / f"{script_id}.json"
    aligned_path = data_root / date / "scripts_aligned" / f"{script_id}.json"
    
    if not original_path.exists():
        raise HTTPException(404, f"原始脚本不存在: {date}/{script_id}")
    
    with open(original_path, "r", encoding="utf-8") as f:
        original = json.load(f)
    
    aligned = None
    if aligned_path.exists():
        with open(aligned_path, "r", encoding="utf-8") as f:
            aligned = json.load(f)
    
    return {
        "original": original,
        "aligned": aligned,
    }
