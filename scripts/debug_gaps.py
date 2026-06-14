import json

for name in ["hot_daily", "ai_daily"]:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    # Original script
    with open(f"data/2026-06-12/scripts/{name}.json", "r", encoding="utf-8") as f:
        orig = json.load(f)
    
    # Aligned script
    with open(f"data/2026-06-12/scripts_aligned/{name}.json", "r", encoding="utf-8") as f:
        aligned = json.load(f)
    
    orig_voice = orig["tracks"]["voice"]
    aligned_voice = aligned["tracks"]["voice"]
    
    print(f"\nOriginal: {len(orig_voice)} voice items, total={orig.get('total_duration_ms',0)}ms")
    print(f"Aligned:  {len(aligned_voice)} voice items, total={aligned.get('total_duration_ms',0)}ms")
    
    # Check original gaps
    print(f"\n--- Original gaps > 2s ---")
    for i in range(1, len(orig_voice)):
        prev_end = orig_voice[i-1]["start_ms"] + orig_voice[i-1]["duration_ms"]
        gap = orig_voice[i]["start_ms"] - prev_end
        if gap > 2000:
            print(f"  [{i-1}]->[{i}] gap={gap}ms  subtitle_prev: {orig_voice[i-1].get('subtitle','')[:25]}...")
    
    # Check aligned gaps
    print(f"\n--- Aligned gaps > 3s ---")
    for i in range(1, len(aligned_voice)):
        prev_end = aligned_voice[i-1]["start_ms"] + aligned_voice[i-1]["duration_ms"]
        gap = aligned_voice[i]["start_ms"] - prev_end
        if gap > 3000:
            t_sec = aligned_voice[i]["start_ms"] / 1000
            print(f"  [{i-1}]->[{i}] gap={gap}ms (at {t_sec:.1f}s)  subtitle: {aligned_voice[i].get('subtitle','')[:30]}...")
    
    # Check play_audio video clips
    visual = orig["tracks"].get("visual", [])
    play_audio_clips = [v for v in visual if v.get("type") == "video_clip" and v.get("play_audio")]
    if play_audio_clips:
        print(f"\n--- play_audio clips: {len(play_audio_clips)} ---")
        for v in play_audio_clips:
            print(f"  start={v['start_ms']}ms dur={v['duration_ms']}ms")
    else:
        print(f"\n--- No play_audio clips ---")
