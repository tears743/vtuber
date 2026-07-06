"""
Step 2: Timeline Realigner - 用实际音频时长修正脚本时间线

简单版：按原始时间顺序逐个调整
1. 所有 item 按原始 start_ms 排序
2. 从头到尾走，维护 cursor（当前时间点）
3. voice/PA 会改变时长 → cursor 跟着变
4. 其他 item 按原始间隔跟着 cursor 走
"""
import json
import logging
import subprocess
from pathlib import Path
from copy import deepcopy

logger = logging.getLogger(__name__)


def _get_video_duration_ms(path: Path) -> int | None:
    """用 ffprobe 获取视频时长（毫秒）"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()) * 1000)
    except Exception:
        pass
    return None


def realign_timeline(script: dict, audio_durations: dict[int, int]) -> dict:
    """
    用实际音频时长修正脚本 timeline。
    
    Args:
        script: 原始脚本 dict
        audio_durations: {voice_index: actual_duration_ms}
    
    Returns:
        修正后的 script (deep copy，不改原始数据)
    """
    aligned = deepcopy(script)
    
    # 新格式: tracks
    tracks = aligned.get("tracks")
    if tracks and "voice" in tracks:
        return _realign_tracks(aligned, audio_durations)
    
    # 旧格式: segments
    return _realign_segments(aligned, audio_durations)


def _realign_tracks(aligned: dict, audio_durations: dict[int, int]) -> dict:
    """多轨模式对齐 — 累积偏移法
    
    核心思路：
    1. 所有 item 按原始 start_ms 排序
    2. 维护 cumulative_delta（累积偏移量）
    3. 所有元素的 new_start = orig_start + cumulative_delta
    4. 只有 voice 和 play_audio 的 video_clip 会改变时长，产生新的 delta
    5. 其他元素（visual/overlay/live2d/background）只偏移 start，不改 duration
    
    这样并行关系保持（原始脚本中同时开始的元素偏移后还是同时开始）。
    """
    tracks = aligned["tracks"]
    voice_items = tracks.get("voice", [])
    visual_items = tracks.get("visual", [])
    script_id = aligned.get("id", "unknown")
    
    if not voice_items:
        return aligned
    
    # ─── Step 1: 预计算每个 voice 的实际时长 ───
    voice_actual_dur = {}  # {voice_index: actual_duration_ms}
    changes = 0
    for i, item in enumerate(voice_items):
        old_dur = item.get("duration_ms", 0)
        if i in audio_durations:
            new_dur = audio_durations[i] + 200  # +200ms 尾部留白
            voice_actual_dur[i] = new_dur
            if abs(new_dur - old_dur) > 100:
                changes += 1
        else:
            voice_actual_dur[i] = old_dur
    
    # ─── Step 2: 预计算 play_audio video_clip 的实际时长 ───
    pa_actual_dur = {}  # {id(item): actual_dur_ms}
    for vitem in visual_items:
        if vitem.get("type") == "video_clip" and vitem.get("play_audio"):
            pa_dur = vitem.get("duration_ms", 0)
            source = vitem.get("source", "")
            if source and Path(source).exists():
                actual_dur_ms = _get_video_duration_ms(Path(source))
                if actual_dur_ms:
                    time_range = vitem.get("time_range", [0])
                    if len(time_range) >= 2 and time_range[1] > time_range[0]:
                        pa_dur = int((time_range[1] - time_range[0]) * 1000)
                    else:
                        range_start_ms = int((time_range[0] if time_range else 0) * 1000)
                        pa_dur = max(0, actual_dur_ms - range_start_ms)
            pa_actual_dur[id(vitem)] = pa_dur
    
    # ─── Step 3: 构建统一事件列表 ───
    all_events = []
    
    for i, item in enumerate(voice_items):
        all_events.append({
            "orig_start": item.get("start_ms", 0),
            "type": "voice",
            "item": item,
            "voice_idx": i,
        })
    
    for item in visual_items:
        is_pa = item.get("type") == "video_clip" and item.get("play_audio")
        all_events.append({
            "orig_start": item.get("start_ms", 0),
            "type": "pa_visual" if is_pa else "visual",
            "item": item,
        })
    
    for track_name in ("overlay", "live2d", "background"):
        for item in tracks.get(track_name, []):
            all_events.append({
                "orig_start": item.get("start_ms", 0),
                "type": track_name,
                "item": item,
            })
    
    # 按原始 start_ms 排序（稳定排序保持原始顺序）
    all_events.sort(key=lambda e: e["orig_start"])
    
    # ─── Step 4: 遍历，累积 delta 偏移 ───
    cumulative_delta = 0
    
    for evt in all_events:
        etype = evt["type"]
        item = evt["item"]
        orig_start = evt["orig_start"]
        
        # 所有元素统一偏移 start
        new_start = max(0, orig_start + cumulative_delta)
        item["start_ms"] = new_start
        
        if etype == "voice":
            # voice：替换 duration，累积 delta
            vi = evt["voice_idx"]
            old_dur = item.get("duration_ms", 0)
            new_dur = voice_actual_dur[vi]
            item["duration_ms"] = new_dur
            item["audio_file"] = f"audio/{script_id}/voice_{vi:02d}.wav"
            cumulative_delta += (new_dur - old_dur)
            
        elif etype == "pa_visual":
            # play_audio video_clip：替换 duration，累积 delta
            old_dur = item.get("duration_ms", 0)
            new_dur = pa_actual_dur.get(id(item), old_dur)
            item["duration_ms"] = new_dur
            cumulative_delta += (new_dur - old_dur)
        
        # 其他类型（visual/overlay/live2d/background）：只改了 start，不改 duration，不累积
    
    # ─── Step 5: 排序 visual 轨（确保时间顺序）───
    tracks["visual"] = sorted(visual_items, key=lambda x: x.get("start_ms", 0))
    
    # ─── Step 6: voice 去重叠保底 ───
    for i in range(len(voice_items) - 1):
        end_i = voice_items[i]["start_ms"] + voice_items[i]["duration_ms"]
        start_next = voice_items[i + 1]["start_ms"]
        if end_i > start_next:
            # 推后后续所有 voice
            shift = end_i - start_next + 50
            for j in range(i + 1, len(voice_items)):
                voice_items[j]["start_ms"] += shift
    
    # ─── Step 7: 更新 total_duration_ms ───
    max_end = 0
    for track_name, items in tracks.items():
        for item in items:
            end = item.get("start_ms", 0) + item.get("duration_ms", 0)
            if end > max_end:
                max_end = end
    
    old_total = aligned.get("total_duration_ms", 0)
    aligned["total_duration_ms"] = max_end
    
    logger.info(
        f"[realigner] {aligned.get('id', '?')}: "
        f"{old_total}ms -> {max_end}ms "
        f"({changes} voice items adjusted, delta: {max_end - old_total:+d}ms)"
    )
    
    return aligned


def _realign_segments(aligned: dict, audio_durations: dict[int, int]) -> dict:
    """旧格式兼容：segments 模式对齐"""
    segments = aligned.get("segments", [])
    
    if not segments:
        return aligned
    
    current_ms = 0
    changes = 0
    
    for i, seg in enumerate(segments):
        seg["start_ms"] = current_ms
        
        if seg.get("type") == "live2d_talk" and i in audio_durations:
            old_dur = seg.get("duration_ms", 0)
            new_dur = audio_durations[i] + 200
            seg["duration_ms"] = new_dur
            
            if abs(new_dur - old_dur) > 100:
                logger.debug(
                    f"  seg[{i}] live2d_talk: {old_dur}ms -> {new_dur}ms "
                    f"(delta: {new_dur - old_dur:+d}ms)"
                )
                changes += 1
        
        current_ms += seg["duration_ms"]
    
    old_total = aligned.get("total_duration_ms", 0)
    aligned["total_duration_ms"] = current_ms
    
    logger.info(
        f"[realigner] {aligned.get('id', '?')}: "
        f"{old_total}ms -> {current_ms}ms "
        f"({changes} segments adjusted, delta: {current_ms - old_total:+d}ms)"
    )
    
    return aligned


def realign_script_file(
    script_path: Path,
    audio_durations: dict[int, int],
    output_path: Path,
) -> Path:
    """
    读取脚本文件 → 对齐 → 写入新文件
    """
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    
    aligned = realign_timeline(script, audio_durations)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(aligned, f, ensure_ascii=False, indent=2)
    
    return output_path
