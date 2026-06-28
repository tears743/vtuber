"""检查引导语和画面的对应关系"""
import json

with open("data/2026-06-16/scripts/hot_daily.json", "r", encoding="utf-8") as f:
    script = json.load(f)

voice = script["tracks"]["voice"]
visual = script["tracks"]["visual"]

for i, v in enumerate(visual):
    if v.get("type") == "video_clip" and not v.get("play_audio"):
        v_start = v["start_ms"]
        v_end = v_start + v["duration_ms"]
        src = v.get("source", "")
        tr = v.get("time_range", [])
        print(f"--- visual[{i}] video_clip (muted)")
        print(f"    source: ...{src[-50:]}")
        print(f"    time_range={tr}, start_ms={v_start}, duration_ms={v['duration_ms']}")
        # 找这个时间段内的 voice
        for vo in voice:
            vo_start = vo["start_ms"]
            vo_end = vo_start + vo["duration_ms"]
            if vo_start < v_end and vo_end > v_start:
                text = vo.get("subtitle", vo.get("text", ""))[:60]
                print(f"    voice: [{vo_start}-{vo_end}ms] {text}")
        print()
