"""
Connect to Chrome via CDP and extract video URL from Douyin page.
Chrome must be running with --remote-debugging-port=9222
"""
import requests
import json
import websocket
import sys
import time
from pathlib import Path

CDP_HOST = "http://localhost:9222"

def get_ws_url():
    """Get WebSocket debugger URL from Chrome CDP"""
    r = requests.get(f"{CDP_HOST}/json", timeout=5)
    tabs = r.json()
    for tab in tabs:
        if "douyin.com/video" in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]
    # fallback: first tab
    if tabs:
        return tabs[0]["webSocketDebuggerUrl"]
    return None

def send_cdp(ws, method, params=None, msg_id=1):
    """Send CDP command and get response"""
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp
        # Skip events
        if "method" in resp:
            continue

def extract_video_url_from_page(ws):
    """Try multiple approaches to get video URL"""
    
    # Method 1: Get video element src
    resp = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            var videos = document.querySelectorAll('video');
            var srcs = [];
            for (var i = 0; i < videos.length; i++) {
                var v = videos[i];
                if (v.src) srcs.push(v.src);
                if (v.currentSrc) srcs.push(v.currentSrc);
                // Check source elements
                var sources = v.querySelectorAll('source');
                for (var j = 0; j < sources.length; j++) {
                    if (sources[j].src) srcs.push(sources[j].src);
                }
            }
            return JSON.stringify(srcs);
        })()
        """,
        "returnByValue": True
    }, msg_id=10)
    
    result = resp.get("result", {}).get("result", {}).get("value", "[]")
    srcs = json.loads(result) if result else []
    print(f"[1] Video element srcs: {srcs}")
    
    # Method 2: Check performance entries for video CDN
    resp = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            var entries = performance.getEntriesByType('resource');
            var videos = entries.filter(function(e) {
                return e.name.indexOf('douyinvod') > -1 || 
                       e.name.indexOf('bytecdn') > -1 || 
                       e.name.indexOf('byteicdn') > -1 ||
                       e.name.indexOf('ixigua') > -1 ||
                       (e.name.indexOf('.mp4') > -1 && e.name.indexOf('douyin') > -1);
            });
            return JSON.stringify(videos.map(function(e) { return e.name; }));
        })()
        """,
        "returnByValue": True
    }, msg_id=20)
    
    result = resp.get("result", {}).get("result", {}).get("value", "[]")
    cdn_urls = json.loads(result) if result else []
    print(f"[2] CDN entries ({len(cdn_urls)}): {cdn_urls[:3]}")
    
    # Method 3: Extract from page source / RENDER_DATA
    resp = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            // Try RENDER_DATA
            var el = document.getElementById('RENDER_DATA');
            if (el) {
                try {
                    var data = decodeURIComponent(el.textContent);
                    var playIdx = data.indexOf('play_addr');
                    if (playIdx > -1) {
                        var snippet = data.substring(playIdx, playIdx + 2000);
                        var urlMatch = snippet.match(/https?:\\/\\/[^"'\\s]+douyinvod[^"'\\s]+/);
                        if (urlMatch) return urlMatch[0];
                        urlMatch = snippet.match(/https?:\\/\\/[^"'\\s]+bytecdn[^"'\\s]+/);
                        if (urlMatch) return urlMatch[0];
                    }
                } catch(e) {}
            }
            // Try _ROUTER_DATA
            if (window._ROUTER_DATA) {
                var rd = JSON.stringify(window._ROUTER_DATA);
                var m = rd.match(/https?:\\/\\/[^"'\\s]*(?:douyinvod|bytecdn|byteicdn)[^"'\\s]*/);
                if (m) return m[0];
            }
            return 'NOT_FOUND';
        })()
        """,
        "returnByValue": True
    }, msg_id=30)
    
    render_url = resp.get("result", {}).get("result", {}).get("value", "NOT_FOUND")
    print(f"[3] RENDER_DATA url: {render_url[:150] if render_url else 'None'}")
    
    # Return first valid URL found
    for url in cdn_urls:
        if 'douyinvod' in url or 'bytecdn' in url:
            return url
    if render_url and render_url != 'NOT_FOUND':
        return render_url
    for src in srcs:
        if src and not src.startswith('blob:'):
            return src
    
    return None

def download_video(url, output_path):
    """Download video from URL"""
    print(f"[dl] Downloading: {url[:120]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
    }
    r = requests.get(url, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    mb = output_path.stat().st_size / 1024 / 1024
    print(f"[ok] Saved: {output_path} ({mb:.1f}MB)")
    return True

if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("d:/workspace/videoFactory/data/2026-06-24/media/test_dy_cdp.mp4")
    
    print(f"Connecting to Chrome CDP at {CDP_HOST}...")
    ws_url = get_ws_url()
    if not ws_url:
        print("ERROR: No Chrome tab found. Launch Chrome with --remote-debugging-port=9222")
        sys.exit(1)
    
    print(f"Found tab, connecting: {ws_url[:80]}")
    ws = websocket.create_connection(ws_url, timeout=10)
    
    url = extract_video_url_from_page(ws)
    ws.close()
    
    if url:
        print(f"\nVideo URL found: {url[:150]}")
        download_video(url, output)
    else:
        print("\nFAILED: Could not extract video URL from page")
        sys.exit(1)
