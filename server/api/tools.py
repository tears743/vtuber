import logging
import re
import shutil
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tools", tags=["tools"])

TOOLS_DIR = Path(__file__).parent.parent.parent / "data" / "tools"


class ToolCreate(BaseModel):
    name: str = ""
    description: str = ""
    executor: Optional[dict] = None
    executor_type: Optional[str] = None
    code: Optional[str] = None
    http: Optional[dict] = None
    parameters: dict = Field(default_factory=dict)
    skill_md: Optional[str] = None


class ToolUpdate(BaseModel):
    description: Optional[str] = None
    executor: Optional[dict] = None
    executor_type: Optional[str] = None
    code: Optional[str] = None
    http: Optional[dict] = None
    parameters: Optional[dict] = None
    skill_md: Optional[str] = None


class ToolExecuteRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class LLMCreateRequest(BaseModel):
    description: str
    preview: bool = False
    skill_md: Optional[str] = None
    run_py: Optional[str] = None
    model_name: Optional[str] = None


def _get_tool_dir(name: str) -> Path:
    return TOOLS_DIR / name


def _executor_from_body(body) -> dict:
    if getattr(body, "executor", None):
        return body.executor

    executor_type = getattr(body, "executor_type", None) or "python"
    if executor_type == "http":
        http_cfg = getattr(body, "http", None) or {}
        return {"type": "http", **http_cfg}
    return {"type": "python", "working_dir": ".", "sandbox": "process", "timeout_seconds": 60}


def _read_run_py(tool_dir: Path) -> str:
    run_file = tool_dir / "run.py"
    if run_file.exists():
        return run_file.read_text(encoding="utf-8")
    return ""


