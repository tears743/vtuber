"""
Renderer 入口脚本 - Phase 3: 视频渲染管线

Usage:
    python -m agents.renderer.run_render --step download    # 素材下载
    python -m agents.renderer.run_render --step recognize   # 图片识别
    python -m agents.renderer.run_render --step transcribe  # 视频音频转文字
    python -m agents.renderer.run_render --step tts         # TTS 生成
    python -m agents.renderer.run_render --step align       # Timeline 对齐
    python -m agents.renderer.run_render --step render      # 素材渲染
    python -m agents.renderer.run_render --step compose     # 最终合成
    python -m agents.renderer.run_render --all              # 全部执行
"""
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config_loader import load_config, get_model_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def step_download(config: dict, today: str, data_root: Path):
    """Step 0: 素材下载"""
    from agents.renderer.media_downloader import MediaDownloader
    
    collected_dir = data_root / today / "collected"
    media_dir = data_root / today / "media"
    
    opencli = config.get("opencli", {}).get("binary", "opencli")
    
    downloader = MediaDownloader(opencli_binary=opencli)
    manifest = downloader.download_all(collected_dir, media_dir)
    
    logger.info(f"[render] 素材下载完成: {len(manifest)} 条有素材")
    return manifest


def step_recognize(config: dict, today: str, data_root: Path):
    """Step 0.5: 素材识别 (mimo-v2.5-pro vision)"""
    from agents.renderer.media_recognizer import MediaRecognizer
    
    media_dir = data_root / today / "media"
    manifest_path = media_dir / "manifest.json"
    
    if not manifest_path.exists():
        logger.error("[render] manifest.json 不存在，请先执行 --step download")
        return None
    
    # 从 config 获取 mimo-v2.5 配置（支持 vision）
    mimo_cfg = config.get("models", {}).get("mimo-v2.5", {})
    if not mimo_cfg:
        logger.error("[render] config.yaml 中未找到 mimo-v2.5 配置")
        return None
    
    recognizer = MediaRecognizer(
        base_url=mimo_cfg["base_url"],
        api_key=mimo_cfg["api_key"],
        model=mimo_cfg["model"],
    )
    
    manifest = recognizer.recognize_all(media_dir, manifest_path)
    logger.info(f"[render] 素材识别完成")
    return manifest


def step_transcribe(config: dict, today: str, data_root: Path):
    """Step 0.6: 视频音频转文字 (faster-whisper)"""
    from agents.renderer.audio_transcriber import AudioTranscriber
    
    media_dir = data_root / today / "media"
    manifest_path = media_dir / "manifest.json"
    
    if not manifest_path.exists():
        logger.warning("[render] manifest.json 不存在，跳过 transcribe")
        return
    
    transcriber = AudioTranscriber(
        model_size="large-v3",
        language="zh",
        hf_token=config.get("hf_token", ""),
    )
    
    manifest = transcriber.transcribe_all(media_dir, manifest_path)
    logger.info(f"[render] 音频转录完成")
    return manifest


def step_tts(config: dict, today: str, data_root: Path):
    """Step 1: TTS 生成"""
    from agents.renderer.tts import VoxCPMTTS
    
    scripts_dir = data_root / today / "scripts"
    audio_dir = data_root / today / "audio"
    
    # TTS 配置
    tts_cfg = config.get("tts", {}).get("voxcpm", {})
    tts = VoxCPMTTS(
        url=tts_cfg.get("url", "http://127.0.0.1:8808"),
        dialect=tts_cfg.get("dialect", "四川话"),
        speed=tts_cfg.get("speed", "快"),
    )
    
    # 检查服务
    if not tts.check_health():
        logger.error("[render] VoxCPM TTS 服务不可用! 请先启动: scripts/start_tts.bat")
        return None
    
    logger.info("[render] VoxCPM TTS 服务已连接")
    
    # 为每个脚本生成 TTS
    all_durations = {}
    scripts = sorted(scripts_dir.glob("*.json"))
    
    for i, script_path in enumerate(scripts):
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        
        script_id = script.get("id", script_path.stem)
        script_audio_dir = audio_dir / script_id
        
        logger.info(f"[render] [{i+1}/{len(scripts)}] TTS: {script_id}")
        durations = tts.synthesize_script(script, script_audio_dir)
        all_durations[script_id] = durations
    
    # 保存 durations 索引
    durations_path = audio_dir / "durations.json"
    audio_dir.mkdir(parents=True, exist_ok=True)
    with open(durations_path, "w", encoding="utf-8") as f:
        json.dump(all_durations, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[render] TTS 完成: {len(all_durations)} 个脚本")
    return all_durations


def step_align(config: dict, today: str, data_root: Path):
    """Step 2: Timeline 对齐"""
    from agents.renderer.realigner import realign_script_file
    
    scripts_dir = data_root / today / "scripts"
    audio_dir = data_root / today / "audio"
    aligned_dir = data_root / today / "scripts_aligned"
    
    # 加载 durations
    durations_path = audio_dir / "durations.json"
    if not durations_path.exists():
        logger.error("[render] durations.json 不存在，请先执行 --step tts")
        return
    
    with open(durations_path, "r", encoding="utf-8") as f:
        all_durations = json.load(f)
    
    aligned_dir.mkdir(parents=True, exist_ok=True)
    
    for script_path in sorted(scripts_dir.glob("*.json")):
        script_id = script_path.stem
        durations = all_durations.get(script_id, {})
        
        # JSON key 是 string，转 int
        durations_int = {int(k): v for k, v in durations.items()}
        
        output_path = aligned_dir / script_path.name
        realign_script_file(script_path, durations_int, output_path)
    
    logger.info(f"[render] Timeline 对齐完成 -> {aligned_dir}")


def step_render(config: dict, today: str, data_root: Path):
    """Step 3: Overlay 渲染 (Remotion WebM) — 并发"""
    from agents.renderer.remotion_renderer import render_overlay
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 优先用对齐后的脚本，否则用原始脚本
    aligned_dir = data_root / today / "scripts_aligned"
    scripts_dir = aligned_dir if aligned_dir.exists() else data_root / today / "scripts"

    overlay_dir = data_root / today / "overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    script_files = sorted(scripts_dir.glob("*.json"))
    logger.info(f"[render] Remotion overlay 渲染: {len(script_files)} 个脚本 (并发)")

    # 准备任务列表
    tasks = []
    for script_path in script_files:
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        script_id = script.get("id", script_path.stem)
        output_path = overlay_dir / f"{script_id}_overlay.webm"
        tasks.append((script, output_path, script_id))

    max_workers = config.get("render", {}).get("workers", 4)
    success = 0
    skipped = 0
    failed = 0

    def _render_one(args):
        script, output_path, script_id = args
        result = render_overlay(script, output_path)
        return script_id, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_render_one, t): t[2] for t in tasks}
        for future in as_completed(futures):
            script_id = futures[future]
            try:
                sid, result = future.result()
                if result:
                    success += 1
                    logger.info(f"[render] ✅ {sid}")
                else:
                    skipped += 1
                    logger.info(f"[render] ⏭️ {sid} (无overlay/失败)")
            except Exception as e:
                failed += 1
                logger.error(f"[render] ❌ {script_id}: {e}")

    logger.info(f"[render] Overlay 渲染完成: {success} 成功, {skipped} 跳过, {failed} 失败")


