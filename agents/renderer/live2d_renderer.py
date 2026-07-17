"""
Live2D 轨渲染器

处理流程：
1. 读取 scripts_aligned/ 中每个脚本的口播段 (live2d_talk)
2. 从对应的 TTS wav 文件提取每帧音量数据
3. 调用 Remotion 渲染 Live2D 动画（透明背景 WebM）
4. 输出：每个脚本一个 live2d 透明 WebM

输入 props：
- modelUrl: 模型路径（public/下）
- volumes: number[] — 每帧嘴巴音量 (0~1)
- scale/offsetX/offsetY: 位置参数
"""
import json
import logging
import subprocess
import wave
import struct
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

REMOTION_DIR = Path(__file__).parent.parent.parent / "remotion"
FPS = 30
MODEL_URL = "live2d/mao_pro/mao_pro.model3.json"

# action → 模型文件映射
# expression: {name} → 对应 model3.json 中的 Expression name
# motion: {group, index} → 对应 model3.json 中的 Motion group/index
ACTION_MAP = {
    # 表情类（配合 idle 动作）
    "exp_pleasant":    {"expression": "exp_01", "motion": None},
    "exp_happy_squint":{"expression": "exp_02", "motion": None},
    "exp_thinking":    {"expression": "exp_03", "motion": None},
    "exp_curious":     {"expression": "exp_04", "motion": None},
    "exp_neutral":     {"expression": "exp_05", "motion": None},
    "exp_shy_smile":   {"expression": "exp_06", "motion": None},
    "exp_stunned":     {"expression": "exp_07", "motion": None},
    "exp_dejected":    {"expression": "exp_08", "motion": None},
    # 动作类
    "motion_idle":       {"expression": None, "motion": {"group": "Idle", "index": 0}},
    "motion_happy_wave":  {"expression": None, "motion": {"group": "Action", "index": 0}},  # mtn_02
    "motion_lecture":    {"expression": None, "motion": {"group": "Action", "index": 1}},  # mtn_03
    "motion_encourage":  {"expression": None, "motion": {"group": "Action", "index": 2}},  # mtn_04
    # 特殊动作（带特效）
    "sp_cast_success": {"expression": None, "motion": {"group": "Action", "index": 3}},  # special_01
    "sp_cast_fail":    {"expression": None, "motion": {"group": "Action", "index": 4}},  # special_02
    "sp_thumbs_up":    {"expression": None, "motion": {"group": "Action", "index": 5}},  # special_03
}


def extract_volumes_from_wav(wav_path: Path, fps: int = 30) -> list[float]:
    """
    从 WAV 文件提取每帧的 RMS 音量 (归一化到 0~1)
    """
    try:
        with wave.open(str(wav_path), 'rb') as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            # 每视频帧对应的音频采样数
            samples_per_frame = framerate // fps
            total_video_frames = math.ceil(n_frames / samples_per_frame)

            volumes = []
            for _ in range(total_video_frames):
                raw = wf.readframes(samples_per_frame)
                if not raw:
                    volumes.append(0.0)
                    continue

                # 解析采样
                if sample_width == 2:
                    fmt = f"<{len(raw) // 2}h"
                    samples = struct.unpack(fmt, raw)
                elif sample_width == 1:
                    samples = [s - 128 for s in raw]
                else:
                    volumes.append(0.0)
                    continue

                # 如果多声道，只取第一声道
                if n_channels > 1:
                    samples = samples[::n_channels]

                # 计算 RMS
                if not samples:
                    volumes.append(0.0)
                    continue
                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                # 归一化（16bit max = 32768）
                max_val = 32768 if sample_width == 2 else 128
                normalized = min(1.0, rms / (max_val * 0.3))  # 0.3 作为敏感度系数
                volumes.append(round(normalized, 3))

            return volumes
    except Exception as e:
        logger.warning(f"[live2d] 无法读取音频 {wav_path}: {e}")
        return []


def build_live2d_volumes(script: dict, audio_dir: Path, fps: int = 30) -> list[float]:
    """
    根据脚本的 voice track 构建完整视频的 volumes 数组。
    非口播段的 volumes 为 0（嘴巴闭合）。
    
    音频文件命名: audio/{script_id}/voice_00.wav, voice_01.wav, ...
    """
    total_ms = script.get("total_duration_ms", 30000)
    total_frames = math.ceil(total_ms / 1000 * fps)
    volumes = [0.0] * total_frames

    script_id = script.get("id", "unknown")
    tracks = script.get("tracks", {})
    voice_items = tracks.get("voice", [])

    for idx, item in enumerate(voice_items):
        start_ms = item.get("start_ms", 0)
        start_frame = round(start_ms / 1000 * fps)

        # 对应的音频文件
        wav_path = audio_dir / script_id / f"voice_{idx:02d}.wav"
        if wav_path.exists():
            seg_volumes = extract_volumes_from_wav(wav_path, fps)
            for i, v in enumerate(seg_volumes):
                target_frame = start_frame + i
                if target_frame < total_frames:
                    volumes[target_frame] = v
        else:
            logger.debug(f"[live2d] 音频不存在: {wav_path}")

    return volumes


