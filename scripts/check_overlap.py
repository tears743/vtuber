import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open('data/2026-06-12/scripts_aligned/hot_daily.json', encoding='utf-8'))

visual = d['tracks']['visual']
clips = [v for v in visual if v.get('type') == 'video_clip']

print(f"=== hot_daily video_clips: {len(clips)} ===\n")
for i, c in enumerate(clips):
    source = c.get('source', '')
    exists = os.path.exists(source)
    print(f"  [{i}] {c['start_ms']}ms dur={c['duration_ms']}ms")
    print(f"       source: {source}")
    print(f"       exists: {exists}")
    if exists:
        size = os.path.getsize(source)
        print(f"       size: {size/1024:.0f}KB")
    print()
