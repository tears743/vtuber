"""增强 visual renderer 的错误输出，完整记录 stderr"""
import json
import subprocess
from pathlib import Path

script_path = Path(r"D:\workspace\videoFactory\data\2026-06-16\scripts_aligned\hot_daily.json")
data = json.loads(script_path.read_text(encoding="utf-8"))

visual = sorted(data["tracks"]["visual"], key=lambda v: v["start_ms"])

# 找所有 video_clip 类型
for i, v in enumerate(visual):
    if v.get("type") != "video_clip":
        continue
    
    source = v["source"]
    pa = v.get("play_audio", False)
    duration_ms = v["duration_ms"]
    duration_s = duration_ms / 1000.0
    time_range = v.get("time_range", [0, duration_s])
    start_s = time_range[0] if isinstance(time_range, list) and len(time_range) > 0 else 0
    
    if isinstance(time_range, list) and len(time_range) >= 2:
        range_dur = time_range[1] - time_range[0]
        duration_s = min(duration_s, range_dur)
    
    fade_out_start = max(0, duration_s - 0.5)
    
    # 只测 dur <= 20s 的短片段（非PA预览）
    if pa or duration_s > 20:
        print(f"[{i:2d}] SKIP PA={pa} dur={duration_s:.0f}s {Path(source).parent.name}")
        continue
    
    output_path = Path(f"D:/workspace/videoFactory/data/2026-06-16/visual/.test_seg_{i:02d}.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_s),
        "-i", str(source),
        "-t", str(duration_s),
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"fade=t=in:st=0:d=0.3,"
            f"fade=t=out:st={fade_out_start}:d=0.5,"
            "format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-an",
        str(output_path),
    ]
    
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=60, encoding="utf-8", errors="replace",
    )
    
    status = "OK" if result.returncode == 0 else "FAIL"
    print(f"[{i:2d}] {status} dur={duration_s:.0f}s {Path(source).parent.name}")
    if result.returncode != 0:
        # 打印 stderr 最后 300 字符
        print(f"     stderr: ...{result.stderr[-300:]}")
