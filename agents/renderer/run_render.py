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
    """Step 4: 最终合成 (FFmpeg)

    合成层级 (从底到顶):
        1. visual（图片/视频素材渲染 — 底层）或纯色背景
        2. live2d（Live2D 透明 WebM — 右下角角色）
        3. overlay（Remotion WebM — 弹幕/数据卡片等）
        4. audio（TTS 语音，多段 WAV 合并）

    关键: VP9 alpha WebM 必须用 -vcodec libvpx-vp9 解码才能获取 alpha 通道
    """
    import subprocess

    logger.info("[render] Step 4: 最终合成")

    scripts_dir = data_root / today / "scripts_aligned"
    overlay_dir = data_root / today / "overlay"
    live2d_dir = data_root / today / "live2d"
    audio_dir = data_root / today / "audio"
    visual_dir = data_root / today / "visual"
    output_dir = data_root / today / "final"
    output_dir.mkdir(parents=True, exist_ok=True)

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

        # 查找各轨文件
        visual_mp4 = visual_dir / f"{script_id}_visual.mp4"
        live2d_webm = live2d_dir / f"{script_id}_live2d.webm"
        overlay_webm = overlay_dir / f"{script_id}_overlay.webm"

        # 合并多段 TTS 音频
        audio_seg_dir = audio_dir / script_id
        merged_audio = _merge_audio_segments(audio_seg_dir, script, output_dir / f"{script_id}_audio.wav")

        total_ms = script.get("total_duration_ms", 30000)
        duration_s = total_ms / 1000.0

        # 从脚本中提取 video_clip 的原声信息（play_audio: true）
        tracks = script.get("tracks", {})
        visual_items = tracks.get("visual", [])
        video_clips_with_audio = [
            v for v in visual_items
            if v.get("type") == "video_clip" and v.get("play_audio") and v.get("source")
            and Path(v["source"]).exists()
        ]

        # 构建 FFmpeg 命令
        cmd = ["ffmpeg", "-y"]
        input_idx = 0

        # Input 0: 视频底层 (visual 或纯色背景)
        if visual_mp4.exists():
            cmd.extend(["-i", str(visual_mp4)])
        else:
            # 深色纯色背景
            cmd.extend(["-f", "lavfi", "-i",
                        f"color=c=0x0f0f23:s=1080x1920:d={duration_s}:r=30"])
        input_idx += 1

        # Input 1: Live2D WebM (VP9 alpha)
        has_live2d = live2d_webm.exists()
        if has_live2d:
            cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(live2d_webm)])
            input_idx += 1

        # Input 2: Overlay WebM (VP9 alpha)
        has_overlay = overlay_webm.exists()
        if has_overlay:
            cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(overlay_webm)])
            input_idx += 1

        # Input 3: TTS Audio
        has_audio = merged_audio is not None and merged_audio.exists()
        if has_audio:
            cmd.extend(["-i", str(merged_audio)])
            audio_idx = input_idx
            input_idx += 1

        # Input 4+: video_clip 原声源文件
        clip_inputs = []
        for clip in video_clips_with_audio:
            source = clip["source"]
            time_range = clip.get("time_range", [0, clip.get("duration_ms", 5000) / 1000])
            start_s = time_range[0] if isinstance(time_range, list) and len(time_range) > 0 else 0
            dur_s = clip.get("duration_ms", 5000) / 1000.0

            cmd.extend(["-ss", str(start_s), "-t", str(dur_s), "-i", str(source)])
            clip_inputs.append({
                "input_idx": input_idx,
                "start_ms": clip["start_ms"],
                "duration_ms": clip["duration_ms"],
            })
            input_idx += 1

        # 构建 filter_complex
        filter_parts = []
        current_label = "bg"

        # 底层缩放
        filter_parts.append(f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[{current_label}]")

        # 叠加 Live2D (缩放到右下角 30% 区域)
        if has_live2d:
            live2d_input = 1
            # 缩放 Live2D 到 80% 宽度 (864px), 高度等比 1536px，定位右下角
            filter_parts.append(f"[{live2d_input}:v]scale=864:1536[l2d_scaled]")
            # x=1080-864=216, y=1920-1536=384
            filter_parts.append(f"[{current_label}][l2d_scaled]overlay=216:384:shortest=1[v1]")
            current_label = "v1"

        # 叠加 Overlay
        if has_overlay:
            ov_input = 2 if has_live2d else 1
            filter_parts.append(f"[{ov_input}:v]scale=1080:1920[ov]")
            next_label = "v2"
            filter_parts.append(f"[{current_label}][ov]overlay=0:0:shortest=1[{next_label}]")
            current_label = next_label

        # 最终视频输出
        filter_parts.append(f"[{current_label}]format=yuv420p[vout]")

        # 音频混合: TTS + video_clip 原声（按时间点 adelay）
        audio_streams = []
        if has_audio and clip_inputs:
            # 有 clip 需要混合时，给 TTS 加 volume filter
            filter_parts.append(f"[{audio_idx}:a]volume=1.0[tts]")
            audio_streams.append("[tts]")

        for i, clip_info in enumerate(clip_inputs):
            delay_ms = clip_info["start_ms"]
            clip_label = f"clip{i}"
            # adelay 将音频延迟到正确时间点，volume 降低防止盖过 TTS
            filter_parts.append(
                f"[{clip_info['input_idx']}:a]volume=0.7,adelay={delay_ms}|{delay_ms}[{clip_label}]"
            )
            audio_streams.append(f"[{clip_label}]")

        # 混合所有音频流
        if len(audio_streams) > 1:
            mix_inputs = "".join(audio_streams)
            filter_parts.append(
                f"{mix_inputs}amix=inputs={len(audio_streams)}:duration=longest:dropout_transition=2[aout]"
            )
            audio_output = "[aout]"
        elif len(audio_streams) == 1:
            # 只有 clip 没有 TTS（不太可能但防御性处理）
            audio_output = audio_streams[0]
        else:
            audio_output = None

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])

        # Output mapping
        cmd.extend(["-map", "[vout]"])
        if audio_output:
            cmd.extend(["-map", audio_output])
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        elif has_audio:
            cmd.extend(["-map", f"{audio_idx}:a"])
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        elif clip_inputs:
            # 只有 clip 原声没有 TTS
            cmd.extend(["-map", f"{clip_inputs[0]['input_idx']}:a"])
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])

        # Video encoding
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-t", str(duration_s),
            str(output_mp4),
        ])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                size_mb = output_mp4.stat().st_size / (1024 * 1024)
                logger.info(f"[compose] ✅ {script_id} -> {size_mb:.1f}MB")
                success += 1
            else:
                logger.error(f"[compose] ❌ {script_id}:\n{result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            logger.error(f"[compose] ⏰ 超时: {script_id}")
        except Exception as e:
            logger.error(f"[compose] 💥 {script_id}: {e}")

        # 清理临时合并音频
        if merged_audio and merged_audio.exists() and "final" in str(merged_audio.parent):
            try:
                merged_audio.unlink()
            except:
                pass

    logger.info(f"[compose] 合成完成: {success}/{len(script_files)}")


def _merge_audio_segments(audio_seg_dir: Path, script: dict, output_path: Path) -> Path | None:
    """将多段 TTS WAV + 视频原声按时间轴合并为一个完整音频文件
    
    支持:
    - voice 轨的 TTS wav 文件（voice_00.wav, voice_01.wav, ...）
    - visual 轨中 video_clip 的 play_audio: true（从源视频提取原声）
    """
    import subprocess
    import math

    if not audio_seg_dir.exists():
        audio_seg_dir.mkdir(parents=True, exist_ok=True)

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

    # 如果只有一段且起始为0，直接返回
    if len(audio_segments) == 1 and audio_segments[0][1] == 0:
        return audio_segments[0][0]

    # 用 FFmpeg 的 adelay + amix 合并到正确时间位置
    cmd = ["ffmpeg", "-y"]
    filter_parts = []

    for idx, (wav_path, start_ms) in enumerate(audio_segments):
        cmd.extend(["-i", str(wav_path)])
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
            timeout=120,  # 聚合视频更长，增加超时
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
