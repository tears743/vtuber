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
    """多轨模式对齐
    
    核心思路：
    1. 从原始脚本构建"事件序列" — voice 说话段 + play_audio 静默段
    2. voice 段用 TTS 实际时长替换
    3. play_audio 段保持原时长
    4. 顺序排列，确保不重叠
    5. 用新旧时间映射同步 visual/overlay/background 轨
    """
    tracks = aligned["tracks"]
    voice_items = tracks.get("voice", [])
    
    if not voice_items:
        return aligned
    
    visual_items = tracks.get("visual", [])
    script_id = aligned.get("id", "unknown")
    
    # 收集 play_audio 段（原始时间）
    play_audio_ranges = []
    for vitem in visual_items:
        if vitem.get("type") == "video_clip" and vitem.get("play_audio"):
            pa_start = vitem.get("start_ms", 0)
            pa_dur = vitem.get("duration_ms", 0)
            play_audio_ranges.append((pa_start, pa_start + pa_dur, pa_dur))
    play_audio_ranges.sort(key=lambda x: x[0])
    
    # 构建事件序列：按原始 start_ms 排序所有 voice + play_audio
    # voice event: ("voice", index, old_start, old_dur, new_dur)
    # pa event: ("pa", pa_index, old_start, old_end, pa_dur)
    events = []
    
    changes = 0
    for i, item in enumerate(voice_items):
        old_start = item.get("start_ms", 0)
        old_dur = item.get("duration_ms", 0)
        if i in audio_durations:
            new_dur = audio_durations[i] + 200
            if abs(new_dur - old_dur) > 100:
                changes += 1
        else:
            new_dur = old_dur
        events.append(("voice", i, old_start, old_dur, new_dur))
    
    for pi, (pa_start, pa_end, pa_dur) in enumerate(play_audio_ranges):
        events.append(("pa", pi, pa_start, pa_dur, pa_dur))
    
    # 按原始 start_ms 排序
    events.sort(key=lambda e: e[2])
    
    # 识别空 voice 段（text=""）并标记为 pa 的"伴随"段
    # 空 voice 段紧邻 pa 时，不独立占用时间，而是和 pa 共享时间窗口
    empty_voice_for_pa = set()  # voice indices that are silent slots for play_audio
    for ei in range(len(events) - 1):
        evt = events[ei]
        nxt = events[ei + 1]
        if (evt[0] == "voice" and nxt[0] == "pa"):
            voice_idx = evt[1]
            voice_text = voice_items[voice_idx].get("text", "").strip()
            if not voice_text:
                empty_voice_for_pa.add(voice_idx)
    
    # 顺序放置事件
    current_ms = events[0][2] if events else 0  # 第一个事件的原始起始
    voice_timing = {}  # {voice_index: (new_start, new_dur)}
    pa_timing = {}     # {pa_index: (new_start, new_dur)}
    time_shifts = []   # [(old_start, old_end, new_start, new_end)]
    
    for evt in events:
        evt_type = evt[0]
        
        if evt_type == "voice":
            idx, old_start, old_dur, new_dur = evt[1], evt[2], evt[3], evt[4]
            
            # 空 voice 段（伴随 pa）：跳过，稍后和 pa 同步
            if idx in empty_voice_for_pa:
                continue
            
            # voice 之间加 300ms 间隔
            if time_shifts:
                current_ms = max(current_ms, time_shifts[-1][3] + 300)
            
            voice_timing[idx] = (current_ms, new_dur)
            time_shifts.append((old_start, old_start + old_dur, current_ms, current_ms + new_dur))
            
            # 更新 voice item
            voice_items[idx]["start_ms"] = current_ms
            voice_items[idx]["duration_ms"] = new_dur
            voice_items[idx]["audio_file"] = f"audio/{script_id}/voice_{idx:02d}.wav"
            
            current_ms += new_dur
            
        elif evt_type == "pa":
            pi, old_start, old_dur = evt[1], evt[2], evt[3]
            
            # play_audio 紧接前一个 voice（仅 200ms 间隔）
            if time_shifts:
                current_ms = max(current_ms, time_shifts[-1][3] + 200)
            
            pa_timing[pi] = (current_ms, old_dur)
            time_shifts.append((old_start, old_start + old_dur, current_ms, current_ms + old_dur))
            
            # 同步设置伴随的空 voice 段（和 pa 完全重合）
            for ei2 in range(len(events) - 1):
                if events[ei2][0] == "voice" and events[ei2][1] in empty_voice_for_pa:
                    if ei2 + 1 < len(events) and events[ei2 + 1][0] == "pa" and events[ei2 + 1][1] == pi:
                        vidx = events[ei2][1]
                        voice_timing[vidx] = (current_ms, old_dur)
                        voice_items[vidx]["start_ms"] = current_ms
                        voice_items[vidx]["duration_ms"] = old_dur
                        break
            
            current_ms += old_dur
    
    # Step 2: live2d 轨跟随 voice 轨时间
    live2d_items = tracks.get("live2d", [])
    for i, item in enumerate(live2d_items):
        if i in voice_timing:
            item["start_ms"] = voice_timing[i][0]
            item["duration_ms"] = voice_timing[i][1]
    
    # Step 3: 同步调整 visual/overlay/background 轨
    # 构建时间映射函数
    time_shifts.sort(key=lambda x: x[0])
    
    def map_time(old_ms: int) -> int:
        """将原始时间点映射到对齐后的时间点"""
        if not time_shifts:
            return old_ms
        
        # 在第一个事件之前的保持不变
        if old_ms <= time_shifts[0][0]:
            return old_ms
        
        # 在最后一个事件之后的按累积偏移调整
        last_old_end = time_shifts[-1][1]
        last_new_end = time_shifts[-1][3]
        if old_ms >= last_old_end:
            offset = last_new_end - last_old_end
            return old_ms + offset
        
        # 在事件范围内或间隔内：线性插值
        for idx in range(len(time_shifts)):
            old_start, old_end, new_start, new_end = time_shifts[idx]
            
            if old_start <= old_ms <= old_end:
                if old_end == old_start:
                    return new_start
                ratio = (old_ms - old_start) / (old_end - old_start)
                return int(new_start + ratio * (new_end - new_start))
            
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
    
    # 更新 play_audio visual items 的时间（精确定位）
    pa_idx = 0
    for item in visual_items:
        if item.get("type") == "video_clip" and item.get("play_audio"):
            if pa_idx in pa_timing:
                item["start_ms"] = pa_timing[pa_idx][0]
                item["duration_ms"] = pa_timing[pa_idx][1]
            pa_idx += 1
    
    # 其他 visual/overlay/background 用 map_time
    for track_name in ("visual", "overlay", "background"):
        items = tracks.get(track_name, [])
        for item in items:
            # play_audio 的 visual 已经精确定位了，跳过
            if item.get("type") == "video_clip" and item.get("play_audio"):
                continue
            old_start = item.get("start_ms", 0)
            old_dur = item.get("duration_ms", 0)
            old_end = old_start + old_dur
            
            new_start = map_time(old_start)
            new_end = map_time(old_end)
            
            item["start_ms"] = new_start
            item["duration_ms"] = max(new_end - new_start, 100)
    
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

