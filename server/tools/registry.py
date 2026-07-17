import asyncio
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).parent.parent.parent / "data" / "tools"


class ToolRegistry:
    """Registry for Agent Skill tools stored under data/tools."""

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def load_all(self) -> int:
        self._tools.clear()
        if not TOOLS_DIR.exists():
            logger.info("Tool directory does not exist: %s", TOOLS_DIR)
            return 0

        count = 0
        for tool_dir in TOOLS_DIR.iterdir():
            if not tool_dir.is_dir():
                continue

            skill_file = tool_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                definition = self._load_skill_md(skill_file)
                name = definition.get("name", tool_dir.name)
                definition["_dir"] = str(tool_dir)
                self._tools[name] = definition
                count += 1
                logger.debug("Loaded skill tool: %s", name)
            except Exception as e:
                logger.error("Failed to load skill tool %s: %s", tool_dir.name, e)

        logger.info("Loaded %s skill tools from %s", count, TOOLS_DIR)
        return count

    @staticmethod
    def _load_skill_md(path: Path) -> dict:
        text = path.read_text(encoding="utf-8").lstrip("\ufeff")
        if not text.startswith("---"):
            raise ValueError(f"SKILL.md missing frontmatter: {path}")
        end = text.find("\n---", 3)
        if end == -1:
            raise ValueError(f"SKILL.md frontmatter is not closed: {path}")
        frontmatter = text[3:end].strip()
        body = text[end + 4:].lstrip("\r\n")
        definition = yaml.safe_load(frontmatter) or {}
        if not definition.get("name"):
            definition["name"] = path.parent.name
        definition["skill_markdown"] = body
        definition["skill_md"] = text
        definition["manifest_format"] = "skill"
        return definition

    def get_tool(self, name: str) -> dict | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return list(self._tools.values())

    def register(self, name: str, definition: dict) -> None:
        self._tools[name] = definition
        logger.info("Registered skill tool: %s", name)

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            logger.info("Unregistered skill tool: %s", name)
            return True
        return False

    def execute(self, name: str, params: dict) -> dict:
        definition = self._tools.get(name)
        if definition is None:
            raise KeyError(f"Tool '{name}' not found. Available tools: {list(self._tools.keys())}")

        executor = definition.get("executor", {}) or {}
        exec_type = executor.get("type", "")

        if exec_type == "python":
            return self._execute_python(definition, params)
        if exec_type == "http":
            return self._execute_http(executor, params)
        raise ValueError(f"Unsupported executor type '{exec_type}' for tool '{name}'")

    def _execute_python(self, definition: dict, params: dict) -> dict:
        tool_dir = Path(definition.get("_dir", ""))
        run_file = tool_dir / "run.py"
        if not run_file.exists():
            raise FileNotFoundError(f"Python executor missing run.py: {run_file}")

        executor = definition.get("executor", {}) or {}
        work_dir = self._resolve_working_dir(tool_dir, executor.get("working_dir", "."))
        timeout = executor.get("timeout_seconds", 60)
        try:
            timeout = max(1, min(int(timeout), 3600))
        except (TypeError, ValueError):
            timeout = 60

        runner = Path(__file__).with_name("python_runner.py")
        try:
            completed = subprocess.run(
                [sys.executable, str(runner), str(run_file)],
                input=json.dumps(params, ensure_ascii=False),
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=str(work_dir),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"工具执行超时（{timeout}s）") from e
        except Exception as e:
            raise RuntimeError(f"工具执行失败: {e}") from e

        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"工具进程退出码 {completed.returncode}")

        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as e:
            detail = completed.stdout.strip() or completed.stderr.strip()
            raise RuntimeError(f"工具未返回有效 JSON: {detail}") from e

        if not isinstance(result, dict):
            raise RuntimeError(f"工具 run() 必须返回 dict，实际返回 {type(result).__name__}")

        return result

    @staticmethod
    def _resolve_working_dir(tool_dir: Path, working_dir: str) -> Path:
        base = tool_dir.resolve()
        candidate = Path(working_dir or ".")
        resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
        if resolved != base and base not in resolved.parents:
            raise ValueError("工具工作目录必须位于工具目录内")
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _execute_http(self, executor: dict, params: dict) -> dict:
        method = executor.get("method", "POST").upper()
        url = executor.get("url", "")
        headers = executor.get("headers", {})
        body_template = executor.get("body_template", "")

        if not url:
            raise ValueError("HTTP executor requires url")

        body = self._render_template(body_template, params)

        async def _do_request() -> dict:
            import httpx

            kwargs = {"headers": headers}
            if method in ("POST", "PUT", "PATCH") and body:
                try:
                    kwargs["json"] = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    kwargs["content"] = body

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                try:
                    return resp.json()
                except (json.JSONDecodeError, ValueError):
                    return {"status_code": resp.status_code, "text": resp.text}

        try:
            return asyncio.run(_do_request())
        except Exception as e:
            raise RuntimeError(f"HTTP 请求失败: {e}") from e

    @staticmethod
    def _render_template(template: str, params: dict) -> str:
        if not template:
            return ""

        def replacer(match):
            key = match.group(1).strip()
            value = params.get(key, "")
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return re.sub(r"\{\{(\w+)\}\}", replacer, template)


tool_registry = ToolRegistry()