def _parse_skill_md(text: str) -> tuple[dict, str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        raise HTTPException(status_code=400, detail="SKILL.md 缺少 YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise HTTPException(status_code=400, detail="SKILL.md frontmatter 未闭合")
    frontmatter = text[3:end].strip()
    body = text[end + 4:].lstrip("\r\n")
    try:
        meta = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"SKILL.md frontmatter 解析失败: {e}")
    return meta, body


def _build_skill_md(definition: dict, body: str = "") -> str:
    clean = {k: v for k, v in definition.items() if not k.startswith("_")}
    clean.pop("skill_md", None)
    clean.pop("skill_markdown", None)
    clean["manifest_format"] = "skill"
    frontmatter = yaml.dump(clean, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    if not body.strip():
        body = (
            f"# {clean.get('name', 'tool')}\n\n"
            f"{clean.get('description', '')}\n\n"
            "## Usage\n\n"
            "Call this skill when the task matches the description. The executor receives the declared parameters.\n"
        )
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


def _save_skill_md(tool_dir: Path, definition: dict, body: str = "") -> str:
    tool_dir.mkdir(parents=True, exist_ok=True)
    skill_md = definition.get("skill_md") or _build_skill_md(definition, body)
    (tool_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return skill_md


def _definition_from_skill_md(skill_md: str) -> dict:
    meta, body = _parse_skill_md(skill_md)
    meta["skill_markdown"] = body
    meta["skill_md"] = skill_md
    meta["manifest_format"] = "skill"
    if not meta.get("name"):
        raise HTTPException(status_code=400, detail="SKILL.md frontmatter 缺少 name")
    if not meta.get("executor"):
        meta["executor"] = {"type": "python", "working_dir": ".", "sandbox": "process", "timeout_seconds": 60}
    return meta


def _public_tool(tool: dict) -> dict:
    clean = {k: v for k, v in tool.items() if not k.startswith("_")}
    executor = clean.get("executor", {}) or {}
    clean["executor_type"] = executor.get("type", "")
    clean["manifest_format"] = "skill"
    if executor.get("type") == "http":
        clean["http"] = {k: v for k, v in executor.items() if k != "type"}

    tool_dir = Path(tool.get("_dir", ""))
    if tool_dir:
        skill_file = tool_dir / "SKILL.md"
        if skill_file.exists():
            clean["skill_md"] = skill_file.read_text(encoding="utf-8")
        if executor.get("type") == "python":
            clean["code"] = _read_run_py(tool_dir)
    return clean


def _load_llm_model(model_name: Optional[str] = None) -> dict:
    from server.api.settings import _load_settings

    settings = _load_settings()
    models = settings.get("models", {})
    if model_name:
        cfg = models.get(model_name)
        if not cfg:
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
        caps = cfg.get("capabilities", [])
        if not isinstance(caps, list):
            caps = []
        if "text" not in caps and "coding" not in caps:
            raise HTTPException(status_code=400, detail="请选择具备 text 或 coding 能力的模型")
        return cfg

    for cfg in models.values():
        caps = cfg.get("capabilities", [])
        if isinstance(caps, list) and "coding" in caps:
            return cfg
    raise HTTPException(status_code=400, detail="未找到 coding 能力模型，请先在设置中配置")


def _extract_skill_md(text: str) -> str:
    patterns = [
        r"```(?:markdown|md)\s*\n(---\n.*?\n---\n.*?)```",
        r"```skill\s*\n(---\n.*?\n---\n.*?)```",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return matches[0].strip() + "\n"

    start = text.find("---")
    if start != -1:
        end = text.find("\n---", start + 3)
        if end != -1:
            return text[start:].strip() + "\n"

    raise HTTPException(status_code=500, detail="LLM 响应中未找到有效的 SKILL.md")


def _extract_python_code(text: str) -> str:
    matches = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    if "def run" in text:
        return text.strip()
    return ""


def _build_llm_prompt(description: str) -> str:
    return f"""你是 VideoFactory 的工具 Skill 作者。请根据用户需求生成一个 Agent Skill 工具。

工具目录最终包含两个文件：
1. `SKILL.md`：Agent 可读的 skill 文档，必须包含 YAML frontmatter。
2. `run.py`：Python 执行器，必须定义 `run(params: dict) -> dict`。

SKILL.md frontmatter 必须至少包含：
```markdown
---
name: example_tool
description: When and why an agent should use this tool.
executor:
  type: python
  working_dir: "."
  sandbox: process
  timeout_seconds: 60
parameters:
  type: object
  properties:
    query:
      type: string
      description: User query
  required:
    - query
---

# example_tool

Explain what this skill does, when to use it, input expectations, output shape, and caveats.
```

run.py 必须形如：
```python
def run(params: dict) -> dict:
    query = params.get("query", "")
    return {{"result": query}}
```

要求：
1. 先输出一个 markdown 代码块，内容是完整 `SKILL.md`。
2. 再输出一个 python 代码块，内容是完整 `run.py`。
3. name 使用 snake_case。
4. executor.type 目前只能使用 python。
5. run() 必须返回 dict。
6. SKILL.md 正文要像 Agent Skill 文档，不要只是配置说明。

用户需求：
{description}
"""


def _call_llm(model_cfg: dict, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])
    response = client.chat.completions.create(
        model=model_cfg["model"],
        messages=[
            {"role": "system", "content": "你是专业的 Agent Skill 与 Python 工具执行器作者。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=model_cfg.get("max_output_tokens", 8192),
        temperature=0.3,
    )
    return response.choices[0].message.content


def _extract_tool_artifact(text: str) -> dict:
    return {
        "skill_md": _extract_skill_md(text),
        "run_py": _extract_python_code(text),
    }


def _validate_tool_artifact(artifact: dict) -> list[str]:
    errors = []
    skill_md = artifact.get("skill_md") or ""
    python_code = artifact.get("run_py") or ""
    try:
        definition = _definition_from_skill_md(skill_md)
        if definition.get("executor", {}).get("type") != "python":
            errors.append("SKILL.md executor.type must be python.")
        if not definition.get("name"):
            errors.append("SKILL.md frontmatter must include name.")
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        errors.append(f"SKILL.md is invalid: {detail}")

    if not python_code:
        errors.append("run.py code block is missing.")
    else:
        try:
            compile(python_code, "<generated_tool>", "exec")
        except SyntaxError as e:
            errors.append(f"run.py has syntax error: {e}")
    return errors


@router.get("")
async def list_tools():
    from server.tools.registry import tool_registry

    tool_registry.load_all()
    return {"tools": [_public_tool(t) for t in tool_registry.list_tools()]}


@router.get("/{name}")
async def get_tool(name: str):
    from server.tools.registry import tool_registry

    tool = tool_registry.get_tool(name)
    if tool is None:
        tool_registry.load_all()
        tool = tool_registry.get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")
    return _public_tool(tool)


@router.post("")
async def create_tool(body: ToolCreate):
    from server.tools.registry import tool_registry

    if body.skill_md:
        definition = _definition_from_skill_md(body.skill_md)
        name = definition["name"]
    else:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="工具名称不能为空")
        definition = {
            "name": name,
            "description": body.description,
            "executor": _executor_from_body(body),
            "parameters": body.parameters,
        }

    tool_dir = _get_tool_dir(name)
    if tool_dir.exists():
        raise HTTPException(status_code=409, detail=f"工具 '{name}' 已存在")

    skill_md = _save_skill_md(tool_dir, definition, definition.get("skill_markdown", ""))
    definition["skill_md"] = skill_md
    definition["manifest_format"] = "skill"

    if definition.get("executor", {}).get("type") == "python":
        (tool_dir / "run.py").write_text(
            body.code or 'def run(params: dict) -> dict:\n    return {"status": "ok"}\n',
            encoding="utf-8",
        )

    definition["_dir"] = str(tool_dir)
    tool_registry.register(name, definition)
    return {"status": "created", "name": name}


@router.put("/{name}")
async def update_tool(name: str, body: ToolUpdate):
    from server.tools.registry import tool_registry

    tool = tool_registry.get_tool(name)
    if tool is None:
        tool_registry.load_all()
        tool = tool_registry.get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")

    tool_dir = _get_tool_dir(name)
    if body.skill_md:
        updated = _definition_from_skill_md(body.skill_md)
        if updated["name"] != name:
            raise HTTPException(status_code=400, detail="编辑时不能修改工具 name")
        tool.update(updated)
    else:
        if body.description is not None:
            tool["description"] = body.description
        if body.executor is not None or body.executor_type is not None or body.http is not None:
            tool["executor"] = _executor_from_body(body)
        if body.parameters is not None:
            tool["parameters"] = body.parameters

    skill_md = _save_skill_md(tool_dir, tool, tool.get("skill_markdown", ""))
    tool["skill_md"] = skill_md

    if body.code is not None and tool.get("executor", {}).get("type") == "python":
        (tool_dir / "run.py").write_text(body.code, encoding="utf-8")

    tool["_dir"] = str(tool_dir)
    tool_registry.register(name, tool)
    return {"status": "updated", "name": name}


@router.delete("/{name}")
async def delete_tool(name: str):
    from server.tools.registry import tool_registry

    tool_dir = _get_tool_dir(name)
    if not tool_dir.exists():
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")
    try:
        shutil.rmtree(tool_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    tool_registry.unregister(name)
    return {"status": "deleted", "name": name}


@router.post("/{name}/execute")
async def execute_tool(name: str, body: ToolExecuteRequest):
    from server.tools.registry import tool_registry

    tool = tool_registry.get_tool(name)
    if tool is None:
        tool_registry.load_all()
        tool = tool_registry.get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")

    try:
        result = tool_registry.execute(name, body.params)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error("Tool execution failed %s: %s", name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"工具执行失败: {str(e)}")


@router.post("/create")
async def llm_create_tool(req: LLMCreateRequest):
    from server.tools.registry import tool_registry

    if req.skill_md:
        skill_md = req.skill_md.strip() + "\n"
        python_code = (req.run_py or "").strip()
        agent_attempts = 0
        agent_validation_errors = _validate_tool_artifact({"skill_md": skill_md, "run_py": python_code})
    else:
        model_cfg = _load_llm_model(req.model_name)
        try:
            from server.ai.generation_agent import run_generation_agent

            result = run_generation_agent(
                model_cfg=model_cfg,
                task_prompt=_build_llm_prompt(req.description),
                system_prompt="You are a professional Agent Skill and Python tool executor author.",
                extract_artifact=_extract_tool_artifact,
                validate_artifact=_validate_tool_artifact,
                max_steps=4,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("LLM tool generation failed: %s", e, exc_info=True)
            raise HTTPException(status_code=502, detail=f"LLM 调用失败: {str(e)}")
        if result.validation_errors:
            raise HTTPException(status_code=502, detail="AI 工具生成校验失败: " + "; ".join(result.validation_errors))
        skill_md = result.artifact["skill_md"]
        python_code = result.artifact["run_py"]
        agent_attempts = result.attempts
        agent_validation_errors = result.validation_errors

    definition = _definition_from_skill_md(skill_md)
    tool_name = definition["name"]

    if req.preview:
        return {
            "status": "preview",
            "skill_md": skill_md,
            "run_py": python_code,
            "agent_attempts": agent_attempts,
            "agent_validation_errors": agent_validation_errors,
        }

    tool_dir = _get_tool_dir(tool_name)
    if tool_dir.exists():
        raise HTTPException(status_code=409, detail=f"工具 '{tool_name}' 已存在，请先删除")

    executor_type = definition.get("executor", {}).get("type", "")
    if executor_type != "python":
        raise HTTPException(status_code=400, detail="当前仅支持 python 执行器")
    if not python_code:
        raise HTTPException(status_code=400, detail="缺少 run.py 代码")

    try:
        compile(python_code, f"<generated_tool_{tool_name}>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=500, detail=f"生成的 Python 代码有语法错误: {e}")

    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (tool_dir / "run.py").write_text(python_code, encoding="utf-8")

    definition["_dir"] = str(tool_dir)
    tool_registry.register(tool_name, definition)

    return {
        "status": "created",
        "name": tool_name,
        "path": str(tool_dir),
        "skill_md": skill_md,
        "run_py": python_code,
        "agent_attempts": agent_attempts,
        "agent_validation_errors": agent_validation_errors,
    }
