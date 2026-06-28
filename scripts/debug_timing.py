import json

d = json.load(open('data/2026-06-24/scripts_aligned/hot_daily.json', 'r', encoding='utf-8'))
tracks = d.get('tracks', {})
voice = tracks.get('voice', [])
live2d = tracks.get('live2d', [])

print("=== Live2D 动画段 voice 为空 且 > 2秒 ===")
for i, l in enumerate(live2d):
    if i < len(voice):
        v = voice[i]
        text = v.get('text', '').strip()
        if not text and l['duration_ms'] > 2000:
            action = l.get('action', '')
            s = l['start_ms']
            e = s + l['duration_ms']
            print(f"  L2D[{i}]: {s/1000:.1f}s - {e/1000:.1f}s ({l['duration_ms']}ms) action={action}")
            # 前后 voice
            if i > 0:
                pv = voice[i-1]
                pt = pv.get('text', '')[:40]
                pe = pv['start_ms'] + pv['duration_ms']
                print(f"    prev V[{i-1}]: ends {pe/1000:.1f}s '{pt}'")
            if i+1 < len(voice):
                nv = voice[i+1]
                nt = nv.get('text', '')[:40]
                print(f"    next V[{i+1}]: starts {nv['start_ms']/1000:.1f}s '{nt}'")
            print()