def _build_action_timeline(script: dict, fps: int = 30) -> list[dict]:
    """
    从脚本的 live2d 轨解析 action 时间线。
    
    返回格式:
    [
        {
            "startFrame": 0,
            "action": "exp_curious",
            "expression": "exp_04",      # 或 None
            "motion": {"group":"","index":2}  # 或 None
        },
        ...
    ]
    """
    tracks = script.get("tracks", {})
    live2d_items = tracks.get("live2d", [])
    
    timeline = []
    for item in live2d_items:
        action = item.get("action", item.get("emotion", "exp_neutral"))
        start_ms = item.get("start_ms", 0)
        start_frame = round(start_ms / 1000 * fps)
        
        mapping = ACTION_MAP.get(action, ACTION_MAP.get("exp_neutral"))
        
        entry = {
            "startFrame": start_frame,
            "action": action,
            "expression": mapping.get("expression") if mapping else None,
            "motion": mapping.get("motion") if mapping else None,
        }
        timeline.append(entry)
    
    # 如果没有 live2d 轨，默认 idle
    if not timeline:
        timeline.append({
            "startFrame": 0,
            "action": "exp_neutral",
            "expression": "exp_05",
            "motion": None,
        })
    
    return timeline


def render_live2d(
    script: dict,
    audio_dir: Path,
    output_dir: Path,
    remotion_dir: Path = REMOTION_DIR,
    timeout: int = 36000,
) -> Path | None:
    """
    渲染单个脚本的 Live2D 透明视频
    """
    script_id = script.get("id", "unknown")
    total_ms = script.get("total_duration_ms", 30000)
    total_frames = math.ceil(total_ms / 1000 * FPS)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{script_id}_live2d.webm"

    # 提取 volumes
    volumes = build_live2d_volumes(script, audio_dir, FPS)

    # 解析 live2d 轨的 action 时间线
    action_timeline = _build_action_timeline(script, FPS)

    # 写 props 文件
    props = {
        "modelUrl": MODEL_URL,
        "volumes": volumes,
        "scale": 0.45,
        "offsetX": 0,
        "offsetY": 50,
        "actionTimeline": action_timeline,
    }
    props_file = output_dir / f"{script_id}_live2d.props.json"
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(props, f)

    # 判断是否有 special 动作，需要不透明背景
    has_special = any(
        a.get("action", "").startswith("sp_") for a in action_timeline
    )

    # 调用 Remotion 渲染
    # concurrency=1: Live2D 动画有状态（每帧依赖前一帧），不能并行
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "Live2D",
        f"--props={props_file.resolve()}",
        "--gl=angle",
        "--codec=vp9",
        "--pixel-format=yuva420p",
        "--concurrency=1",
        f"--output={output_path.resolve()}",
        f"--frames=0-{total_frames - 1}",
    ]

    logger.info(
        f"[live2d] 渲染: {script_id}, {total_frames} frames -> {output_path.name}"
    )

    # VP9 alpha 编码很慢（约 5 帧/秒），动态超时
    dynamic_timeout = max(timeout, int(total_frames / 5) + 120)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(remotion_dir),
            capture_output=True,
            text=True,
            timeout=dynamic_timeout,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )

        if result.returncode == 0:
            logger.info(f"[live2d] ✅ {output_path.name}")
            return output_path
        else:
            logger.error(f"[live2d] ❌ {script_id}: {result.stderr[:300]}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"[live2d] ⏰ 超时 ({dynamic_timeout}s): {script_id}")
        return None
    except Exception as e:
        logger.error(f"[live2d] 💥 异常: {e}")
        return None


def step_live2d(date_str: str, max_workers: int = 2, progress_callback=None):
    """
    批量渲染所有脚本的 Live2D 轨
    """
    data_dir = Path("data") / date_str
    scripts_dir = data_dir / "scripts_aligned"
    audio_dir = data_dir / "audio"
    output_dir = data_dir / "live2d"

    if not scripts_dir.exists():
        logger.error(f"[live2d] scripts_aligned 不存在: {scripts_dir}")
        return

    scripts = []
    for f in sorted(scripts_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fp:
            script = json.load(fp)
            script.setdefault("id", f.stem)
            scripts.append(script)

    logger.info(f"[live2d] 批渲染: {len(scripts)} 脚本")
    if progress_callback:
        progress_callback(f"准备渲染 {len(scripts)} 个 Live2D 脚本", 0.0)

    success = 0
    skip = 0
    fail = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for script in scripts:
            script_id = script["id"]
            out_file = output_dir / f"{script_id}_live2d.webm"
            
            # 检查已有文件时长是否匹配当前脚本
            if out_file.exists():
                expected_ms = script.get("total_duration_ms", 30000)
                expected_s = expected_ms / 1000.0
                try:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(out_file)],
                        capture_output=True, text=True, timeout=10,
                    )
                    actual_s = float(probe.stdout.strip()) if probe.returncode == 0 else 0
                except Exception:
                    actual_s = 0
                
                # 允许 2 秒误差
                if abs(actual_s - expected_s) <= 2.0:
                    skip += 1
                    logger.info(f"[live2d] ⏭️ 已存在: {script_id} ({actual_s:.1f}s)")
                    if progress_callback:
                        progress_callback(f"Live2D 缓存: {script_id}", 0.1)
                    continue
                else:
                    logger.info(f"[live2d] 🔄 时长不匹配 ({actual_s:.1f}s vs {expected_s:.1f}s), 重渲: {script_id}")
                    out_file.unlink()

            future = executor.submit(
                render_live2d, script, audio_dir, output_dir
            )
            futures[future] = script_id

        completed = 0
        for future in as_completed(futures):
            script_id = futures[future]
            try:
                result = future.result()
                if result:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                logger.error(f"[live2d] 💥 {script_id}: {e}")
                fail += 1
            completed += 1
            if progress_callback:
                progress_callback(
                    f"Live2D [{completed}/{len(futures)}]: {script_id}",
                    0.1 + 0.85 * completed / max(len(futures), 1),
                )

    logger.info(
        f"[live2d] 完成: {success} 成功, {skip} 跳过, {fail} 失败"
    )
    if progress_callback:
        progress_callback(f"Live2D 完成: {success} 成功, {skip} 跳过", 1.0)
