"""
Douyin video downloader - via mobile share API (iesdouyin)
This bypasses the web anti-bot by using the mobile sharing endpoint.
"""
import requests
import re
import sys
import json
from pathlib import Path

def extract_video_id(url: str) -> str:
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    # handle short links
    r = requests.head(url, allow_redirects=True, timeout=10,
                     headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)"})
    m = re.search(r'/video/(\d+)', r.url)
    return m.group(1) if m else None

def get_video_url(video_id: str) -> dict:
    """Try multiple API endpoints to get video download URL"""

    # Method 1: iesdouyin share endpoint (mobile)
    endpoints = [
        f"https://www.iesdouyin.com/share/video/{video_id}/",
        f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}",
    ]

    headers_mobile = {
        "User-Agent": "com.ss.android.ugc.aweme/250801 (Linux; U; Android 12; Pixel 6)",
        "Accept": "application/json",
    }

    headers_web = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.douyin.com/",
    }

    # Try iteminfo API
    url = endpoints[1]
    print(f"[1] Trying iteminfo API: {url}")
    try:
        r = requests.get(url, headers=headers_mobile, timeout=15)
        print(f"    Status: {r.status_code}, Len: {len(r.text)}")
        if r.status_code == 200 and r.text.strip():
            data = r.json()
            items = data.get("item_list", [])
            if items:
                video = items[0].get("video", {})
                play_addr = video.get("play_addr", {})
                url_list = play_addr.get("url_list", [])
                if url_list:
                    # Replace watermark URL with no-watermark
                    dl_url = url_list[0].replace("playwm", "play")
                    return {"url": dl_url, "id": video_id}
                print(f"    No play_addr in response")
            else:
                print(f"    Empty item_list: {r.text[:300]}")
    except Exception as e:
        print(f"    Error: {e}")

    # Method 2: Try SSA endpoint
    ssa_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}"
    print(f"[2] Trying SSA: {ssa_url}")
    try:
        r = requests.get(ssa_url, headers=headers_web, timeout=15)
        print(f"    Status: {r.status_code}, Len: {len(r.text)}")
        if r.status_code == 200 and len(r.text) > 10:
            data = r.json()
            detail = data.get("aweme_detail", {})
            video = detail.get("video", {})
            play_addr = video.get("play_addr", {})
            url_list = play_addr.get("url_list", [])
            if url_list:
                return {"url": url_list[0], "id": video_id}
    except Exception as e:
        print(f"    Error: {e}")

    # Method 3: TikWM third-party API (public, no auth needed)
    tikwm_url = f"https://www.tikwm.com/api/?url=https://www.douyin.com/video/{video_id}"
    print(f"[3] Trying TikWM: {tikwm_url}")
    try:
        r = requests.get(tikwm_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        print(f"    Status: {r.status_code}, Len: {len(r.text)}")
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 0 and data.get("data"):
                play = data["data"].get("play")
                if play:
                    return {"url": play, "id": video_id}
                hdplay = data["data"].get("hdplay")
                if hdplay:
                    return {"url": hdplay, "id": video_id}
            print(f"    Response: {r.text[:300]}")
    except Exception as e:
        print(f"    Error: {e}")

    return None

def download(info: dict, output: Path) -> bool:
    url = info["url"]
    print(f"[dl] Downloading: {url[:120]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)",
        "Referer": "https://www.douyin.com/",
    }
    r = requests.get(url, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    mb = output.stat().st_size / 1024 / 1024
    print(f"[ok] Saved: {output} ({mb:.1f}MB)")
    return True

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/video/7654485758779690278"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("d:/workspace/videoFactory/data/2026-06-24/media/test_dy.mp4")

    vid = extract_video_id(url)
    print(f"Video ID: {vid}")

    info = get_video_url(vid)
    if info:
        download(info, out)
    else:
        print("[FAIL] Could not get video URL from any endpoint")
        sys.exit(1)
