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
    
    # 收集 play_audio 段（原始时间），并用源视频实际时长修正 duration
    # 保存 (pa_start, original_dur, expanded_dur) 用于正确构建 time_shifts
    play_audio_ranges = []
    for vitem in visual_items:
        if vitem.get("type") == "video_clip" and vitem.get("play_audio"):
            pa_start = vitem.get("start_ms", 0)
            pa_dur = vitem.get("duration_ms", 0)
            original_dur = pa_dur  # 保存原始脚本中的时长
            
            # 用 ffprobe 读取源视频实际时长，确保不超出视频边界
            source = vitem.get("source", "")
            if source and Path(source).exists():
                actual_dur_ms = _get_video_duration_ms(Path(source))
                if actual_dur_ms:
                    time_range = vitem.get("time_range", [0])
                    range_start_ms = int((time_range[0] if time_range else 0) * 1000)
                    
                    # 如果 time_range 有明确的 end 值（精确裁剪模式），直接用它
                    if len(time_range) >= 2 and time_range[1] > time_range[0]:
                        clip_dur_ms = int((time_range[1] - time_range[0]) * 1000)
                        pa_dur = clip_dur_ms
                        vitem["duration_ms"] = pa_dur
                    else:
                        # 旧模式：从 range_start 到视频末尾全部播放
                        available_ms = max(0, actual_dur_ms - range_start_ms)
                        if available_ms > pa_dur:
                            pa_dur = available_ms
                            range_end = range_start_ms / 1000.0 + pa_dur / 1000.0
                            vitem["duration_ms"] = pa_dur
                            vitem["time_range"] = [time_range[0] if time_range else 0, range_end]
                            logger.info(f"[realigner] 视频原声扩展: {original_dur}ms -> {pa_dur}ms ({Path(source).parent.name})")
            
            # (pa_start, original_dur, expanded_dur)
            play_audio_ranges.append((pa_start, original_dur, pa_dur))
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
    
    for pi, (pa_start, pa_original_dur, pa_expanded_dur) in enumerate(play_audio_ranges):
        # event: ("pa", index, old_start, old_dur_for_shifts, new_dur_for_placement)
        events.append(("pa", pi, pa_start, pa_original_dur, pa_expanded_dur))
    
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
    
    # 标记紧接 PA 的有文本 voice 段（引导语如"听听主播怎么说"）
    voice_before_pa = set()
    for ei in range(len(events) - 1):
        evt = events[ei]
        nxt = events[ei + 1]
        if evt[0] == "voice" and nxt[0] == "pa":
            voice_idx = evt[1]
            voice_text = voice_items[voice_idx].get("text", "").strip()
            if voice_text:  # 有文本的引导语
                voice_before_pa.add(voice_idx)
    
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
            
            # 引导语保护：紧接 PA 的 voice 段，如果 TTS 时长超过原始 2 倍或超过 5 秒，
            # 强制 cap（引导语只是一句话，不应超 5 秒）
            if idx in voice_before_pa and new_dur > min(old_dur * 2, 5000):
                capped_dur = min(old_dur + 1000, 5000)  # 最多 5 秒
                logger.warning(
                    f"[realigner] 引导语 voice[{idx}] TTS 过长: "
                    f"{new_dur}ms -> cap 到 {capped_dur}ms (原始 {old_dur}ms)"
                )
                new_dur = capped_dur
            
            # voice 之间保留原始间隔（非固定 300ms）
            # 原始间隔中可能有 video_clip(play_audio=false) 画面在播放
            if time_shifts:
                last_new_end = time_shifts[-1][3]
                last_old_end = time_shifts[-1][1]
                # 原始间隔 = 当前事件原始 start - 上一个事件原始 end
                original_gap = old_start - last_old_end
                # 保留原始间隔，但最少 300ms
                preserved_gap = max(original_gap, 300)
                current_ms = max(current_ms, last_new_end + preserved_gap)
            
            voice_timing[idx] = (current_ms, new_dur)
            time_shifts.append((old_start, old_start + old_dur, current_ms, current_ms + new_dur))
            
            # 更新 voice item
            voice_items[idx]["start_ms"] = current_ms
            voice_items[idx]["duration_ms"] = new_dur
            voice_items[idx]["audio_file"] = f"audio/{script_id}/voice_{idx:02d}.wav"
            
            current_ms += new_dur
            
        elif evt_type == "pa":
            pi, old_start = evt[1], evt[2]
            pa_original_dur = evt[3]   # 原始脚本时长（用于 old 范围）
            pa_expanded_dur = evt[4]   # 扩展后时长（用于 new 范围/实际放置）
            
            # play_audio 紧接前一个 voice（仅 200ms 间隔）
            if time_shifts:
                current_ms = max(current_ms, time_shifts[-1][3] + 200)
            
            pa_timing[pi] = (current_ms, pa_expanded_dur)
            # old 范围用原始时长，new 范围用扩展后时长
            # 这样 map_time 对 old_start+original_dur 之后的内容正确映射到 PA 之后
            time_shifts.append((old_start, old_start + pa_original_dur, current_ms, current_ms + pa_expanded_dur))
            
            # 同步设置伴随的空 voice 段（和 pa 完全重合）
            for ei2 in range(len(events) - 1):
                if events[ei2][0] == "voice" and events[ei2][1] in empty_voice_for_pa:
                    if ei2 + 1 < len(events) and events[ei2 + 1][0] == "pa" and events[ei2 + 1][1] == pi:
                        vidx = events[ei2][1]
                        voice_timing[vidx] = (current_ms, pa_expanded_dur)
                        voice_items[vidx]["start_ms"] = current_ms
                        voice_items[vidx]["duration_ms"] = pa_expanded_dur
                        break
            
            current_ms += pa_expanded_dur
    
    # Step 2: live2d 轨用 map_time 对齐（与 voice 解耦）
    # 这样 Mili 可以边做动作边说话，不需要等动作完成
    # 注意：map_time 函数在后面定义，所以移到 Step 3 之后处理
    
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
    
    # 所有非 PA visual items 统一用 map_time 对齐
    # 这样保持它们与对应语音段的相对时间关系
    for item in visual_items:
        if item.get("type") == "video_clip" and item.get("play_audio"):
            continue  # PA items 已在上面精确定位
        
        old_start = item.get("start_ms", 0)
        old_dur = item.get("duration_ms", 0)
        old_end = old_start + old_dur
        
        new_start = map_time(old_start)
        new_end = map_time(old_end)
        
        item["start_ms"] = new_start
        item["duration_ms"] = max(new_end - new_start, 100)
    
    # overlay/background/live2d 轨用 map_time
    # live2d 与 voice 解耦：动作和说话可以同时进行
    for track_name in ("overlay", "background", "live2d"):
        items = tracks.get(track_name, [])
        for item in items:
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
    
    # Step 4: 排序 visual 轨确保按时间顺序
    tracks["visual"] = sorted(tracks.get("visual", []), key=lambda x: x.get("start_ms", 0))
    
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

