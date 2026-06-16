"""直接跑 hot_daily compose 并捕获完整错误"""
import json, logging, sys
from pathlib import Path
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

sys.path.insert(0, '.')
from agents.renderer.run_render import _compose_studio, _merge_audio_segments

data_root = Path('data/2026-06-12')
script_path = data_root / 'scripts_aligned' / 'hot_daily.json'
with open(script_path, 'r', encoding='utf-8') as f:
    script = json.load(f)

script_id = script['id']
tracks = script['tracks']
visual_items = tracks.get('visual', [])

media_segments = []
for vis in visual_items:
    vtype = vis.get('type', '')
    if vtype in ('image', 'video_clip'):
        start_ms = vis.get('start_ms', 0)
        dur_ms = vis.get('duration_ms', 5000)
        source = vis.get('source', '')
        if source and Path(source).exists():
            media_segments.append({
                'start_s': start_ms / 1000.0,
                'end_s': (start_ms + dur_ms) / 1000.0,
                'type': vtype,
                'source': source,
                'play_audio': vis.get('play_audio', False),
                'time_range': vis.get('time_range', []),
            })

print(f"media_segments: {len(media_segments)}")

project_root = Path('.')
studio_bg = project_root / "assets" / "studio" / "bg_starry.png"
studio_desk = project_root / "assets" / "studio" / "desk_foreground.png"
live2d_webm = data_root / "live2d" / f"{script_id}_live2d.webm"
overlay_webm = data_root / "overlay" / f"{script_id}_overlay.webm"
output_dir = data_root / "final"
output_dir.mkdir(parents=True, exist_ok=True)
output_mp4 = output_dir / f"{script_id}.mp4"
output_mp4.unlink(missing_ok=True)

# merge audio
audio_seg_dir = data_root / "audio" / script_id
merged_audio = _merge_audio_segments(audio_seg_dir, script, output_dir / f"{script_id}_audio.wav")

total_ms = script.get('total_duration_ms', 30000)
duration_s = total_ms / 1000.0

result = _compose_studio(
    studio_bg=studio_bg,
    studio_desk=studio_desk,
    live2d_webm=live2d_webm,
    overlay_webm=overlay_webm,
    merged_audio=merged_audio,
    media_segments=media_segments,
    duration_s=duration_s,
    output_mp4=output_mp4,
    script_id=script_id,
)

print(f"Result: {result}")
