import hashlib
import json
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return {
            k: _json_default(v)
            for k, v in value.__dict__.items()
            if not k.startswith("_")
        }
    if isinstance(value, dict):
        return {str(k): _json_default(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_default(v) for v in value]
    return repr(value)


def stable_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class NodeCacheManager:
    def __init__(self, data_root: Path, date: str, workflow_id: str):
        self.data_root = Path(data_root)
        self.date = date
        self.workflow_id = workflow_id or "unknown"
        self.root = self.data_root / self.date / ".node_cache" / self.workflow_id

    def config_hash(self, node) -> str:
        config = node.config or {}
        cache_revision = getattr(node, "cache_revision", None)
        if cache_revision is None:
            return stable_hash(config)
        return stable_hash({"config": config, "cache_revision": cache_revision})

    def input_hash(self, ctx) -> str:
        summary = {
            "data": {
                key: {
                    "type": type(value).__name__,
                    "value": _json_default(value),
                }
                for key, value in sorted(ctx.data.items(), key=lambda item: item[0])
            },
            "legacy": {
                key: {
                    "type": type(value).__name__,
                    "value": _json_default(value),
                }
                for key, value in sorted(ctx._legacy_fields.items(), key=lambda item: item[0])
            },
        }
        return stable_hash(summary)

    def cache_key(self, node, ctx, edges: list[dict]) -> str:
        relevant_edges = [
            edge for edge in edges
            if edge.get("target") == node.id or edge.get("source") == node.id
        ]
        return stable_hash(
            {
                "node_type": node.type,
                "config_hash": self.config_hash(node),
                "input_hash": self.input_hash(ctx),
                "edges": relevant_edges,
            }
        )

    def node_dir(self, node_id: str) -> Path:
        return self.root / node_id

    def cache_dir(self, node_id: str, cache_key: str) -> Path:
        return self.node_dir(node_id) / cache_key

    def latest_cache_dir(self, node) -> Path | None:
        base = self.node_dir(node.id)
        if not base.exists():
            return None
        cfg_hash = self.config_hash(node)
        candidates = []
        for child in base.iterdir():
            manifest_path = child / "manifest.json"
            output_path = child / "output.pkl"
            if not manifest_path.exists() or not output_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if manifest.get("config_hash") == cfg_hash:
                candidates.append((manifest.get("created_at", ""), child))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def restore(self, node, ctx, cache_dir: Path) -> bool:
        manifest_path = cache_dir / "manifest.json"
        output_path = cache_dir / "output.pkl"
        if not manifest_path.exists() or not output_path.exists():
            return False

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("files", []):
            original = Path(item.get("original", ""))
            cached = cache_dir / item.get("cached", "")
            if cached.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                if cached.is_dir():
                    if original.exists():
                        shutil.rmtree(original)
                    shutil.copytree(cached, original)
                else:
                    shutil.copy2(cached, original)

        with output_path.open("rb") as f:
            payload = pickle.load(f)

        for name, value in (payload.get("outputs") or {}).items():
            ctx.write(node.id, name, value)
        for name, value in (payload.get("legacy_fields") or {}).items():
            ctx._legacy_fields[name] = value
            ctx.data[f"_legacy:{name}"] = value
        return True

    def save(self, node, ctx, cache_key: str, outputs: dict | None, edges: list[dict]) -> None:
        cache_dir = self.cache_dir(node.id, cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)
        outputs = outputs or {}
        legacy_fields = {
            name: ctx._legacy_fields[name]
            for name in getattr(node, "writes", []) or []
            if name in ctx._legacy_fields
        }

        with (cache_dir / "output.pkl").open("wb") as f:
            pickle.dump({"outputs": outputs, "legacy_fields": legacy_fields}, f)

        copied_files = self._copy_output_files(node, ctx, cache_dir)
        manifest = {
            "workflow_id": self.workflow_id,
            "node_id": node.id,
            "node_type": node.type,
            "cache_key": cache_key,
            "config_hash": self.config_hash(node),
            "input_hash": self.input_hash(ctx),
            "created_at": datetime.now().isoformat(),
            "outputs": list(outputs.keys()),
            "legacy_fields": list(legacy_fields.keys()),
            "output_dirs": list(getattr(node, "output_dirs", []) or []),
            "edges": [
                edge for edge in edges
                if edge.get("source") == node.id or edge.get("target") == node.id
            ],
            "files": copied_files,
        }
        (cache_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _copy_output_files(self, node, ctx, cache_dir: Path) -> list[dict]:
        copied = []
        files_root = cache_dir / "files"
        for dir_name in getattr(node, "output_dirs", []) or []:
            src = ctx.data_root / ctx.date / dir_name
            if not src.exists():
                continue
            dest = files_root / dir_name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            copied.append({"original": str(src), "cached": str(dest.relative_to(cache_dir))})
        return copied

    def clear_node(self, node_id: str) -> int:
        path = self.node_dir(node_id)
        if not path.exists():
            return 0
        count = sum(1 for child in path.iterdir() if child.is_dir())
        shutil.rmtree(path)
        return count
