"""
Remotion 渲染器 — 将脚本 overlay 轨渲染为透明 WebM 视频

流程：
1. 读取脚本 JSON 的 overlay 轨
2. 构建 Remotion inputProps
3. 调用 npx remotion render 渲染 WebM（透明背景）
4. 返回输出文件路径
"""
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REMOTION_DIR = Path(__file__).parent.parent.parent / "remotion"
FPS = 30


def ms_to_frames(ms: int) -> int:
    return round(ms / 1000 * FPS)


def normalize_remotion_item(item: dict, overlay: bool = False) -> dict:
    """Normalize LLM-generated props before they reach strict React components."""
    normalized = dict(item or {})
    component = normalized.get("component") or normalized.get("type") or ""
    if overlay and normalized.get("type") == "remotion" and normalized.get("component"):
        normalized["type"] = normalized["component"]
    props = dict(normalized.get("props") or {})

    for key in (
        "name", "stars", "forks", "language", "description", "downloads",
        "task", "title", "value", "unit", "text", "sub_text", "source",
        "code", "color", "accent_color",
    ):
        if key in props and props[key] is not None:
            props[key] = str(props[key])

    for key in ("points", "items"):
        value = props.get(key)
        if component in {"info_panel", "remotion"} and value is not None:
            if not isinstance(value, list):
                value = [value]
            props[key] = [str(entry) for entry in value]

    if component == "ranking_table":
        rows = props.get("items") if isinstance(props.get("items"), list) else []
        props["items"] = [
            {
                "rank": int(row.get("rank", index + 1) or index + 1),
                "name": str(row.get("name", "")),
                "value": str(row.get("value", "")),
            }
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]

    if component == "comment_scroll":
        comments = props.get("comments") if isinstance(props.get("comments"), list) else []
        props["comments"] = [
            {
                **comment,
                "user": str(comment.get("user", "")),
                "text": str(comment.get("text", "")),
                "likes": int(comment.get("likes", 0) or 0),
            }
            if isinstance(comment, dict)
            else {"user": "", "text": str(comment), "likes": 0}
            for comment in comments
        ]

    normalized["props"] = props
    return normalized


def render_overlay(
    script: dict,
    output_path: Path,
    remotion_dir: Path = REMOTION_DIR,
    timeout: int = 3600,
) -> Path | None:
    """
    渲染脚本的 overlay 轨为透明背景 WebM

    Args:
        script: 脚本 JSON dict（含 tracks.overlay）
        output_path: 输出 .webm 文件路径
        remotion_dir: Remotion 项目目录
        timeout: 渲染超时（秒）

    Returns:
        输出文件路径，或 None（渲染失败）
    """
    tracks = script.get("tracks", {})
    overlay_items = [normalize_remotion_item(item, overlay=True) for item in tracks.get("overlay", [])]

    # Remotion components are transparent presentation layers. Keeping them in
    # Overlay preserves the studio and the full-size presenter underneath.
    visual_items = tracks.get("visual", [])
    existing_items = {
        (
            item.get("start_ms", 0),
            item.get("duration_ms", 0),
            item.get("type", ""),
            json.dumps(item.get("props") or {}, ensure_ascii=False, sort_keys=True, default=str),
        )
        for item in overlay_items
    }
    for item in visual_items:
        if item.get("type") != "remotion":
            continue
        normalized = normalize_remotion_item(item, overlay=True)
        identity = (
            normalized.get("start_ms", 0),
            normalized.get("duration_ms", 0),
            normalized.get("type", ""),
            json.dumps(normalized.get("props") or {}, ensure_ascii=False, sort_keys=True, default=str),
        )
        if identity not in existing_items:
            overlay_items.append(normalized)
            existing_items.add(identity)

    # 自动注入 author_tag：扫描 visual 轨中有 author 字段的 video_clip/image 段
    # 为每段生成 author_tag overlay（Remotion 渲染中文无乱码）
    for vis in visual_items:
        vtype = vis.get("type", "")
        author = vis.get("author", "")
        if vtype in ("video_clip", "image") and author:
            vis_start = vis.get("start_ms", 0)
            vis_dur = vis.get("duration_ms", 5000)
            # author_tag 不参与碰撞检测（它是小标签，不会遮挡其他 overlay）
            author_text = author if author.startswith("@") else f"@{author}"
            overlay_items.append({
                "start_ms": vis_start,
                "duration_ms": vis_dur,
                "type": "author_tag",
                "position": "bottom-left",
                "props": {
                    "text": author_text,
                    "position": "bottom-left",
                },
            })

    if not overlay_items:
        logger.info("[remotion] 无 overlay 轨，跳过渲染")
        return None

    total_ms = script.get("total_duration_ms", 30000)
    total_frames = ms_to_frames(total_ms)

    # 碰撞检测 & 自动修正
    from agents.renderer.layout_validator import LayoutValidator
    validator = LayoutValidator()
    overlay_items = validator.validate_and_fix(overlay_items)

    # 构建 inputProps，写入临时文件（Windows 命令行引号转义有问题）
    input_props = {
        "overlayItems": overlay_items,
    }

    props_file = output_path.with_suffix(".props.json")
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(input_props, f, ensure_ascii=False)

    # 构建渲染命令
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "Overlay",
        f"--props={props_file.resolve()}",
        "--codec=vp9",
        "--pixel-format=yuva420p",
        "--image-format=png",
        f"--output={output_path.resolve()}",
        f"--frames=0-{total_frames - 1}",
    ]

    logger.info(
        f"[remotion] 渲染 overlay: {len(overlay_items)} items, "
        f"{total_frames} frames -> {output_path.name}"
    )

    # 动态超时：按帧数估算（约 15 帧/秒渲染速度），最少 120s
    dynamic_timeout = max(120, int(total_frames / 15) + 60)
    actual_timeout = max(timeout, dynamic_timeout)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(remotion_dir),
            capture_output=True,
            text=True,
            timeout=actual_timeout,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )

        if result.returncode == 0:
            logger.info(f"[remotion] ✅ 渲染完成: {output_path}")
            return output_path
        else:
            logger.error(f"[remotion] ❌ 渲染失败:\n{result.stderr[:500]}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"[remotion] ⏰ 渲染超时 ({timeout}s)")
        return None
    except Exception as e:
        logger.error(f"[remotion] 💥 渲染异常: {e}")
        return None


def render_script_overlay(
    script_path: Path,
    output_dir: Path,
) -> Path | None:
    """
    读取脚本文件 → 渲染 overlay → 返回 WebM 路径
    """
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    script_id = script.get("id", script_path.stem)
    output_path = output_dir / f"{script_id}_overlay.webm"

    return render_overlay(script, output_path)


def render_all_overlays(
    scripts_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """
    批量渲染所有脚本的 overlay 层

    Returns:
        {script_id: webm_path}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    script_files = sorted(scripts_dir.glob("*.json"))
    logger.info(f"[remotion] 批量渲染 {len(script_files)} 个脚本的 overlay")

    for script_path in script_files:
        webm_path = render_script_overlay(script_path, output_dir)
        if webm_path:
            results[script_path.stem] = webm_path

    logger.info(f"[remotion] 批量渲染完成: {len(results)}/{len(script_files)}")
    return results
