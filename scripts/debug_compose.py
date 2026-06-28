"""Debug hot_daily compose issue"""
import json, sys, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO)
from config_loader import load_config

config = load_config()
data_root = Path(config.get("paths", {}).get("data_root", "data"))
today = "2026-06-24"

script_path = data_root / today / "scripts_aligned" / "hot_daily.json"
with open(script_path, "r", encoding="utf-8") as f:
    script = json.load(f)

total_ms = script.get("total_duration_ms", 30000)
duration_s = total_ms / 1000.0

tracks = script.get("tracks", {})
visual_items = tracks.get("visual", [])
media_segments = []
for vis in visual_items:
    vtype = vis.get("type", "")
    if vtype in ("image", "video_clip"):
        start_ms = vis.get("start_ms", 0)
        dur_ms = vis.get("duration_ms", 5000)
        source = vis.get("source", "")
        if source and Path(source).exists():
            media_segments.append({
                "start_s": start_ms / 1000.0,
                "end_s": (start_ms + dur_ms) / 1000.0,
                "type": vtype,
                "source": source,
                "play_audio": vis.get("play_audio", False),
                "time_range": vis.get("time_range", []),
                "author": vis.get("author", ""),
            })

print(f"media_segments: {len(media_segments)}, duration: {duration_s}s")

# Check video_clip with time_range
for i, seg in enumerate(media_segments):
    if seg["type"] == "video_clip":
        tr = seg.get("time_range", [])
        dur = seg["end_s"] - seg["start_s"]
        src_short = seg["source"][-50:]
        print(f"  video[{i}]: tr={tr}, dur={dur:.1f}s, src=...{src_short}")

# Now build the actual ffmpeg command and dump it
project_root = Path(__file__).parent.parent
studio_bg = project_root / "assets" / "studio" / "bg_starry.png"
studio_desk = project_root / "assets" / "studio" / "desk_foreground.png"
live2d_webm = data_root / today / "live2d" / "hot_daily_live2d.webm"
overlay_webm = data_root / today / "overlay" / "hot_daily_overlay.webm"
merged_audio = data_root / today / "final" / "hot_daily_audio.wav"
meteor_fx_path = project_root / "assets" / "studio" / "meteor_fx.webm"

FADE_DURATION = 0.5
cmd = ["ffmpeg", "-y"]
input_idx = 0

# bg
cmd.extend(["-loop", "1", "-i", str(studio_bg)])
bg_idx = input_idx; input_idx += 1

# meteor
has_meteor = meteor_fx_path.exists()
if has_meteor:
    cmd.extend(["-stream_loop", "-1", "-vcodec", "libvpx-vp9", "-i", str(meteor_fx_path)])
    meteor_idx = input_idx; input_idx += 1

# live2d
cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(live2d_webm)])
l2d_idx = input_idx; input_idx += 1

# desk
cmd.extend(["-loop", "1", "-i", str(studio_desk)])
desk_idx = input_idx; input_idx += 1

# overlay
cmd.extend(["-vcodec", "libvpx-vp9", "-i", str(overlay_webm)])
ov_idx = input_idx; input_idx += 1

# media inputs
media_input_map = []
for seg in media_segments:
    if seg["type"] == "video_clip":
        time_range = seg.get("time_range", [])
        if time_range and len(time_range) >= 1:
            cmd.extend(["-ss", str(time_range[0])])
        cmd.extend(["-i", seg["source"]])
    else:
        cmd.extend(["-loop", "1", "-i", seg["source"]])
    media_input_map.append({
        "input_idx": input_idx,
        "start_s": seg["start_s"],
        "end_s": seg["end_s"],
        "type": seg["type"],
        "play_audio": seg.get("play_audio", False),
        "author": seg.get("author", ""),
    })
    input_idx += 1

# audio
cmd.extend(["-i", str(merged_audio)])
audio_idx = input_idx; input_idx += 1

print(f"\nTotal inputs: {input_idx}")
print(f"Command args count: {len(cmd)}")

# Build filter_complex
fp = []
fp.append(f"[{bg_idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[studio_bg]")

if has_meteor:
    fp.append(f"[{meteor_idx}:v]scale=1080:1920,format=yuva420p[meteor]")
    fp.append("[studio_bg][meteor]overlay=0:0:shortest=1[studio_bg_fx]")
    bg_label = "studio_bg_fx"
else:
    bg_label = "studio_bg"

