"""下载剩余抖音视频 + 转录"""
import json
from pathlib import Path

collected = Path("data/2026-06-12/collected")
manifest_path = Path("data/2026-06-12/media/manifest.json")
manifest = json.load(open(manifest_path, "r", encoding="utf-8"))

douyin_files = sorted(collected.glob("*douyin*"))
need_download = []

for f in douyin_files:
    raw = f.read_text("utf-8")
    if raw.startswith('"'):
        raw = json.loads(raw)
    data = json.loads(raw) if isinstance(raw, str) else raw
    url = data.get("url", "")
    
    # 检查 manifest 里有没有 video
    entry = manifest.get(f.name, {})
    video = entry.get("video")
    has_video = False
    if isinstance(video, dict) and video.get("path"):
        has_video = Path(video["path"]).exists()
    elif isinstance(video, str) and video:
        has_video = Path(video).exists()
    
    if url and "douyin.com/video" in url and not has_video:
        need_download.append((f.name, f.stem, url))

print(f"需要下载: {len(need_download)} 个抖音视频")
for name, stem, url in need_download:
    print(f"  {stem[:60]} -> {url}")