def step_visual(config: dict, today: str, data_root: Path):
    """Step 3b: Visual 轨渲染"""
    from agents.renderer.visual_renderer import render_script_visual
    from concurrent.futures import ThreadPoolExecutor, as_completed

    aligned_dir = data_root / today / "scripts_aligned"
    scripts_dir = aligned_dir if aligned_dir.exists() else data_root / today / "scripts"

    visual_dir = data_root / today / "visual"
    visual_dir.mkdir(parents=True, exist_ok=True)

    script_files = sorted(scripts_dir.glob("*.json"))
    logger.info(f"[render] Visual 轨渲染: {len(script_files)} 个脚本 (并发)")

    tasks = []
    for script_path in script_files:
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        tasks.append((script, visual_dir))

    max_workers = config.get("render", {}).get("workers", 4)
    success = 0
    skipped = 0
    failed = 0

    def _render_one(args):
        script, out_dir = args
        result = render_script_visual(script, out_dir)
        return script.get("id", "?"), result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_render_one, t): t[0].get("id", "?") for t in tasks}
        for future in as_completed(futures):
            script_id = futures[future]
            try:
                sid, result = future.result()
                if result:
                    success += 1
                    logger.info(f"[visual] ✅ {sid}")
                else:
                    skipped += 1
                    logger.info(f"[visual] ⏭️ {sid} (无visual/失败)")
            except Exception as e:
                failed += 1
                logger.error(f"[visual] ❌ {script_id}: {e}")

    logger.info(f"[visual] 渲染完成: {success} 成功, {skipped} 跳过, {failed} 失败")


def step_live2d(config: dict, today: str, data_root: Path):
    """Step 3c: Live2D 口播渲染 (Remotion WebM + 口型同步)"""
    from agents.renderer.live2d_renderer import step_live2d as _step_live2d

    _step_live2d(today, max_workers=config.get("render", {}).get("workers", 2))


