"""提取抖音视频直链 - 通过 browser 工具从页面数据中获取"""
import subprocess
import sys
import json
import re

def extract_douyin_video_url(page_url: str, session: str = "dy_dl") -> str | None:
    """打开抖音视频页，从 RENDER_DATA 中提取视频直链"""
    
    # 打开页面
    subprocess.run(
        ["browser", "--session", session, "open", page_url],
        capture_output=True, text=True, timeout=30,
    )
    
    import time
    time.sleep(5)
    
    # 获取 RENDER_DATA（抖音把视频信息放在这里）
    js = """
    (function(){
        var el = document.querySelector('#RENDER_DATA');
        if (!el) return 'NO_RENDER_DATA';
        var raw = decodeURIComponent(el.textContent);
        var matches = raw.match(/https?:[^"]*\\.mp4[^"]*/g);
        if (matches && matches.length > 0) return matches[0];
        // fallback: 找 playAddr
        var m2 = raw.match(/"playAddr"[^[]*"urlList":\\s*\\[\\s*"([^"]+)"/);
        if (m2) return m2[1];
        return 'NO_VIDEO_URL_FOUND';
    })()
    """
    
    result = subprocess.run(
        ["browser", "--session", session, "eval", js],
        capture_output=True, text=True, timeout=15,
    )
    
    output = result.stdout.strip()
    # 解析 result: <url>
    if "result:" in output:
        url = output.split("result:", 1)[1].strip()
        if url.startswith("http"):
            return url
    
    # 尝试获取 cookies 后用 yt-dlp
    result2 = subprocess.run(
        ["browser", "--session", session, "cookies", "get"],
        capture_output=True, text=True, timeout=10,
    )
    
    # 关闭
    subprocess.run(
        ["browser", "--session", session, "close"],
        capture_output=True, text=True, timeout=5,
    )
    
    return None


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/video/7654485758779690278"
    print(f"[extract] URL: {url}")
    video_url = extract_douyin_video_url(url)
    if video_url:
        print(f"[extract] Video direct URL: {video_url[:120]}...")
    else:
        print("[extract] Failed to extract video URL")
