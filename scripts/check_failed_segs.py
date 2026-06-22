"""Check which segments failed"""
import json
from pathlib import Path

script_path = Path(r"D:\workspace\videoFactory\data\2026-06-16\scripts_aligned\hot_daily.json")
data = json.loads(script_path.read_text(encoding="utf-8"))

visual = sorted(data["tracks"]["visual"], key=lambda v: v["start_ms"])

# seg_15 and seg_20 failed (based on log showing seg_15 and seg_20 errors)
for i in [15, 20]:
    if i < len(visual):
        v = visual[i]
        src = v.get("source", "")
        print(f"seg_{i:02d}: type={v['type']} dur={v['duration_ms']}ms pa={v.get('play_audio','')} src={src[-80:]}")
        if src:
            p = Path(src)
            print(f"  exists: {p.exists()}, size: {p.stat().st_size if p.exists() else 'N/A'}")