# live2d
fp.append(f"[{l2d_idx}:v]split=2[l2d_raw_big][l2d_raw_small]")
fp.append("[l2d_raw_big]scale=864:1536[l2d_big]")
fp.append("[l2d_raw_small]scale=540:960[l2d_small]")
fp.append(f"[{bg_label}][l2d_big]overlay=108:100:shortest=1[with_char]")

# desk
fp.append(f"[{desk_idx}:v]scale=1080:580[desk]")
fp.append("[with_char][desk]overlay=0:1340:shortest=1[studio_full]")

# UI
fp.append(
    "[studio_full]"
    "drawbox=x=0:y=0:w=1080:h=80:color=black@0.6:t=fill,"
    "drawtext=text='Mili Channel':fontsize=32:fontcolor=white:x=20:y=25,"
    f"drawtext=text='{today}':fontsize=28:fontcolor=white@0.8:x=900:y=28,"
    "drawbox=x=0:y=1840:w=1080:h=80:color=black@0.75:t=fill,"
    "drawtext=text='LIVE':fontsize=36:fontcolor=white:x=15:y=1860:"
    "box=1:boxcolor=red:boxborderw=6,"
    "drawtext=text='AI Daily | Hot News | Tech Updates':"
    "fontsize=28:fontcolor=white:x='1080-mod(t*200\\,2400)':y=1862[studio_ui]"
)

cur = "studio_ui"

# media overlays
for i, mseg in enumerate(media_input_map):
    mi = mseg["input_idx"]
    start = mseg["start_s"]
    end = mseg["end_s"]
    dur = end - start
    author = mseg.get("author", "")
    
    fade_in_d = min(FADE_DURATION, dur / 2)
    fade_out_st = max(0, dur - FADE_DURATION)
    
    media_filter = (
        f"[{mi}:v]scale=1080:1760:force_original_aspect_ratio=decrease,setsar=1,"
        f"pad=1080:1760:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setpts=PTS-STARTPTS,trim=duration={dur},setpts=PTS-STARTPTS,"
        f"fade=t=in:st=0:d={fade_in_d},"
        f"fade=t=out:st={fade_out_st}:d={FADE_DURATION}"
    )
    
    if author:
        author_text = author if author.startswith("@") else f"@{author}"
        author_escaped = author_text.replace("'", "\\'").replace(":", "\\:")
        media_filter += (
            f",drawbox=x=20:y=ih-70:w=text_w+30:h=50:color=black@0.5:t=fill,"
            f"drawtext=text='{author_escaped}':fontsize=28:fontcolor=white@0.9:"
            f"x=35:y=ih-60"
        )
    
    media_filter += f",setpts=PTS+{start}/TB[media_{i}]"
    fp.append(media_filter)
    
    nxt = f"v_m{i}"
    fp.append(f"[{cur}][media_{i}]overlay=0:80:eof_action=pass:shortest=0[{nxt}]")
    cur = nxt

# small live2d
delay = FADE_DURATION
parts = [
    f"between(t,{m['start_s']+delay},{m['end_s']-delay})"
    for m in media_input_map
    if m['end_s'] - m['start_s'] > delay * 3
]
if parts:
    enable_expr = "+".join(parts)
    nxt = "v_small"
    fp.append(f"[{cur}][l2d_small]overlay=510:880:enable='gte({enable_expr},1)':eof_action=pass[{nxt}]")
    cur = nxt

# overlay
fp.append(f"[{ov_idx}:v]scale=1080:1920[ov]")
nxt = "v_final"
fp.append(f"[{cur}][ov]overlay=0:0:shortest=1[{nxt}]")
cur = nxt

fp.append(f"[{cur}]format=yuv420p[vout]")

# audio
afp = [f"[{audio_idx}:a]volume=1.0[aout]"]

filter_complex = ";".join(fp + afp)
print(f"\nFilter complex length: {len(filter_complex)} chars")
print(f"Filter parts count: {len(fp) + len(afp)}")

# Write filter to file for inspection
with open("data/2026-06-24/final/hot_daily_filter.txt", "w", encoding="utf-8") as f:
    f.write(filter_complex)
print("\nFilter written to data/2026-06-24/final/hot_daily_filter.txt")

# Check command line total length
cmd.extend(["-filter_complex", filter_complex])
cmd.extend(["-map", "[vout]", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k"])
cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-t", str(duration_s), "data/2026-06-24/final/hot_daily.mp4"])

total_cmd_len = sum(len(a) for a in cmd)
print(f"Total command length: {total_cmd_len} chars")
print(f"Total args: {len(cmd)}")
