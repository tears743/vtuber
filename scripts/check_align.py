"""检查对齐后 voice 和 play_audio 是否有重叠"""
import json

d = json.load(open('data/2026-06-12/scripts_aligned/hot_daily.json', 'r', encoding='utf-8'))
voice = d['tracks']['voice']
visual = d['tracks']['visual']
pa = [v for v in visual if v.get('play_audio')]

print("=== voice items (first 8) ===")
for i, v in enumerate(voice[:8]):
    s = v['start_ms']
    e = s + v['duration_ms']
    print(f"  v[{i}]: {s}-{e}ms ({v['duration_ms']}ms)")

print("\n=== play_audio segments ===")
for p in pa:
    s = p['start_ms']
    e = s + p['duration_ms']
    print(f"  pa: {s}-{e}ms ({p['duration_ms']}ms)")

print("\n=== overlap check ===")
overlap_count = 0
for p in pa:
    ps = p['start_ms']
    pe = ps + p['duration_ms']
    for i, v in enumerate(voice):
        vs = v['start_ms']
        ve = vs + v['duration_ms']
        if vs < pe and ve > ps:
            print(f"  OVERLAP: voice[{i}] {vs}-{ve} vs PA {ps}-{pe}")
            overlap_count += 1

if overlap_count == 0:
    print("  ✅ No overlaps!")
else:
    print(f"\n  ❌ {overlap_count} overlaps found")
