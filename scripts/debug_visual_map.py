import json

s = json.load(open(r'D:\workspace\videoFactory\data\2026-06-16\scripts_aligned\hot_daily.json', 'r', encoding='utf-8'))

print("=== VIDEO CLIPS ===")
vis = [v for v in s['tracks']['visual'] if v.get('type') == 'video_clip']
for v in vis:
    start = v['start_ms'] / 1000
    dur = v['duration_ms'] / 1000
    tr = v.get('time_range', [])
    audio = v.get('play_audio', False)
    print(f"  start={start:.1f}s dur={dur:.1f}s time_range={tr} play_audio={audio}")

print()
print("=== VOICE around first video (0-20s) ===")
voice = s['tracks']['voice']
for v in voice[:6]:
    start = v['start_ms'] / 1000
    dur = v.get('duration_ms', 0) / 1000
    text = v.get('text', '')[:40]
    print(f"  {start:.1f}s - {start+dur:.1f}s: {text}")

print()
print(f"Total duration: {s['total_duration_ms']/1000:.1f}s")
print(f"Total video clips: {len(vis)}")
