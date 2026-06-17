"""
Visual 轨渲染器

处理 visual 轨的三种类型：
1. type: "remotion" → 调用 Remotion 渲染 Visual composition
2. type: "image"     → FFmpeg Ken Burns 效果
3. type: "video_clip" → FFmpeg 截取视频片段

最终输出：每个脚本一个 visual MP4 视频（1080x1920，不透明）
"""
import json
import logging
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

REMOTION_DIR = Path(__file__).parent.parent.parent / "remotion"
FPS = 30


def ms_to_frames(ms: int) -> int:
    return round(ms / 1000 * FPS)


def render_visual_remotion(
    script: dict,
    output_path: Path,
    remotion_dir: Path = REMOTION_DIR,
    timeout: int = 3600,
) -> Path | None:
    """
    渲染 visual 轨中 type=remotion 的条目为不透明 MP4
    """
    tracks = script.get("tracks", {})
    visual_items = tracks.get("visual", [])
    remotion_items = [v for v in visual_items if v.get("type") == "remotion"]

    if not remotion_items:
        return None

    total_ms = script.get("total_duration_ms", 30000)
    total_frames = ms_to_frames(total_ms)

    # 提取背景色
    bg_tracks = tracks.get("background", [])
    bg_colors = ["#0f0f23", "#1a1a3e"]
    if bg_tracks and bg_tracks[0].get("colors"):
        bg_colors = bg_tracks[0]["colors"]

    input_props = {
        "visualItems": remotion_items,
        "background": bg_colors,
    }

    props_file = output_path.with_suffix(".props.json")
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(input_props, f, ensure_ascii=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "Visual",
        f"--props={props_file.resolve()}",
        "--codec=h264",
        f"--output={output_path.resolve()}",
        f"--frames=0-{total_frames - 1}",
    ]

    logger.info(
        f"[visual] Remotion 渲染: {len(remotion_items)} items, "
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
            logger.info(f"[visual] ✅ {output_path.name}")
            return output_path
        else:
            logger.error(f"[visual] ❌ 渲染失败:\n{result.stderr[:500]}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"[visual] ⏰ 超时 ({timeout}s)")
        return None
    except Exception as e:
        logger.error(f"[visual] 💥 异常: {e}")
        return None


def render_visual_image(
    item: dict,
    output_path: Path,
    timeout: int = 30,
) -> Path | None:
    """
    将图片渲染为带 Ken Burns 效果的视频片段
    """
    source = item.get("source", "")
    duration_ms = item.get("duration_ms", 5000)
    duration_s = duration_ms / 1000.0

    if not source or not Path(source).exists():
        logger.warning(f"[visual] 图片不存在: {source}")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Ken Burns: 从 1.0 缩放到 1.15，同时轻微平移
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(source),
        "-vf", (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0005,1.15)':d={int(duration_s * FPS)}:s=1080x1920:fps={FPS},"
            f"format=yuv420p"
        ),
        "-t", str(duration_s),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-an",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            logger.info(f"[visual] ✅ image: {output_path.name}")
            return output_path
        else:
            logger.error(f"[visual] ❌ image: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.error(f"[visual] 💥 image: {e}")
        return None


def _fuzzy_find_source(source: str) -> str | None:
    """当精确路径不存在时，在同级目录模糊匹配最相似的路径"""
    source_path = Path(source)
    # 尝试找 video.mp4 的父目录的父目录（media 目录）
    if source_path.name == "video.mp4":
        topic_dir = source_path.parent
        media_dir = topic_dir.parent
    else:
        media_dir = source_path.parent
        topic_dir = source_path

    if not media_dir.exists():
        return None

    target_name = topic_dir.name
    best_match = None
    best_score = 0

    for candidate in media_dir.iterdir():
        if not candidate.is_dir():
            continue
        name = candidate.name
        # 计算公共前缀长度作为相似度
        common = 0
        for a, b in zip(target_name, name):
            if a == b:
                common += 1
            else:
                break
        # 也检查目标名是否是候选名的子串
        if target_name in name:
            common = len(target_name)
        if common > best_score and common >= len(target_name) * 0.6:
            best_score = common
            best_match = candidate

    if best_match:
        # 重建完整路径
        if source_path.name == "video.mp4":
            resolved = best_match / "video.mp4"
        else:
            resolved = best_match
        if resolved.exists():
            return str(resolved)
    return None


def render_visual_video_clip(
    item: dict,
    output_path: Path,
    timeout: int = 60,
) -> Path | None:
    """
    截取视频片段并缩放到 1080x1920
    """
    source = item.get("source", "")
    duration_ms = item.get("duration_ms", 5000)
    duration_s = duration_ms / 1000.0
    time_range = item.get("time_range", [0, duration_s])

    if not source or not Path(source).exists():
        # 尝试模糊匹配
        resolved = _fuzzy_find_source(source) if source else None
        if resolved:
            logger.info(f"[visual] 模糊匹配: {source} -> {resolved}")
            source = resolved
        else:
            logger.warning(f"[visual] 视频不存在: {source}")
            return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_s = time_range[0] if isinstance(time_range, list) and len(time_range) > 0 else 0
    
    # 如果 time_range 指定了结束时间，用它来限制 duration
    if isinstance(time_range, list) and len(time_range) >= 2:
        range_dur = time_range[1] - time_range[0]
        duration_s = min(duration_s, range_dur)
    
    # fade 参数
    fade_in = 0.3
    fade_out_start = max(0, duration_s - 0.5)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_s),
        "-i", str(source),
        "-t", str(duration_s),
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"fade=t=in:st=0:d={fade_in},"
            f"fade=t=out:st={fade_out_start}:d=0.5,"
            "format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-an",
        str(output_path),
    ]

    # 处理 mute_ranges（静音某些片段） - 暂不实现
    # 动态超时：基于视频时长
    dynamic_timeout = max(timeout, int(duration_s) + 60)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=dynamic_timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            logger.info(f"[visual] ✅ clip: {output_path.name}")
            return output_path
        else:
            logger.error(f"[visual] ❌ clip: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.error(f"[visual] 💥 clip: {e}")
        return None


def _generate_black_segment(
    duration_ms: int,
    output_path: Path,
    bg_color: str = "0x0f0f23",
) -> Path | None:
    """生成指定时长的纯色段（填充时间间隔）"""
    duration_s = duration_ms / 1000.0
    if duration_s < 0.05:
        return None
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c={bg_color}:s=1080x1920:d={duration_s}:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "mpegts",
        str(output_path),
    ]
    try:
        subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except Exception:
        pass
    return None


