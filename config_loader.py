"""
videoFactory 配置加载器
"""
import os
import yaml
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent


def load_config(path: str = None) -> dict:
    """加载 config.yaml，支持环境变量覆盖"""
    if path is None:
        path = PROJECT_ROOT / "config.yaml"
        # worktree 中可能没有 config.yaml，fallback 到主仓库
        if not Path(path).exists():
            main_repo_config = Path(r"d:\workspace\videoFactory\config.yaml")
            if main_repo_config.exists():
                path = main_repo_config

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # data_root 相对路径基于主仓库解析（worktree 中没有 data/ 目录）
    paths = cfg.get("paths", {})
    data_root = paths.get("data_root", "data")
    if not Path(data_root).is_absolute():
        main_data = Path(r"d:\workspace\videoFactory\data")
        if main_data.exists():
            paths["data_root"] = str(main_data)
            cfg["paths"] = paths
    
    # 环境变量覆盖（向后兼容）
    if os.environ.get("DIRECTOR_API_KEY"):
        models = cfg.get("models", {})
        role_name = cfg.get("roles", {}).get("director", "deepseek-v4-flash")
        if role_name in models:
            models[role_name]["api_key"] = os.environ["DIRECTOR_API_KEY"]
    
    return cfg


def get_model_config(cfg: dict, role: str) -> dict:
    """
    根据角色名获取模型配置。
    
    Args:
        cfg: 完整配置 dict
        role: 角色名 (orchestrator, worker, director, scriptwriter, etc.)
    
    Returns:
        {"base_url": ..., "api_key": ..., "model": ..., "context_length": ...}
    
    Usage:
        model = get_model_config(cfg, "worker")
        client = OpenAI(base_url=model["base_url"], api_key=model["api_key"])
    """
    roles = cfg.get("roles", {})
    models = cfg.get("models", {})
    
    # 获取这个角色对应的模型名
    model_name = roles.get(role)
    if not model_name:
        raise ValueError(f"Role '{role}' not found in config.roles")
    
    # 获取模型详情
    model_cfg = models.get(model_name)
    if not model_cfg:
        raise ValueError(f"Model '{model_name}' (for role '{role}') not found in config.models")
    
    return model_cfg


def get_worker_model_config(cfg: dict, platform: str) -> dict:
    """
    获取特定平台的 Worker 模型配置。
    优先查 roles.worker_overrides.{platform}，fallback 到 roles.worker。
    
    Args:
        cfg: 完整配置 dict
        platform: 平台名 (weibo, douyin, huggingface, github)
    
    Returns:
        {"base_url": ..., "api_key": ..., "model": ..., "context_length": ...}
    """
    roles = cfg.get("roles", {})
    models = cfg.get("models", {})
    
    # 先看有没有平台专属覆盖
    overrides = roles.get("worker_overrides", {})
    model_name = overrides.get(platform)
    
    # fallback 到默认 worker
    if not model_name:
        model_name = roles.get("worker")
    
    if not model_name:
        raise ValueError(f"No worker model configured for platform '{platform}'")
    
    model_cfg = models.get(model_name)
    if not model_cfg:
        raise ValueError(f"Model '{model_name}' not found in config.models")
    
    return model_cfg


def ensure_dirs(cfg: dict):
    """确保所有输出目录存在（按日期 + 阶段）"""
    from datetime import datetime
    
    data_root = PROJECT_ROOT / cfg.get("paths", {}).get("data_root", "data")
    today = datetime.now().strftime("%Y-%m-%d")
    today_dir = data_root / today
    
    stages = cfg.get("pipeline_stages", ["collected", "selected", "scripts", "audio", "visuals", "live2d", "output"])
    for stage in stages:
        (today_dir / stage).mkdir(parents=True, exist_ok=True)
    
    # assets dir
    assets = PROJECT_ROOT / cfg.get("paths", {}).get("assets", "assets")
    assets.mkdir(parents=True, exist_ok=True)


def get_today_dir(cfg: dict) -> Path:
    """获取今天的数据根目录 data/{date}/"""
    from datetime import datetime
    
    data_root = PROJECT_ROOT / cfg.get("paths", {}).get("data_root", "data")
    today = datetime.now().strftime("%Y-%m-%d")
    return data_root / today