def step_compose(config: dict, today: str, data_root: Path, progress_callback=None):
    """Step 4: 最终合成 (FFmpeg) — 演播室模式 + 素材转场

    合成模式:
        - 演播室模式（默认）: studio_bg + live2d居中 + desk前景 + ticker + 顶部bar + overlay
        - 素材模式（image/video_clip）: 全屏素材 + live2d缩到角落 + overlay
        - 两种模式之间有 0.5s fade 转场
    """
    import subprocess

    logger.info("[render] Step 4: 最终合成 (演播室模式)")

    scripts_dir = data_root / today / "scripts_aligned"
    overlay_dir = data_root / today / "overlay"
    live2d_dir = data_root / today / "live2d"
    audio_dir = data_root / today / "audio"
    visual_dir = data_root / today / "visual"
    subtitle_dir = data_root / today / "subtitles"
    output_dir = data_root / today / "final"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 演播室素材路径
    project_root = Path(__file__).parent.parent.parent
    studio_bg = project_root / "assets" / "studio" / "bg_starry.png"
    studio_desk = project_root / "assets" / "studio" / "desk_foreground.png"

    if not studio_bg.exists():
        logger.error(f"[compose] 演播室背景不存在: {studio_bg}")
        return
    if not studio_desk.exists():
        logger.error(f"[compose] 演播台前景不存在: {studio_desk}")
        return

    script_files = sorted(scripts_dir.glob("*.json"))
    if not script_files:
        logger.warning("[compose] 无脚本文件")
        return

    success = 0
    failed_scripts = []
    for script_index, script_path in enumerate(script_files, start=1):
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        script_id = script.get("id", script_path.stem)
        output_mp4 = output_dir / f"{script_id}.mp4"

        # 图层或样式可能变化，最终视频必须重新合成，不能复用旧残缺产物。
        output_mp4.unlink(missing_ok=True)

        logger.info(f"[compose] 合成: {script_id}")
        if progress_callback:
            progress_callback(
                f"合成 [{script_index}/{len(script_files)}]: {script_id}",
                0.05 + 0.85 * (script_index - 1) / max(len(script_files), 1),
            )

        live2d_webm = live2d_dir / f"{script_id}_live2d.webm"
        overlay_webm = overlay_dir / f"{script_id}_overlay.webm"
        subtitle_ass = subtitle_dir / f"{script_id}.ass"

        # 合并 TTS 音频
        audio_seg_dir = audio_dir / script_id
        merged_audio = _merge_audio_segments(audio_seg_dir, script, output_dir / f"{script_id}_audio.wav")

        total_ms = script.get("total_duration_ms", 30000)
        duration_s = total_ms / 1000.0

        # 分析 visual 轨，找出素材段 (image/video_clip)
        tracks = script.get("tracks", {})
        visual_items = tracks.get("visual", [])
        material_items = [
            item for item in visual_items
            if item.get("type") in {"image", "video_clip"}
        ]
        remotion_items = [item for item in visual_items if item.get("type") == "remotion"]
        overlay_items = tracks.get("overlay", [])
        voice_items = tracks.get("voice", [])
        media_segments = []
        visual_intervals = []

        for vis in material_items:
            start_ms = int(vis.get("start_ms", 0) or 0)
            duration_ms = int(vis.get("duration_ms", 0) or 0)
            if duration_ms > 0:
                visual_intervals.append({
                    "start_s": start_ms / 1000.0,
                    "end_s": (start_ms + duration_ms) / 1000.0,
                })

        # 加载 manifest 用于 author fallback
        manifest_path = data_root / today / "media" / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        # 构建 source路径 → author 的映射（从 manifest）
        _path_to_author = {}
        for mkey, mval in manifest.items():
            m_author = mval.get("author", "")
            if m_author:
                # manifest key 是 json 文件名，对应的媒体目录名是 stem
                slug = mkey.replace(".json", "")
                _path_to_author[slug] = m_author

        for vis in visual_items:
            vtype = vis.get("type", "")
            if vtype in ("image", "video_clip"):
                start_ms = vis.get("start_ms", 0)
                dur_ms = vis.get("duration_ms", 5000)
                source = vis.get("source", "")
                if source and Path(source).exists():
                    # author: 优先用脚本中的，fallback 从 manifest 按路径匹配
                    author = vis.get("author", "")
                    if not author:
                        # 从 source 路径中提取 slug 来匹配 manifest author
                        source_parts = Path(source).parts
                        for part in source_parts:
                            if part in _path_to_author:
                                author = _path_to_author[part]
                                break
                    media_segments.append({
                        "start_s": start_ms / 1000.0,
                        "end_s": (start_ms + dur_ms) / 1000.0,
                        "type": vtype,
                        "source": source,
                        "play_audio": vis.get("play_audio", False),
                        "time_range": vis.get("time_range", []),
                        "author": author,
                    })

        # 检测预合成的 visual 视频（visual_renderer 输出）
        visual_mp4 = visual_dir / f"{script_id}_visual.mp4"
        if not material_items or not visual_mp4.exists():
            visual_mp4 = None

        missing_layers = []
        if (overlay_items or remotion_items) and not overlay_webm.exists():
            missing_layers.append("overlay")
        if material_items and visual_mp4 is None:
            missing_layers.append("visual")
        if voice_items and not subtitle_ass.exists():
            missing_layers.append("subtitles")
        if missing_layers:
            raise RuntimeError(
                f"{script_id} 缺少已声明的渲染图层: {', '.join(missing_layers)}"
            )

        # 构建 FFmpeg 命令
        def _compose_progress(message, local_progress):
            if not progress_callback:
                return
            local_progress = min(1.0, max(0.0, float(local_progress)))
            overall_progress = 0.05 + 0.85 * (
                (script_index - 1 + local_progress) / max(len(script_files), 1)
            )
            progress_callback(message, overall_progress)

        result = _compose_studio(
            studio_bg=studio_bg,
            studio_desk=studio_desk,
            live2d_webm=live2d_webm,
            overlay_webm=overlay_webm,
            subtitle_ass=subtitle_ass,

            merged_audio=merged_audio,
            media_segments=media_segments,
            visual_intervals=visual_intervals,
            visual_mp4=visual_mp4,
            duration_s=duration_s,
            output_mp4=output_mp4,
            script_id=script_id,
            today=today,
            progress_callback=_compose_progress,
        )

        if result:
            success += 1
        else:
            failed_scripts.append(script_id)
        if progress_callback:
            progress_callback(
                f"{'合成完成' if result else '合成失败'} [{script_index}/{len(script_files)}]: {script_id}",
                0.05 + 0.85 * script_index / max(len(script_files), 1),
            )

        # 清理临时合并音频
        if merged_audio and merged_audio.exists() and "final" in str(merged_audio.parent):
            try:
                merged_audio.unlink()
            except:
                pass

    logger.info(f"[compose] 合成完成: {success}/{len(script_files)}")
    if failed_scripts:
        raise RuntimeError(
            f"最终合成失败 {len(failed_scripts)}/{len(script_files)}: "
            + ", ".join(failed_scripts)
        )
    if progress_callback:
        progress_callback(f"合成完成: {success}/{len(script_files)}", 1.0)
    return {"success": success, "total": len(script_files)}


