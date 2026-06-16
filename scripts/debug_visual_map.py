import json
from pathlib import Path

s = json.load(open(r'D:\workspace\videoFactory\data\2026-06-16\scripts_aligned\hot_daily.json', 'r', encoding='utf-8'))
visual_items = s['tracks']['visual']

print("=== VISUAL TRACK: video_clip items (画面顺序) ===")
media_idx = 0
for vi_idx, vis in enumerate(visual_items):
    if vis.get('type') not in ('image', 'video_clip'):
        continue
    is_video = vis.get('type') == 'video_clip'
    src = vis.get('source', '')[-50:]
    play_audio = vis.get('play_audio', False)
    time_range = vis.get('time_range', [])
    start_s = vis['start_ms'] / 1000
    print(f"  media_idx={media_idx}, vi_idx={vi_idx}, start={start_s:.1f}s, type={vis['type']}")
    print(f"    source=...{src}")
    if is_video:
        print(f"    time_range={time_range}, play_audio={play_audio}")
    print()
    media_idx += 1

print()
print("=== AUDIO: play_audio 视频音频 (音频提取顺序) ===")
for vi_idx, vis in enumerate(visual_items):
    if vis.get('type') != 'video_clip':
        continue
    if not vis.get('play_audio', False):
        continue
    src = vis.get('source', '')[-50:]
    time_range = vis.get('time_range', [])
    start_ms = vis.get('start_ms', 0)
    print(f"  vi_idx={vi_idx}, start={start_ms/1000:.1f}s, time_range={time_range}")
    print(f"    source=...{src}")
    print(f"    audio_file=video_audio_{vi_idx:02d}.wav, placed at {start_ms}ms")
    print()
