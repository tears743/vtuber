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
    overlay_items = list(tracks.get("overlay", []))

    # 合并 visual 轨中 type=remotion 的条目（stats_card/code_scroll/info_panel 等）
    # 通过时间碰撞检测避免重复：如果 overlay 轨已有同时间段的组件则跳过
    visual_items = tracks.get("visual", [])

    # 构建 overlay 轨已有时间区间集合（含组件类型）
    existing_intervals = []
    for ov in overlay_items:
        s = ov.get("start_ms", 0)
        e = s + ov.get("duration_ms", 0)
        ov_type = ov.get("type", "")
        existing_intervals.append((s, e, ov_type))

    def _has_same_component(start_ms: int, duration_ms: int, component: str) -> bool:
        """检查是否与已有 overlay 中相同类型的组件时间重叠"""
        end_ms = start_ms + duration_ms
        for (es, ee, et) in existing_intervals:
            if start_ms < ee and end_ms > es and et == component:
                return True
        return False

    for vis in visual_items:
        if vis.get("type") == "remotion" and vis.get("component"):
            vis_start = vis.get("start_ms", 0)
            vis_dur = vis.get("duration_ms", 5000)
            vis_component = vis.get("component", "")
            # 只有同类型组件时间重叠才跳过（避免重复渲染同一效果）
            if _has_same_component(vis_start, vis_dur, vis_component):
                logger.debug(
                    f"[remotion] 跳过 visual 轨 {vis_component} "
                    f"({vis_start}ms) — overlay 轨已有同类型组件"
                )
                continue
            # 转换为 overlay 格式: component → type
            # position 兼容: 优先从 props 内读取，fallback 到外层
            vis_position = vis.get("props", {}).get("position") or vis.get("position")
            overlay_item = {
                "start_ms": vis_start,
                "duration_ms": vis_dur,
                "type": vis["component"],
                "props": vis.get("props", {}),
                "style": vis.get("style"),
                "scale": vis.get("scale"),
                "position": vis_position,
                "offsetX": vis.get("offsetX"),
                "offsetY": vis.get("offsetY"),
            }
            # 移除 None 值
            overlay_item = {k: v for k, v in overlay_item.items() if v is not None}
            overlay_items.append(overlay_item)
            # 更新区间集合
            existing_intervals.append((vis_start, vis_start + vis_dur, vis_component))
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
