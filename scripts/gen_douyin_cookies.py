"""生成抖音 cookies.txt (Netscape 格式) 供 yt-dlp 使用

用法: python scripts/gen_douyin_cookies.py
会通过 browser 工具打开抖音首页获取 fresh cookies，然后输出到 douyin_cookies.txt
"""
import subprocess
import json
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIES_FILE = PROJECT_ROOT / "douyin_cookies.txt"


def get_cookies_via_browser() -> list[dict]:
    """通过 browser 工具打开抖音获取 cookies"""
    # 打开抖音首页
    subprocess.run(
        ["browser", "--session", "dy_ck", "open", "https://www.douyin.com"],
        capture_output=True, text=True, timeout=30,
    )
    
    # 获取 cookies
    result = subprocess.run(
        ["browser", "--session", "dy_ck", "cookies", "get"],
        capture_output=True, text=True, timeout=10,
    )
    
    # 关闭 session
    subprocess.run(
        ["browser", "--session", "dy_ck", "close"],
        capture_output=True, text=True, timeout=5,
    )
    
    output = result.stdout.strip()
    # 输出格式: cookies: [{...}, ...]
    if "cookies:" in output:
        raw = output.split("cookies:", 1)[1].strip()
        try:
            return ast.literal_eval(raw)
        except Exception:
            return json.loads(raw)
    return []


def cookies_to_netscape(cookies: list[dict]) -> str:
    """转换为 Netscape cookies.txt 格式"""
    lines = ["# Netscape HTTP Cookie File", "# Generated for yt-dlp douyin downloads", ""]
    
    for c in cookies:
        domain = c.get("domain", "")
        if "douyin" not in domain:
            continue
        
        inc_sub = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", 0)))
        name = c.get("name", "")
        value = c.get("value", "")
        path = c.get("path", "/")
        
        lines.append(f"{domain}\t{inc_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
    
    return "\n".join(lines) + "\n"


def main():
    print("[cookies] 获取抖音 cookies...")
    cookies = get_cookies_via_browser()
    
    douyin_cookies = [c for c in cookies if "douyin" in c.get("domain", "")]
    if not douyin_cookies:
        print("[cookies] 未获取到抖音 cookies!", file=sys.stderr)
        sys.exit(1)
    
    content = cookies_to_netscape(cookies)
    COOKIES_FILE.write_text(content, encoding="utf-8")
    print(f"[cookies] 已生成: {COOKIES_FILE} ({len(douyin_cookies)} cookies)")


if __name__ == "__main__":
    main()