def concat_visual_segments(
    segments: list[tuple[int, Path]],
    total_ms: int,
    output_path: Path,
    bg_color: str = "0x0f0f23",
    timeout: int = 120,
) -> Path | None:
    """
    将多个视频片段按时间轴拼接为完整的 visual 视频
    segments: [(start_ms, segment_path), ...]
    使用 TS concat，在段之间插入黑场保持时间对齐
    """
    if not segments:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_s = total_ms / 1000.0

    # 如果只有一个 segment 且从 0 开始，直接用
    if len(segments) == 1 and segments[0][0] == 0:
        import shutil
        shutil.copy2(segments[0][1], output_path)
        return output_path

    # 排序 segments 按 start_ms
    segments_sorted = sorted(segments, key=lambda x: x[0])
    
    # Step 1: 将每个 segment 转为 TS，并在间隔处插入黑场
    ts_files = []
    current_ms = 0
    gap_idx = 0
    
    for idx, (start_ms, seg_path) in enumerate(segments_sorted):
        # 如果有间隔 > 100ms，插入黑场
        gap = start_ms - current_ms
        if gap > 100:
            gap_path = output_path.parent / f".ts_gap_{output_path.stem}_{gap_idx:03d}.ts"
            gap_result = _generate_black_segment(gap, gap_path, bg_color)
            if gap_result:
                ts_files.append(gap_result)
            gap_idx += 1
        
        # 转换片段为 TS
        ts_path = output_path.parent / f".ts_tmp_{output_path.stem}_{idx:03d}.ts"
        ts_cmd = [
            "ffmpeg", "-y",
            "-i", str(seg_path),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-r", "30",
            "-vf", "fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0f0f23,format=yuv420p",
            "-an",
            "-bsf:v", "h264_mp4toannexb",
            "-f", "mpegts",
            str(ts_path),
        ]
        try:
            # 动态超时：基于源文件可能的时长
            seg_timeout = max(60, int((segments_sorted[idx][0] + 500000 - start_ms) / 1000) + 60)
            # 先用 ffprobe 获取源片段时长
            try:
                probe_dur = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(seg_path)],
                    capture_output=True, text=True, timeout=10,
                )
                seg_dur_s = float(probe_dur.stdout.strip())
                seg_timeout = max(60, int(seg_dur_s) + 60)
            except Exception:
                pass
            
            subprocess.run(
                ts_cmd, capture_output=True, text=True,
                timeout=seg_timeout, encoding="utf-8", errors="replace",
            )
            if ts_path.exists() and ts_path.stat().st_size > 0:
                ts_files.append(ts_path)
                # 用实际片段时长更新 current_ms
                # 获取片段实际时长
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(seg_path)],
                    capture_output=True, text=True, timeout=10,
                )
                try:
                    seg_dur_ms = int(float(probe.stdout.strip()) * 1000)
                except (ValueError, AttributeError):
                    seg_dur_ms = segments_sorted[idx][0] + 5000 - start_ms  # fallback
                current_ms = start_ms + seg_dur_ms
            else:
                logger.warning(f"[visual] TS 转换失败: seg_{idx}")
                current_ms = start_ms
        except Exception as e:
            logger.warning(f"[visual] TS 转换异常: {e}")
            current_ms = start_ms

    if not ts_files:
        logger.error("[visual] 无有效 TS 片段")
        return None

    # Step 2: 用 concat 协议拼接所有 TS
    concat_input = "concat:" + "|".join(str(f) for f in ts_files)
    
    # 动态超时：基于时长
    dynamic_timeout = max(timeout, int(duration_s) + 60)

    cmd = [
        "ffmpeg", "-y",
        "-i", concat_input,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-r", "30",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration_s),
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=dynamic_timeout,
            encoding="utf-8",
            errors="replace",
        )
        # 清理 TS 临时文件
        for ts in ts_files:
            ts.unlink(missing_ok=True)
            
        if result.returncode == 0:
            return output_path
        else:
            logger.error(f"[visual] ❌ concat: {result.stderr[:300]}")
            return None
    except Exception as e:
        logger.error(f"[visual] 💥 concat: {e}")
        return None


