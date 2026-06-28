"""
Douyin Video Downloader via KuKuTool.com + opencli browser

Flow:
1. Open kukutool.com
2. Close ad popup if present
3. Input douyin video URL
4. Click "开始解析"
5. Wait for results
6. Click "复制链接" (1080p)
7. Read clipboard to get direct video URL
8. Download via requests

Usage:
    python kukutool_downloader.py <douyin_url> <output_path>
"""
import subprocess
import time
import sys
import json
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_NAME = "kuku_dl"


def run_browser_cmd(args: str, timeout: int = 30) -> dict:
    """Execute opencli browser command and return parsed result"""
    cmd = f"opencli browser {SESSION_NAME} {args}"
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace"
        )
        output = proc.stdout.strip()
        # Try parse JSON
        try:
            # Find JSON in output (may have update notices after)
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("{") or line.startswith("["):
                    return json.loads(line)
            # Try full output
            return json.loads(output.split("\n\n")[0])
        except (json.JSONDecodeError, IndexError):
            return {"raw": output, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}


def get_clipboard() -> str:
    """Read Windows clipboard"""
    proc = subprocess.run(
        ["powershell", "-Command", "Get-Clipboard"],
        capture_output=True, text=True, timeout=5,
        encoding="utf-8", errors="replace"
    )
    return proc.stdout.strip()


def close_ad_popup() -> bool:
    """Check page state and close ad popup if present"""
    result = run_browser_cmd("state", timeout=20)
    raw = result.get("raw", "")
    
    # Look for the ad dialog close button
    # Pattern: [N]<button tabindex=0 aria-label=关闭 />
    if "aria-label=关闭" in raw or "解锁3小时" in raw:
        # Find the close button index
        for line in raw.split("\n"):
            if "aria-label=关闭" in line:
                # Extract [N] index
                import re
                m = re.search(r'\[(\d+)\]', line)
                if m:
                    idx = m.group(1)
                    run_browser_cmd(f"click {idx}", timeout=10)
                    time.sleep(1)
                    return True
    return False


def find_element_index(state_output: str, pattern: str) -> str | None:
    """Find element index by text pattern in state output"""
    import re
    for line in state_output.split("\n"):
        if pattern in line:
            m = re.search(r'\[(\d+)\]', line)
            if m:
                return m.group(1)
    return None


def download_douyin_via_kukutool(douyin_url: str, output_path: Path, quality: str = "1080p") -> bool:
    """
    Download douyin video via kukutool.com
    
    Args:
        douyin_url: Douyin video URL (https://www.douyin.com/video/XXXXX)
        output_path: Local path to save the video
        quality: Video quality (540p, 720p, 1080p, 超高清)
    
    Returns:
        True if download successful
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if output_path.exists() and output_path.stat().st_size > 10000:
        logger.info(f"[kukutool] Already exists: {output_path}")
        return True
    
    logger.info(f"[kukutool] Downloading: {douyin_url}")
    
    # Step 1: Open kukutool
    logger.info("[kukutool] Opening kukutool.com...")
    result = run_browser_cmd('open "https://dy.kukutool.com/"', timeout=30)
    if "error" in result:
        logger.error(f"[kukutool] Failed to open: {result}")
        return False
    
    time.sleep(3)
    
    # Step 2: Close ad popup if present
    close_ad_popup()
    
    # Step 3: Get current state to find input box
    state = run_browser_cmd("state", timeout=20)
    state_raw = state.get("raw", "")
    
    # Find input element
    input_idx = find_element_index(state_raw, "input type=text")
    if not input_idx:
        input_idx = find_element_index(state_raw, "placeholder=粘贴")
        if not input_idx:
            logger.error("[kukutool] Cannot find input box")
            run_browser_cmd("close", timeout=5)
            return False
    
    # Step 4: Clear existing content and type new URL
    clear_idx = find_element_index(state_raw, "清除内容")
    if clear_idx:
        run_browser_cmd(f"click {clear_idx}", timeout=5)
        time.sleep(0.5)
    
    result = run_browser_cmd(f'type {input_idx} "{douyin_url}"', timeout=15)
    if not result.get("typed"):
        logger.error(f"[kukutool] Failed to type URL: {result}")
        run_browser_cmd("close", timeout=5)
        return False
    
    # Step 5: Click "开始解析"
    parse_idx = find_element_index(state_raw, "开始解析")
    if not parse_idx:
        logger.error("[kukutool] Cannot find parse button")
        run_browser_cmd("close", timeout=5)
        return False
    
    run_browser_cmd(f"click {parse_idx}", timeout=15)
    
    # Step 6: Wait for results (poll state until video options appear)
    logger.info("[kukutool] Waiting for parse results...")
    video_url = None
    
    for attempt in range(6):
        time.sleep(5)
        
        # Close ad popup if it appears
        close_ad_popup()
        
        state = run_browser_cmd("state", timeout=20)
        state_raw = state.get("raw", "")
        
        # Check if results are ready (look for quality buttons)
        if quality in state_raw:
            logger.info(f"[kukutool] Results ready, looking for {quality} copy button...")
            
            # Find the copy button next to the desired quality
            # The copy button is right after the download button for each quality
            lines = state_raw.split("\n")
            found_quality = False
            for line in lines:
                if quality in line and "下载" not in line:
                    found_quality = True
                if found_quality and "复制链接" in line:
                    import re
                    m = re.search(r'\[(\d+)\]', line)
                    if m:
                        copy_idx = m.group(1)
                        # Click copy
                        run_browser_cmd(f"click {copy_idx}", timeout=10)
                        time.sleep(1)
                        
                        # Close ad popup if triggered
                        close_ad_popup()
                        time.sleep(1)
                        
                        # Read clipboard
                        video_url = get_clipboard()
                        if video_url and video_url.startswith("http") and "douyin" not in video_url:
                            break
                        # If clipboard has douyin url, the copy didn't work (ad blocked it)
                        # Try clicking again
                        close_ad_popup()
                        time.sleep(1)
                        run_browser_cmd(f"click {copy_idx}", timeout=10)
                        time.sleep(1)
                        video_url = get_clipboard()
                        break
                    break
            
            if video_url and video_url.startswith("http"):
                break
    
    # Cleanup browser session
    run_browser_cmd("close", timeout=5)
    
    if not video_url or not video_url.startswith("http"):
        logger.error(f"[kukutool] Failed to get video URL. Clipboard: {video_url[:100] if video_url else 'empty'}")
        return False
    
    # Step 7: Download the video
    logger.info(f"[kukutool] Downloading video ({quality})...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
        }
        r = requests.get(video_url, headers=headers, stream=True, timeout=120)
        r.raise_for_status()
        
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        
        size_mb = output_path.stat().st_size / (1024 * 1024)
        if size_mb < 0.1:
            logger.error(f"[kukutool] Download too small: {size_mb:.2f}MB")
            output_path.unlink(missing_ok=True)
            return False
        
        logger.info(f"[kukutool] Success: {output_path} ({size_mb:.1f}MB)")
        return True
        
    except Exception as e:
        logger.error(f"[kukutool] Download failed: {e}")
        output_path.unlink(missing_ok=True)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/video/7654485758779690278"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("d:/workspace/videoFactory/data/2026-06-24/media/kukutool_test/video.mp4")
    
    success = download_douyin_via_kukutool(url, out)
    sys.exit(0 if success else 1)
