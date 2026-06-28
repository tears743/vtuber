"""查看前几条 voice 台词内容"""
import json

with open("data/2026-06-16/scripts/hot_daily.json", "r", encoding="utf-8") as f:
    script = json.load(f)

voice = script["tracks"]["voice"]
for i, v in enumerate(voice[:6]):
    text = v.get("text", "")[:80]
    sub = v.get("subtitle", "")[:80]
    start = v["start_ms"]
    end = start + v["duration_ms"]
    print(f"voice[{i}] [{start}-{end}ms]")
    print(f"  text: {text}")
    print(f"  sub:  {sub}")
    print()