def _probe_video_duration(video_path: Path) -> float | None:
    """Return a positive duration only when ffprobe can read the video."""
    import subprocess

    if not video_path.exists() or video_path.stat().st_size <= 0:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _format_ffmpeg_exit_code(returncode: int) -> str:
    unsigned_code = returncode & 0xFFFFFFFF
    label = f"{returncode} (0x{unsigned_code:08X})"
    if unsigned_code == 0xC0000005:
        return label + "，Windows 内存访问冲突（APPCRASH）"
    return label


def _read_ffmpeg_error_summary(error_log: Path, limit: int = 12) -> str:
    if not error_log.exists():
        return "FFmpeg 未输出错误详情"
    try:
        raw = error_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "无法读取 FFmpeg 错误日志"
    lines = []
    for line in raw.replace("\r", "\n").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("frame="):
            continue
        if stripped.startswith("Fontconfig error:"):
            continue
        lines.append(stripped)
    return "\n".join(lines[-limit:]) if lines else "FFmpeg 进程无错误文本，可能发生外部终止或原生崩溃"


def _run_ffmpeg_with_progress(
    cmd: list[str],
    duration_s: float,
    error_log: Path,
    progress_callback=None,
    timeout: int = 18000,
) -> tuple[int, bool, dict]:
    """Run FFmpeg while streaming machine-readable progress updates."""
    import queue
    import subprocess
    import threading
    import time

    progress_queue: queue.Queue = queue.Queue()
    last_progress = {"frame": "0", "fps": "0", "out_time_s": 0.0, "speed": "0x"}

    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("w", encoding="utf-8", errors="replace") as error_file:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=error_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def _read_progress():
            try:
                for line in process.stdout or []:
                    progress_queue.put(line.rstrip())
            finally:
                progress_queue.put(None)

        reader = threading.Thread(target=_read_progress, name="ffmpeg-progress", daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        stream_finished = False
        timed_out = False
        progress_data = {}

        while True:
            if time.monotonic() >= deadline and process.poll() is None:
                timed_out = True
                process.kill()

            try:
                line = progress_queue.get(timeout=0.5)
            except queue.Empty:
                line = ""

            if line is None:
                stream_finished = True
            elif "=" in line:
                key, value = line.split("=", 1)
                progress_data[key] = value
                if key == "progress":
                    try:
                        out_time_s = int(progress_data.get("out_time_ms", "0")) / 1_000_000
                    except ValueError:
                        out_time_s = 0.0
                    last_progress = {
                        "frame": progress_data.get("frame", "0"),
                        "fps": progress_data.get("fps", "0"),
                        "out_time_s": out_time_s,
                        "speed": progress_data.get("speed", "0x"),
                    }
                    if progress_callback and duration_s > 0:
                        ratio = min(1.0, max(0.0, out_time_s / duration_s))
                        try:
                            progress_callback(
                                f"最终合成 {ratio * 100:.1f}% · {last_progress['frame']} 帧 · "
                                f"{last_progress['fps']} fps · {last_progress['speed']}",
                                0.08 + 0.87 * ratio,
                            )
                        except Exception as exc:
                            logger.debug("FFmpeg 进度回调失败: %s", exc)

            if process.poll() is not None and stream_finished:
                break

        reader.join(timeout=2)
        return process.wait(), timed_out, last_progress


def _compose_studio(
    studio_bg: Path,
    studio_desk: Path,
    live2d_webm: Path,
    overlay_webm: Path,
    merged_audio,
    media_segments: list,
    duration_s: float,
    output_mp4: Path,
    script_id: str,
    today: str = "",
    visual_mp4: Path = None,
    subtitle_ass: Path = None,
    visual_intervals: list = None,
    progress_callback=None,
) -> bool:
    """演播室合成核心逻辑

    演播室底层全程存在, 素材段通过 overlay + fade alpha 覆盖全屏,
    Live2D 用 split 分两路: 演播室模式居中大版, 素材段缩小到右下角.

    当 visual_mp4 存在时，使用预合成视频替代逐段叠加（解决 filter chain 过长卡死）。
    """
    FADE_DURATION = 0.5

    partial_output = output_mp4.with_name(f"{output_mp4.stem}.part{output_mp4.suffix}")
    error_log = output_mp4.parent / f"{script_id}_ffmpeg_err.log"
    partial_output.unlink(missing_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-stats_period", "1", "-progress", "pipe:1",
        "-filter_complex_threads", "8",
    ]
    input_idx = 0

    # Input 0: 演播室背景 (loop)
    cmd.extend(["-loop", "1", "-i", str(studio_bg)])
    bg_idx = input_idx
    input_idx += 1

    # Input: 流星特效 (VP9 alpha, loop)
    meteor_fx_path = Path(__file__).resolve().parent.parent.parent / "assets" / "studio" / "meteor_fx.webm"
    has_meteor = meteor_fx_path.exists()
    if has_meteor:
        cmd.extend(["-stream_loop", "-1", "-threads", "4", "-vcodec", "libvpx-vp9", "-i", str(meteor_fx_path)])
        meteor_idx = input_idx
        input_idx += 1

    # Input 1: Live2D (VP9 alpha)
    has_live2d = live2d_webm.exists()
    if has_live2d:
        cmd.extend(["-threads", "8", "-vcodec", "libvpx-vp9", "-i", str(live2d_webm)])
        l2d_idx = input_idx
        input_idx += 1

    # Input 2: 演播台前景 (loop)
    cmd.extend(["-loop", "1", "-i", str(studio_desk)])
    desk_idx = input_idx
    input_idx += 1

    # Input 3: Overlay WebM (VP9 alpha)
    has_overlay = overlay_webm.exists()
    if has_overlay:
        cmd.extend(["-threads", "4", "-vcodec", "libvpx-vp9", "-i", str(overlay_webm)])
        ov_idx = input_idx
        input_idx += 1

    # Input 4+: 素材文件 或 预合成 visual 视频
    use_precomposed = visual_mp4 is not None and visual_mp4.exists()
    media_input_map = []
    precomposed_visual_inputs = []

    if use_precomposed and visual_intervals:
        # Only decode the short material windows. Blending one full-duration
        # visual stream with a per-pixel expression is several times slower and
        # triggered excessive FFmpeg filter threads on long videos.
        for interval in visual_intervals:
            start = max(0.0, float(interval.get("start_s", 0) or 0))
            end = max(start, float(interval.get("end_s", 0) or 0))
            duration = end - start
            if duration <= 0:
                continue
            cmd.extend([
                "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                "-threads", "2", "-i", str(visual_mp4),
            ])
            precomposed_visual_inputs.append({
                "input_idx": input_idx,
                "start_s": start,
                "end_s": end,
                "duration_s": duration,
            })
            input_idx += 1
        use_precomposed = bool(precomposed_visual_inputs)
        logger.info(
            f"[compose] 使用预合成 visual 的 {len(precomposed_visual_inputs)} 个素材片段: "
            f"{visual_mp4.name}"
        )
    if use_precomposed and not precomposed_visual_inputs:
        use_precomposed = False
    if not use_precomposed:
        # 逐个素材输入（兼容无预合成的情况）
        for seg in media_segments:
            if seg["type"] == "video_clip":
                time_range = seg.get("time_range", [])
                if time_range and len(time_range) >= 1:
                    cmd.extend(["-ss", str(time_range[0])])
                cmd.extend(["-i", str(seg["source"])])
            else:
                cmd.extend(["-noautorotate", "-loop", "1", "-i", str(seg["source"])])
            media_input_map.append({
                "input_idx": input_idx,
                "start_s": seg["start_s"],
                "end_s": seg["end_s"],
                "type": seg["type"],
                "play_audio": seg.get("play_audio", False),
                "author": seg.get("author", ""),
            })
            input_idx += 1

    # Input N: TTS 音频
    has_audio = merged_audio is not None and Path(str(merged_audio)).exists()
    if has_audio:
        cmd.extend(["-i", str(merged_audio)])
        audio_idx = input_idx
        input_idx += 1

    # --- filter_complex ---
    fp = []

    # 1. 背景
    fp.append(
        f"[{bg_idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,setsar=1[studio_bg]"
    )

    # 1.5 流星特效叠加到背景上
    if has_meteor:
        fp.append(f"[{meteor_idx}:v]scale=1080:1920,format=yuva420p[meteor]")
        fp.append("[studio_bg][meteor]overlay=0:0:shortest=1[studio_bg_fx]")
        bg_label = "studio_bg_fx"
    else:
        bg_label = "studio_bg"

    # 2. Live2D
    if has_live2d:
        if media_segments or use_precomposed:
            fp.append(f"[{l2d_idx}:v]split=2[l2d_raw_big][l2d_raw_small]")
            fp.append("[l2d_raw_big]scale=864:1536[l2d_big]")
            fp.append("[l2d_raw_small]scale=540:960[l2d_small]")
        else:
            fp.append(f"[{l2d_idx}:v]scale=864:1536[l2d_big]")
        fp.append(f"[{bg_label}][l2d_big]overlay=108:100:shortest=1[with_char]")
    else:
        fp.append(f"[{bg_label}]copy[with_char]")

    # 3. 演播台前景
    fp.append(f"[{desk_idx}:v]scale=1080:580[desk]")
    fp.append("[with_char][desk]overlay=0:1340:shortest=1[studio_full]")

    # 4. 顶部 bar + 底部 ticker
    ticker_text = "AI Daily | Hot News | Tech Updates"
    fp.append(
        "[studio_full]"
        "drawbox=x=0:y=0:w=1080:h=80:color=black@0.6:t=fill,"
        "drawtext=text='Mili Channel':fontsize=32:fontcolor=white:x=20:y=25,"
        f"drawtext=text='{today}':fontsize=28:fontcolor=white@0.8:x=900:y=28,"
        "drawbox=x=0:y=1840:w=1080:h=80:color=black@0.75:t=fill,"
        "drawtext=text='LIVE':fontsize=36:fontcolor=white:x=15:y=1860:"
        "box=1:boxcolor=red:boxborderw=6,"
        f"drawtext=text='{ticker_text}':"
        "fontsize=28:fontcolor=white:x='1080-mod(t*200\\,2400)':y=1862[studio_ui]"
    )

    # 5. Visual 轨
    cur = "studio_ui"

    if precomposed_visual_inputs:
        # Each material window is trimmed and faded independently. This avoids a
        # full-frame blend expression being evaluated for every pixel of the video.
        for i, segment in enumerate(precomposed_visual_inputs):
            mi = segment["input_idx"]
            start = segment["start_s"]
            duration = segment["duration_s"]
            fade = min(FADE_DURATION, duration / 2)
            fade_out_start = max(0.0, duration - fade)
            fp.append(
                f"[{mi}:v]scale=1080:1760:force_original_aspect_ratio=decrease,"
                "setsar=1,pad=1080:1760:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=yuva420p,"
                f"fade=t=in:st=0:d={fade:.3f}:alpha=1,"
                f"fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}:alpha=1,"
                f"setpts=PTS+{start:.3f}/TB[previs_{i}]"
            )
            nxt = f"v_pre{i}"
            fp.append(f"[{cur}][previs_{i}]overlay=0:80:eof_action=pass:shortest=0[{nxt}]")
            cur = nxt
    else:
        # 逐段叠加模式（原始逻辑，用于素材少或无预合成的情况）
        for i, mseg in enumerate(media_input_map):
            mi = mseg["input_idx"]
            start = mseg["start_s"]
            end = mseg["end_s"]
            dur = end - start
            author = mseg.get("author", "")

            fade_in_d = min(FADE_DURATION, dur / 2)
            fade_out_st = max(0, dur - FADE_DURATION)

            media_filter = (
                f"[{mi}:v]scale=1080:1760:force_original_aspect_ratio=decrease,setsar=1,"
                f"pad=1080:1760:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"setpts=PTS-STARTPTS,trim=duration={dur},setpts=PTS-STARTPTS,"
                f"format=yuva420p,fade=t=in:st=0:d={fade_in_d}:alpha=1,"
                f"fade=t=out:st={fade_out_st}:d={FADE_DURATION}:alpha=1"
            )

            media_filter += f",setpts=PTS+{start}/TB[media_{i}]"
            fp.append(media_filter)

            nxt = f"v_m{i}"
            fp.append(
                f"[{cur}][media_{i}]overlay=0:80:eof_action=pass:shortest=0[{nxt}]"
            )
            cur = nxt

    # 6. Live2D 小版本 (素材段右下角, 延迟0.5s出现/提前0.5s消失)
    if has_live2d and (visual_intervals or media_segments or use_precomposed):
        delay = FADE_DURATION  # 和素材 fade 时长一致
        visibility_intervals = visual_intervals or media_segments
        parts = [
            f"between(t,{seg['start_s']+delay},{seg['end_s']-delay})"
            for seg in visibility_intervals
            if seg['end_s'] - seg['start_s'] > delay * 3
        ]
        if parts:
            enable_expr = "+".join(parts)
            nxt = "v_small"
            fp.append(
                f"[{cur}][l2d_small]overlay=510:880:"
                f"enable='gte({enable_expr},1)':eof_action=pass[{nxt}]"
            )
            cur = nxt


    # 7. Overlay (remotion 全程)
    if has_overlay:
        fp.append(f"[{ov_idx}:v]scale=1080:1920,format=yuva420p[ov]")
        nxt = "v_final"
        fp.append(f"[{cur}][ov]overlay=0:0:shortest=0:eof_action=pass[{nxt}]")
        cur = nxt

    # 8. 独立字幕轨（最后叠加，保证不会被其他图层遮挡）
    if subtitle_ass is not None and subtitle_ass.exists():
        subtitle_path = str(subtitle_ass.resolve()).replace("\\", "/")
        subtitle_path = subtitle_path.replace(":", r"\:").replace("'", r"\'")
        nxt = "v_subtitle"
        fp.append(f"[{cur}]ass=filename='{subtitle_path}'[{nxt}]")
        cur = nxt

    # 9. 输出格式
    fp.append(f"[{cur}]format=yuv420p[vout]")

    # 音频处理
    # merged_audio 已经包含了 TTS + video_clip 原声（按正确时间位置混合好的）
    # 不需要再单独处理 video_clip 音频
    audio_output = None
    if has_audio:
        afp = [f"[{audio_idx}:a]volume=1.0[aout]"]
        audio_output = "[aout]"
    else:
        afp = []

    # 合并 filter_complex — 写入临时文件以避免 Windows 命令行长度/编码问题
    filter_complex = ";".join(fp + afp)
    filter_script = output_mp4.parent / f"{script_id}_filter.txt"
    with open(filter_script, "w", encoding="utf-8") as f:
        f.write(filter_complex)
    cmd.extend(["-filter_complex_script", str(filter_script)])

    # Output mapping
    cmd.extend(["-map", "[vout]"])
    if audio_output:
        cmd.extend(["-map", audio_output, "-c:a", "aac", "-b:a", "128k"])
    elif has_audio:
        cmd.extend(["-map", f"{audio_idx}:a", "-c:a", "aac", "-b:a", "128k"])

    # Video encoding
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-threads", "16", "-t", str(duration_s),
        "-movflags", "+faststart", str(partial_output),
    ])

    completed = False
    try:
        returncode, timed_out, last_progress = _run_ffmpeg_with_progress(
            cmd,
            duration_s=duration_s,
            error_log=error_log,
            progress_callback=progress_callback,
            timeout=18000,
        )
        if timed_out:
            logger.error(
                f"[compose] ⏰ 超时: {script_id}; 最后进度 "
                f"{last_progress['out_time_s']:.1f}/{duration_s:.1f}s"
            )
            return False

        if returncode == 0:
            actual_duration = _probe_video_duration(partial_output)
            minimum_duration = max(0.1, duration_s - max(1.0, duration_s * 0.01))
            if actual_duration is None or actual_duration < minimum_duration:
                logger.error(
                    f"[compose] ❌ {script_id}: 输出校验失败，"
                    f"duration={actual_duration}, expected={duration_s:.1f}s"
                )
                return False
            output_mp4.unlink(missing_ok=True)
            partial_output.replace(output_mp4)
            size_mb = output_mp4.stat().st_size / (1024 * 1024)
            logger.info(
                f"[compose] ✅ {script_id} -> {size_mb:.1f}MB, "
                f"{actual_duration:.1f}s"
            )
            completed = True
            error_log.unlink(missing_ok=True)
            return True
        exit_code = _format_ffmpeg_exit_code(returncode)
        summary = _read_ffmpeg_error_summary(error_log)
        logger.error(
            f"[compose] ❌ {script_id}: FFmpeg 退出码 {exit_code}; "
            f"最后进度 {last_progress['out_time_s']:.1f}/{duration_s:.1f}s, "
            f"frame={last_progress['frame']}, fps={last_progress['fps']}, "
            f"speed={last_progress['speed']}\n{summary}\n错误日志: {error_log}"
        )
        return False
    except Exception as e:
        logger.error(f"[compose] 💥 {script_id}: {e}")
        return False
    finally:
        if not completed:
            partial_output.unlink(missing_ok=True)
            output_mp4.unlink(missing_ok=True)
            logger.info(f"[compose] 已保留失败滤镜脚本: {filter_script}")
        else:
            filter_script.unlink(missing_ok=True)


