import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import sys
import traceback
from pathlib import Path


def _load_run_function(run_file: Path):
    spec = importlib.util.spec_from_file_location("_videofactory_tool_run", run_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load tool module: {run_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_fn = getattr(module, "run", None)
    if run_fn is None:
        raise AttributeError(f"run.py does not define run(params): {run_file}")
    return run_fn


async def _call_run(run_fn, params: dict):
    result = run_fn(params)
    if inspect.isawaitable(result):
        result = await result
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python_runner.py <run.py>", file=sys.stderr)
        return 2

    run_file = Path(sys.argv[1]).resolve()
    try:
        params = json.loads(sys.stdin.read() or "{}")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            run_fn = _load_run_function(run_file)
            result = asyncio.run(_call_run(run_fn, params))

        logs = captured.getvalue()
        if logs:
            print(logs, file=sys.stderr, end="")

        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
