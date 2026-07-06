"""
全局设置 API — 模型池管理

REST 路由：
- GET    /api/settings/models            获取所有模型
- POST   /api/settings/models            添加模型
- PUT    /api/settings/models/{id}       编辑模型
- DELETE /api/settings/models/{id}       删除模型
- POST   /api/settings/models/{id}/test  测试连接
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_DIR = Path(__file__).parent.parent.parent / "settings"
SETTINGS_FILE = SETTINGS_DIR / "global.json"


class ModelCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    context_length: int = 128000
    max_output_tokens: int = 8192
    capabilities: list = ["text"]
    note: str = ""


class ModelUpdate(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    capabilities: Optional[list] = None
    note: Optional[str] = None


def _load_settings() -> dict:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 首次启动，从 config.yaml 导入
    return _import_from_config()


def _save_settings(data: dict):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _import_from_config() -> dict:
    """首次启动时从 config.yaml 导入模型配置"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from config_loader import load_config
        config = load_config()
        models = config.get("models", {})
        settings = {"models": {}}
        for name, cfg in models.items():
            settings["models"][name] = {
                "name": name,
                "base_url": cfg.get("base_url", ""),
                "api_key": cfg.get("api_key", ""),
                "model": cfg.get("model", ""),
                "context_length": cfg.get("context_length", 128000),
                "max_output_tokens": cfg.get("max_output_tokens", 8192),
                "capabilities": ["text"],
                "note": cfg.get("note", ""),
            }
        _save_settings(settings)
        return settings
    except Exception as e:
        logger.warning(f"导入 config.yaml 失败: {e}")
        settings = {"models": {}}
        _save_settings(settings)
        return settings


def _mask_key(key: str) -> str:
    """脱敏 API key"""
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]


@router.get("/models")
async def list_models():
    """获取所有模型（API key 脱敏）"""
    settings = _load_settings()
    models = settings.get("models", {})
    result = []
    for name, cfg in models.items():
        masked = {**cfg, "api_key": _mask_key(cfg.get("api_key", ""))}
        result.append(masked)
    return result


@router.get("/models/{model_id}")
async def get_model(model_id: str):
    """获取单个模型详情"""
    settings = _load_settings()
    models = settings.get("models", {})
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    cfg = models[model_id]
    return {**cfg, "api_key": _mask_key(cfg.get("api_key", ""))}


@router.post("/models")
async def create_model(body: ModelCreate):
    """添加模型"""
    settings = _load_settings()
    models = settings.get("models", {})
    if body.name in models:
        raise HTTPException(status_code=409, detail=f"Model '{body.name}' already exists")
    models[body.name] = {
        "name": body.name,
        "base_url": body.base_url,
        "api_key": body.api_key,
        "model": body.model,
        "context_length": body.context_length,
        "max_output_tokens": body.max_output_tokens,
        "capabilities": body.capabilities,
        "note": body.note,
    }
    settings["models"] = models
    _save_settings(settings)
    return {"status": "created", "name": body.name}


@router.put("/models/{model_id}")
async def update_model(model_id: str, body: ModelUpdate):
    """编辑模型"""
    settings = _load_settings()
    models = settings.get("models", {})
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    cfg = models[model_id]
    for field in ["base_url", "api_key", "model", "context_length", "max_output_tokens", "capabilities", "note"]:
        value = getattr(body, field, None)
        if value is not None:
            cfg[field] = value
    models[model_id] = cfg
    settings["models"] = models
    _save_settings(settings)
    return {"status": "updated", "name": model_id}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    """删除模型"""
    settings = _load_settings()
    models = settings.get("models", {})
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    del models[model_id]
    settings["models"] = models
    _save_settings(settings)
    return {"status": "deleted", "name": model_id}


@router.post("/models/{model_id}/test")
async def test_model(model_id: str):
    """测试模型连接"""
    settings = _load_settings()
    models = settings.get("models", {})
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    cfg = models[model_id]

    try:
        from openai import OpenAI
        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return {"status": "ok", "message": "连接成功", "response": response.choices[0].message.content}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {str(e)}"}