def _merge_audio_segments(audio_seg_dir: Path, script: dict, output_path: Path):
    """将多段 TTS WAV + 视频原声按时间轴合并为一个完整音频文件
    
    支持:
    - voice 轨的 TTS wav 文件（voice_00.wav, voice_01.wav, ...）
    - visual 轨中 video_clip 的 play_audio: true（从源视频提取原声）
    """
    import subprocess
    import math

    if not audio_seg_dir.exists():
        audio_seg_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧的视频音频缓存（防止脚本变更后 vi_idx 映射错位）
    for old_audio in audio_seg_dir.glob("video_audio_*.wav"):
        old_audio.unlink()

    total_ms = script.get("total_duration_ms", 30000)
    voice_items = script.get("tracks", {}).get("voice", [])
    visual_items = script.get("tracks", {}).get("visual", [])

    # 收集所有音频片段: (文件路径, 开始毫秒)
    audio_segments = []

    # 1. TTS 语音片段 - 使用 audio_file 字段定位文件
    for item in voice_items:
        audio_file = item.get("audio_file", "")
        if not audio_file:
            continue  # 跳过空段（play_audio 留空段没有 audio_file）
        wav_path = audio_seg_dir.parent.parent / audio_file
        if not wav_path.exists():
            # 兼容旧格式: 尝试从 audio_seg_dir 直接找
            wav_path = audio_seg_dir / Path(audio_file).name
        if wav_path.exists():
            start_ms = item.get("start_ms", 0)
            audio_segments.append((wav_path, start_ms))

    # 2. 视频原声片段 (play_audio: true)
    for vi_idx, vis_item in enumerate(visual_items):
        if vis_item.get("type") != "video_clip":
            continue
        if not vis_item.get("play_audio", False):
            continue
        
        source = vis_item.get("source", "")
        time_range = vis_item.get("time_range", [])
        start_ms = vis_item.get("start_ms", 0)
        
        if not source or not time_range or len(time_range) < 2:
            continue
        
        source_path = Path(source)
        if not source_path.exists():
            # 尝试相对于 data_root 查找
            data_root_guess = audio_seg_dir.parent.parent
            source_path = data_root_guess / source
            if not source_path.exists():
                logger.warning(f"[compose] 视频原声源不存在: {source}")
                continue
        
        # 从源视频提取音频片段
        clip_start_s = time_range[0]
        clip_end_s = time_range[1]
        clip_duration_s = clip_end_s - clip_start_s
        
        extracted_audio = audio_seg_dir / f"video_audio_{vi_idx:02d}.wav"
        if not extracted_audio.exists():
            extract_cmd = [
                "ffmpeg", "-y",
                "-i", str(source_path),
                "-ss", str(clip_start_s),
                "-t", str(clip_duration_s),
                "-vn",
                "-ac", "1",
                "-ar", "24000",
                str(extracted_audio),
            ]
            try:
                result = subprocess.run(
                    extract_cmd, capture_output=True, text=True,
                    timeout=30, encoding="utf-8", errors="replace",
                )
                if result.returncode != 0:
                    logger.warning(f"[compose] 视频音频提取失败: {result.stderr[:200]}")
                    continue
            except Exception as e:
                logger.warning(f"[compose] 视频音频提取异常: {e}")
                continue
        
        if extracted_audio.exists():
            audio_segments.append((extracted_audio, start_ms))

    if not audio_segments:
        return None

    # 构建 play_audio 时间段列表（用于 TTS 静音）
    play_audio_ranges = []
    for vis_item in visual_items:
        if vis_item.get("type") == "video_clip" and vis_item.get("play_audio"):
            pa_start = vis_item.get("start_ms", 0)
            pa_end = pa_start + vis_item.get("duration_ms", 0)
            play_audio_ranges.append((pa_start, pa_end))

    # 如果只有一段且起始为0，且无 play_audio 冲突，直接返回
    if len(audio_segments) == 1 and audio_segments[0][1] == 0 and not play_audio_ranges:
        return audio_segments[0][0]

    # 用 FFmpeg 的 adelay + volume ducking + amix 合并到正确时间位置
    cmd = ["ffmpeg", "-y"]
    filter_parts = []

    # 构建 voice 文件名 -> 允许最大时长(秒) 的映射
    # 用于 atrim 防止 TTS 实际音频超出脚本分配时长导致重叠
    voice_max_dur = {}
    for vi, vitem in enumerate(voice_items):
        audio_file = vitem.get("audio_file", "")
        if audio_file:
            fname = Path(audio_file).name
            # 允许时长 = 脚本分配的 duration_ms（已是 TTS 实际 + 200ms padding）
            voice_max_dur[fname] = vitem.get("duration_ms", 99999) / 1000.0

    for idx, (wav_path, start_ms) in enumerate(audio_segments):
        cmd.extend(["-i", str(wav_path)])
        
        # 检查这个音频片段是否是 TTS（voice_*.wav）还是 video_audio
        is_tts = "voice_" in wav_path.name
        
        # TTS 片段加 atrim 限制时长，防止超出分配时段
        trim_filter = ""
        if is_tts:
            max_dur_s = voice_max_dur.get(wav_path.name, None)
            if max_dur_s:
                trim_filter = f"atrim=0:{max_dur_s:.3f},asetpts=PTS-STARTPTS,"
        
        if is_tts and play_audio_ranges:
            # 对 TTS 应用 volume ducking：在 play_audio 时段静音
            # 注意：volume 表达式里的时间是相对于该片段的全局时间（adelay 后）
            # adelay 后该片段从 start_ms 开始，所以用绝对时间 between(t, pa_start/1000, pa_end/1000)
            # 但 adelay 是放在 volume 之后的，所以 volume 里的 t 是片段本地时间
            # 需要换算：全局时间 = 本地时间 + start_ms/1000
            # between(本地t + offset, pa_start_s, pa_end_s) 
            # => between(t, pa_start_s - offset, pa_end_s - offset)
            offset_s = start_ms / 1000.0
            duck_parts = []
            for pa_start, pa_end in play_audio_ranges:
                local_start = pa_start / 1000.0 - offset_s
                local_end = pa_end / 1000.0 - offset_s
                if local_end > 0:  # 只有和本片段有时间重叠才需要
                    local_start = max(0, local_start)
                    duck_parts.append(f"between(t,{local_start:.3f},{local_end:.3f})")
            
            if duck_parts:
                duck_expr = "+".join(duck_parts)
                filter_parts.append(
                    f"[{idx}:a]{trim_filter}volume='1-min(1,{duck_expr})':eval=frame,adelay={start_ms}|{start_ms}[a{idx}]"
                )
            else:
                filter_parts.append(f"[{idx}:a]{trim_filter}adelay={start_ms}|{start_ms}[a{idx}]")
        else:
            filter_parts.append(f"[{idx}:a]{trim_filter}adelay={start_ms}|{start_ms}[a{idx}]")

    n = len(filter_parts)
    mix_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_parts.append(f"{mix_inputs}amix=inputs={n}:duration=longest:normalize=0[aout]")

    filter_complex = ";".join(filter_parts)
    duration_s = total_ms / 1000.0

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-t", str(duration_s),
        "-ac", "1",
        "-ar", "24000",
        str(output_path),
    ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return output_path
        else:
            logger.warning(f"[compose] 音频合并失败: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.warning(f"[compose] 音频合并异常: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Renderer - 视频渲染管线")
    parser.add_argument("--date", type=str, default=None, help="日期 (YYYY-MM-DD)")
    parser.add_argument("--step", type=str, choices=["download", "recognize", "transcribe", "tts", "align", "render", "visual", "live2d", "compose"])
    parser.add_argument("--all", action="store_true", help="执行全部步骤")
    args = parser.parse_args()
    
    today = args.date or datetime.now().strftime("%Y-%m-%d")
    config = load_config()
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    
    steps = []
    if args.all:
        steps = ["download", "recognize", "transcribe", "tts", "align", "render", "visual", "live2d", "compose"]
    elif args.step:
        steps = [args.step]
    else:
        parser.print_help()
        return
    
    logger.info("=" * 60)
    logger.info(f"[render] Date: {today}, Steps: {steps}")
    logger.info("=" * 60)
    
    step_map = {
        "download": step_download,
        "recognize": step_recognize,
        "transcribe": step_transcribe,
        "tts": step_tts,
        "align": step_align,
        "render": step_render,
        "visual": step_visual,
        "live2d": step_live2d,
        "compose": step_compose,
    }
    
    for step_name in steps:
        logger.info(f"\n{'─' * 40}")
        logger.info(f"[render] >>> Step: {step_name}")
        logger.info(f"{'─' * 40}")
        step_map[step_name](config, today, data_root)
    
    logger.info("\n" + "=" * 60)
    logger.info("[render] DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