def render_script_visual(
    script: dict,
    output_dir: Path,
) -> Path | None:
    """
    渲染单个脚本的完整 visual 轨视频

    策略：
    - 如果全是 remotion 类型 → 直接用 Remotion 渲染一个完整 MP4
    - 如果混合类型 → 分段渲染再拼接
    """
    script_id = script.get("id", "unknown")
    tracks = script.get("tracks", {})
    visual_items = tracks.get("visual", [])
    overlay_items = tracks.get("overlay", [])
    total_ms = script.get("total_duration_ms", 30000)

    if not visual_items:
        logger.info(f"[visual] {script_id}: 无 visual 轨")
        return None

    # 过滤掉跟 overlay 重复的 highlight_text（避免双层显示）
    overlay_set = set()
    for ov in overlay_items:
        if ov.get("type") == "highlight_text":
            key = (ov.get("start_ms", 0), ov.get("props", {}).get("text", ""))
            overlay_set.add(key)
    
    filtered_items = []
    for v in visual_items:
        if (v.get("type") == "remotion" and 
            v.get("component") == "highlight_text"):
            key = (v.get("start_ms", 0), v.get("props", {}).get("text", ""))
            if key in overlay_set:
                logger.debug(f"[visual] 跳过重复 highlight: {key[1]} @{key[0]}ms")
                continue
        filtered_items.append(v)
    
    if len(filtered_items) < len(visual_items):
        logger.info(f"[visual] {script_id}: 过滤 {len(visual_items) - len(filtered_items)} 个重复 highlight_text")
    visual_items = filtered_items

    output_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否全部是 remotion
    types = set(v.get("type") for v in visual_items)

    if types == {"remotion"}:
        # 全部 remotion → 已合并到 overlay 渲染，无需单独生成 visual.mp4
        logger.info(f"[visual] {script_id}: 全 remotion，已合并到 overlay，跳过")
        return None

    # 混合类型 → 分段处理
    segments = []
    tmp_dir = output_dir / f".tmp_{script_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for i, item in enumerate(visual_items):
        item_type = item.get("type", "")
        start_ms = item.get("start_ms", 0)
        seg_path = tmp_dir / f"seg_{i:02d}.mp4"

        if item_type == "image":
            result = render_visual_image(item, seg_path)
        elif item_type == "video_clip":
            result = render_visual_video_clip(item, seg_path)
        elif item_type == "remotion":
            # 单个 remotion 片段 → 小的 Remotion 渲染
            mini_script = {
                "id": f"{script_id}_seg{i}",
                "total_duration_ms": item.get("duration_ms", 5000),
                "tracks": {
                    "visual": [dict(item, start_ms=0)],
                    "background": tracks.get("background", []),
                },
            }
            result = render_visual_remotion(mini_script, seg_path)
        else:
            logger.warning(f"[visual] 未知类型: {item_type}")
            result = None

        if result:
            segments.append((start_ms, result))

    if not segments:
        logger.warning(f"[visual] {script_id}: 所有分段渲染失败")
        return None

    # 拼接
    output_path = output_dir / f"{script_id}_visual.mp4"
    bg_tracks = tracks.get("background", [])
    bg_color = "0x0f0f23"
    if bg_tracks and bg_tracks[0].get("colors"):
        c = bg_tracks[0]["colors"][0]
        bg_color = "0x" + c.lstrip("#")

    result = concat_visual_segments(segments, total_ms, output_path, bg_color)

    # 清理临时文件
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return result
