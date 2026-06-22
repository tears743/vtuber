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


def step_compose(config: dict, today: str, data_root: Path):
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
    for script_path in script_files:
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        script_id = script.get("id", script_path.stem)
        output_mp4 = output_dir / f"{script_id}.mp4"

        # 跳过已存在的
        if output_mp4.exists():
            logger.info(f"[compose] ⏭️ 已存在: {script_id}")
            success += 1
            continue

        logger.info(f"[compose] 合成: {script_id}")

        live2d_webm = live2d_dir / f"{script_id}_live2d.webm"
        overlay_webm = overlay_dir / f"{script_id}_overlay.webm"

        # 合并 TTS 音频
        audio_seg_dir = audio_dir / script_id
        merged_audio = _merge_audio_segments(audio_seg_dir, script, output_dir / f"{script_id}_audio.wav")

        total_ms = script.get("total_duration_ms", 30000)
        duration_s = total_ms / 1000.0

        # 分析 visual 轨，找出素材段 (image/video_clip)
        tracks = script.get("tracks", {})
        visual_items = tracks.get("visual", [])
        media_segments = []


        for vis in visual_items:
            vtype = vis.get("type", "")
            if vtype in ("image", "video_clip"):
                start_ms = vis.get("start_ms", 0)
                dur_ms = vis.get("duration_ms", 5000)
                source = vis.get("source", "")
                if source and Path(source).exists():
                    media_segments.append({
                        "start_s": start_ms / 1000.0,
                        "end_s": (start_ms + dur_ms) / 1000.0,
                        "type": vtype,
                        "source": source,
                        "play_audio": vis.get("play_audio", False),
                        "time_range": vis.get("time_range", []),
                    })

        # 构建 FFmpeg 命令
        result = _compose_studio(
            studio_bg=studio_bg,
            studio_desk=studio_desk,
            live2d_webm=live2d_webm,
            overlay_webm=overlay_webm,

            merged_audio=merged_audio,
            media_segments=media_segments,
            duration_s=duration_s,
            output_mp4=output_mp4,
            script_id=script_id,
            today=today,
        )

        if result:
            success += 1

        # 清理临时合并音频
        if merged_audio and merged_audio.exists() and "final" in str(merged_audio.parent):
            try:
                merged_audio.unlink()
            except:
                pass

    logger.info(f"[compose] 合成完成: {success}/{len(script_files)}")


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
) -> bool:
    """演播室合成核心逻辑

    演播室底层全程存在, 素材段通过 overlay + fade alpha 覆盖全屏,
    Live2D 用 split 分两路: 演播室模式居中大版, 素材段缩小到右下角.
    """
    import subprocess

    FADE_DURATION = 0.5

    cmd = ["ffmpeg", "-y"]
    input_idx = 0

    # Input 0: 演播室背景 (loop)
    cmd.extend(["-loop", "1", "-i", str(studio_bg)])
    bg_idx = input_idx
    input_idx += 1

    # Input: 流星特效 (VP9 alpha, loop)
    meteor_fx_path = Path(__file__).resolve().parent.parent.parent / "assets" / "studio" / "meteor_fx.webm"
    has_meteor = meteor_fx_path.exists()
    if has_meteor:
        cmd.extend(["-stream_loop", "-1", "-vcodec", "libvpx-vp9", "-i", str(meteor_fx_path)])
        meteor_idx = input_idx
        input_idx += 1

    # Input 1: Live2D (VP9 alpha)
    has_live2d = live2d_webm.exists()
    if has_live2d:
        cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(live2d_webm)])
        l2d_idx = input_idx
        input_idx += 1

    # Input 2: 演播台前景 (loop)
    cmd.extend(["-loop", "1", "-i", str(studio_desk)])
    desk_idx = input_idx
    input_idx += 1

    # Input 3: Overlay WebM (VP9 alpha)
    has_overlay = overlay_webm.exists()
    if has_overlay:
        cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(overlay_webm)])
        ov_idx = input_idx
        input_idx += 1

    # Input 4+: 素材文件 (image/video_clip)
    media_input_map = []
    for seg in media_segments:
        if seg["type"] == "video_clip":
            time_range = seg.get("time_range", [])
            if time_range and len(time_range) >= 1:
                cmd.extend(["-ss", str(time_range[0])])
            cmd.extend(["-i", str(seg["source"])])
        else:
            cmd.extend(["-loop", "1", "-i", str(seg["source"])])
        media_input_map.append({
            "input_idx": input_idx,
            "start_s": seg["start_s"],
            "end_s": seg["end_s"],
            "type": seg["type"],
            "play_audio": seg.get("play_audio", False),
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
        if media_segments:
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

    # 5. Visual 轨内容已合并到 overlay webm（透明），不再需要单独层
    cur = "studio_ui"

    # 6. 素材段叠加 (等比居中 + 黑色填充 + fade)
    for i, mseg in enumerate(media_input_map):
        mi = mseg["input_idx"]
        start = mseg["start_s"]
        end = mseg["end_s"]
        dur = end - start

        fade_in_d = min(FADE_DURATION, dur / 2)
        fade_out_st = max(0, dur - FADE_DURATION)

        # 素材链: 等比缩放 → 黑色不透明pad到1760(留顶底bar) → trim → fade → 时间偏移
        fp.append(
            f"[{mi}:v]scale=1080:1760:force_original_aspect_ratio=decrease,setsar=1,"
            f"pad=1080:1760:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setpts=PTS-STARTPTS,trim=duration={dur},setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d={fade_in_d},"
            f"fade=t=out:st={fade_out_st}:d={FADE_DURATION},"
            f"setpts=PTS+{start}/TB[media_{i}]"
        )

        nxt = f"v_m{i}"
        fp.append(
            f"[{cur}][media_{i}]overlay=0:80:eof_action=pass:shortest=0[{nxt}]"
        )
        cur = nxt

    # 6. Live2D 小版本 (素材段右下角, 延迟0.5s出现/提前0.5s消失)
    if has_live2d and media_segments:
        delay = FADE_DURATION  # 和素材 fade 时长一致
        parts = [
            f"between(t,{m['start_s']+delay},{m['end_s']-delay})"
            for m in media_input_map
            if m['end_s'] - m['start_s'] > delay * 3  # 太短的段不显示小角色
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
        fp.append(f"[{ov_idx}:v]scale=1080:1920[ov]")
        nxt = "v_final"
        fp.append(f"[{cur}][ov]overlay=0:0:shortest=1[{nxt}]")
        cur = nxt

    # 8. 输出格式
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

    # 合并 filter_complex
    filter_complex = ";".join(fp + afp)
    cmd.extend(["-filter_complex", filter_complex])

    # Output mapping
    cmd.extend(["-map", "[vout]"])
    if audio_output:
        cmd.extend(["-map", audio_output, "-c:a", "aac", "-b:a", "128k"])
    elif has_audio:
        cmd.extend(["-map", f"{audio_idx}:a", "-c:a", "aac", "-b:a", "128k"])

    # Video encoding
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-t", str(duration_s), str(output_mp4),
    ])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=1800, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            size_mb = output_mp4.stat().st_size / (1024 * 1024)
            logger.info(f"[compose] ✅ {script_id} -> {size_mb:.1f}MB")
            return True
        else:
            logger.error(f"[compose] ❌ {script_id}:\n{result.stderr[-800:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"[compose] ⏰ 超时: {script_id}")
        return False
    except Exception as e:
        logger.error(f"[compose] 💥 {script_id}: {e}")
        return False


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

    # 1. TTS 语音片段
    wav_files = sorted(audio_seg_dir.glob("voice_*.wav"))
    for idx, item in enumerate(voice_items):
        wav_path = audio_seg_dir / f"voice_{idx:02d}.wav"
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

    for idx, (wav_path, start_ms) in enumerate(audio_segments):
        cmd.extend(["-i", str(wav_path)])
        
        # 检查这个音频片段是否是 TTS（voice_*.wav）还是 video_audio
        is_tts = "voice_" in wav_path.name
        
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
                    f"[{idx}:a]volume='1-min(1,{duck_expr})':eval=frame,adelay={start_ms}|{start_ms}[a{idx}]"
                )
            else:
                filter_parts.append(f"[{idx}:a]adelay={start_ms}|{start_ms}[a{idx}]")
        else:
            filter_parts.append(f"[{idx}:a]adelay={start_ms}|{start_ms}[a{idx}]")

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
