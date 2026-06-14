"""
Step 2: Timeline Realigner - 用实际音频时长修正脚本时间线

多轨模式：
1. voice 轨: 用 TTS 实际时长替换预设时长，重新计算 start_ms
2. live2d 轨: 跟随 voice 轨时间（同步表情动作）
3. visual/overlay/background: 保持原设计时间

兼容旧格式 (segments[])
"""
import json
import logging
from pathlib import Path
from copy import deepcopy

logger = logging.getLogger(__name__)


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
    """多轨模式对齐"""
    tracks = aligned["tracks"]
    voice_items = tracks.get("voice", [])
    
    if not voice_items:
        return aligned
    
    # Step 1: 修正 voice 轨时长和时间线，记录时间偏移
    current_ms = 0
    changes = 0
    voice_timing = []  # 记录 [(start_ms, duration_ms)] 用于同步其他轨
    time_shifts = []   # 记录 [(old_start, old_end, new_start, new_end)]
    script_id = aligned.get("id", "unknown")
    
    for i, item in enumerate(voice_items):
        old_start = item.get("start_ms", 0)
        old_dur = item.get("duration_ms", 0)
        old_end = old_start + old_dur
        
        # 计算间隔（voice 之间可能有 visual-only 时段）
        if i == 0:
            # 第一个 voice 的起始位置保持不变
            current_ms = old_start
        else:
            # 后续 voice: 保持原有间隔，但限制最大间隔为 2 秒
            # （原始脚本中可能有 play_audio 段占据的大间隔，对齐后不再需要）
            prev_end = voice_items[i-1].get("start_ms", 0) + voice_items[i-1].get("duration_ms", 0)
            gap = old_start - prev_end
            if gap < 0:
                gap = 0
            gap = min(gap, 2000)  # 最大 2 秒转场间隔
            current_ms = voice_timing[-1][0] + voice_timing[-1][1] + gap
        
        item["start_ms"] = current_ms
        
        # 添加音频文件引用
        item["audio_file"] = f"audio/{script_id}/voice_{i:02d}.wav"
        
        if i in audio_durations:
            # 实际音频时长 + 200ms 尾部缓冲
            new_dur = audio_durations[i] + 200
            item["duration_ms"] = new_dur
            
            if abs(new_dur - old_dur) > 100:
                logger.debug(
                    f"  voice[{i}]: {old_dur}ms -> {new_dur}ms "
                    f"(delta: {new_dur - old_dur:+d}ms)"
                )
                changes += 1
        else:
            new_dur = old_dur
        
        voice_timing.append((current_ms, new_dur))
        time_shifts.append((old_start, old_end, current_ms, current_ms + new_dur))
        current_ms += new_dur
    
    # Step 2: live2d 轨跟随 voice 轨时间
    live2d_items = tracks.get("live2d", [])
    for i, item in enumerate(live2d_items):
        if i < len(voice_timing):
            item["start_ms"] = voice_timing[i][0]
            item["duration_ms"] = voice_timing[i][1]
    
    # Step 2.5: 同步调整 visual/overlay/background 轨
    # 构建时间映射函数：将原始时间点映射到新时间点
    def map_time(old_ms: int) -> int:
        """将原始时间点映射到对齐后的时间点"""
        if not time_shifts:
            return old_ms
        
        # 在第一个 voice 之前的保持不变
        if old_ms <= time_shifts[0][0]:
            return old_ms
        
        # 在最后一个 voice 之后的按累积偏移调整
        last_old_end = time_shifts[-1][1]
        last_new_end = time_shifts[-1][3]
        if old_ms >= last_old_end:
            offset = last_new_end - last_old_end
            return old_ms + offset
        
        # 在两个 voice 之间的：线性插值
        for idx in range(len(time_shifts)):
            old_start, old_end, new_start, new_end = time_shifts[idx]
            
            # 在这个 voice 范围内
            if old_start <= old_ms <= old_end:
                if old_end == old_start:
                    return new_start
                ratio = (old_ms - old_start) / (old_end - old_start)
                return int(new_start + ratio * (new_end - new_start))
            
            # 在两个 voice 之间的间隔
            if idx < len(time_shifts) - 1:
                next_old_start = time_shifts[idx + 1][0]
                next_new_start = time_shifts[idx + 1][2]
                if old_end <= old_ms <= next_old_start:
                    gap_old = next_old_start - old_end
                    if gap_old == 0:
                        return new_end
                    ratio = (old_ms - old_end) / gap_old
                    gap_new = next_new_start - new_end
                    return int(new_end + ratio * gap_new)
        
        return old_ms
    
    for track_name in ("visual", "overlay", "background"):
        items = tracks.get(track_name, [])
        for item in items:
            old_start = item.get("start_ms", 0)
            old_dur = item.get("duration_ms", 0)
            old_end = old_start + old_dur
            
            new_start = map_time(old_start)
            new_end = map_time(old_end)
            
            item["start_ms"] = new_start
            item["duration_ms"] = max(new_end - new_start, 100)  # 最少 100ms
    
    # Step 3: 更新 total_duration_ms
    # 取所有轨的最大结束时间
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

