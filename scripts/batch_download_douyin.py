"""批量下载剩余抖音视频并转录"""
import json
import subprocess
import time
from pathlib import Path

collected = Path("data/2026-06-12/collected")
media_dir = Path("data/2026-06-12/media")
manifest_path = media_dir / "manifest.json"
manifest = json.load(open(manifest_path, "r", encoding="utf-8"))

douyin_files = sorted(collected.glob("*douyin*"))
need_download = []

for f in douyin_files:
    raw = f.read_text("utf-8")
    if raw.startswith('"'):
        raw = json.loads(raw)
    data = json.loads(raw) if isinstance(raw, str) else raw
    url = data.get("url", "")
    
    entry = manifest.get(f.name, {})
    video = entry.get("video")
    has_video = False
    if isinstance(video, dict) and video.get("path"):
        has_video = Path(video["path"]).exists()
    elif isinstance(video, str) and video:
        has_video = Path(video).exists()
    
    if url and "douyin.com/video" in url and not has_video:
        need_download.append((f.name, f.stem, url))

print(f"=== 需要下载: {len(need_download)} 个抖音视频 ===\n")

success = 0
failed = 0

for i, (filename, stem, url) in enumerate(need_download, 1):
    item_dir = media_dir / stem
    item_dir.mkdir(parents=True, exist_ok=True)
    local_path = item_dir / "video.mp4"
    
    if local_path.exists():
        print(f"[{i}/{len(need_download)}] 已存在: {stem[:50]}")
        # 更新 manifest
        if filename not in manifest:
            manifest[filename] = {"images": [], "video": None}
        manifest[filename]["video"] = {"path": str(local_path)}
        success += 1
        continue
    
    print(f"[{i}/{len(need_download)}] 下载中: {stem[:50]}...")
    t0 = time.time()
    
    try:
        result = subprocess.run(
            ["yt-dlp", "-o", str(local_path), "--no-playlist", url],
            capture_output=True, text=True, timeout=120,
        )
        
        if result.returncode == 0 and local_path.exists():
            size_mb = local_path.stat().st_size / (1024 * 1024)
            elapsed = time.time() - t0
            print(f"  OK {size_mb:.1f}MB, {elapsed:.1f}s")
            
            # 更新 manifest
            if filename not in manifest:
                manifest[filename] = {"images": [], "video": None}
            manifest[filename]["video"] = {"path": str(local_path)}
            success += 1
        else:
            print(f"  FAIL 失败: {result.stderr[:100]}")
            failed += 1
            
    except subprocess.TimeoutExpired:
        print(f"  FAIL 超时")
        failed += 1
    except Exception as e:
        print(f"  FAIL 异常: {e}")
        failed += 1

# 保存 manifest
json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"\n=== 下载完成: {success} 成功, {failed} 失败 ===")
