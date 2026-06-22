"""检查 visual 轨按时间排序后的重叠"""
import json
from pathlib import Path

script_path = Path(r"D:\workspace\videoFactory\data\2026-06-16\scripts_aligned\hot_daily.json")
data = json.loads(script_path.read_text(encoding="utf-8"))

visual = data["tracks"]["visual"]

# 按 start_ms 排序
sorted_vis = sorted(visual, key=lambda v: v["start_ms"])

print("=== VISUAL ITEMS (sorted by start_ms) ===")
for i, v in enumerate(sorted_vis):
    src = str(v.get("source", ""))
    src_short = Path(src).parent.name + "/" + Path(src).name if src else v.get("component", "")
    start_s = v["start_ms"] / 1000
    end_s = (v["start_ms"] + v["duration_ms"]) / 1000
    pa = " [PA]" if v.get("play_audio") else ""
    print(f"  [{i:2d}] {start_s:7.1f}s - {end_s:7.1f}s  type={v['type']:10s}{pa} {src_short}")

print("\n=== OVERLAP CHECK (sorted) ===")
overlaps = 0
for i in range(len(sorted_vis) - 1):
    a = sorted_vis[i]
    b = sorted_vis[i + 1]
    a_end = a["start_ms"] + a["duration_ms"]
    b_start = b["start_ms"]
    if b_start < a_end:
        overlap_ms = a_end - b_start
        overlaps += 1
        print(f"  OVERLAP [{i}]-[{i+1}]: {overlap_ms/1000:.1f}s")
        src_a = Path(str(a.get("source",""))).parent.name if a.get("source") else a.get("component","")
        src_b = Path(str(b.get("source",""))).parent.name if b.get("source") else b.get("component","")
        print(f"    [{i}] {src_a} ends at {a_end/1000:.1f}s")
        print(f"    [{i+1}] {src_b} starts at {b_start/1000:.1f}s")

if overlaps == 0:
    print("  ✅ No overlaps!")
else:
    print(f"\n  ❌ {overlaps} overlaps found")
