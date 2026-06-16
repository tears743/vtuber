"""
技术验证 v10: 三层合成 (使用项目本地素材)
底层: 纯背景（无演播台）
中层: Live2D 角色（居中半身）
顶层: 演播台裁片（带顶部alpha渐变，柔和遮挡角色下半身）+ Ticker
"""
import subprocess
from pathlib import Path

PROJECT_DIR = Path(r"D:\workspace\videoFactory")
ASSETS_DIR = PROJECT_DIR / "assets" / "studio"
DATA_DIR = PROJECT_DIR / "data" / "2026-06-12"

BG_IMAGE = ASSETS_DIR / "bg_starry.png"          # 纯背景无演播台
DESK_FG = ASSETS_DIR / "desk_foreground.png"      # 演播台前景 (带alpha渐变)
LIVE2D_WEBM = DATA_DIR / "live2d" / "ai_daily_live2d.webm"
OUTPUT = DATA_DIR / "final" / "test_studio_compose.mp4"

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
DURATION = "10"

# 三层合成:
# [0] = 纯背景 (loop) → 全屏铺满
# [1] = Live2D WebM (VP9 alpha) → 居中半身
# [2] = 演播台前景 (带alpha渐变, loop) → 遮挡角色下半身
#
# 演播台 580px 高, 放在 y=1340 (1920-580=1340)
# 角色 864x1536, 居中 x=108, y=100 → 头在画面上方
# 演播台 alpha 渐变: 顶部 120px 从透明渐变到不透明，遮挡过渡自然

filter_complex = ";".join([
    # 背景: 全屏铺满
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg]",

    # Live2D: 居中, y=100 让半身在台面上方
    "[1:v]scale=864:1536[l2d]",
    "[bg][l2d]overlay=108:100:shortest=1[v1]",

    # 演播台前景: 实体不透明, 放在底部 y=1340
    "[2:v]scale=1080:580[desk]",
    "[v1][desk]overlay=0:1340:shortest=1[v2]",

    # 顶部 Bar: 半透明黑底 + 频道名 + 日期
    "[v2]drawbox=x=0:y=0:w=1080:h=80:color=black@0.6:t=fill,"
    "drawtext=text='Mili Channel':fontsize=32:fontcolor=white:x=20:y=25,"
    "drawtext=text='2026-06-14':fontsize=28:fontcolor=white@0.8:x=900:y=28,"

    # 底部 Ticker (贴底，滚动加速)
    "drawbox=x=0:y=1840:w=1080:h=80:color=black@0.75:t=fill,"
    "drawtext=text='LIVE':fontsize=36:fontcolor=white:x=15:y=1860:"
    "box=1:boxcolor=red:boxborderw=6,"
    "drawtext=text='AI日报 | DeepSeek发布V4 | GitHub Copilot更新 | HuggingFace趋势':"
    "fontsize=28:fontcolor=white:x='1080-mod(t*200\\,2400)':y=1862,"
    "format=yuv420p[vout]"
])

cmd = [
    "ffmpeg", "-y",
    "-loop", "1", "-i", str(BG_IMAGE),
    "-c:v", "libvpx-vp9", "-i", str(LIVE2D_WEBM),
    "-loop", "1", "-i", str(DESK_FG),
    "-filter_complex", filter_complex,
    "-map", "[vout]",
    "-t", DURATION,
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "20",
    "-an",
    str(OUTPUT),
]

print("=" * 60)
print("Tech Validation v10: 3-layer with alpha-fade desk")
print("=" * 60)
print(f"BG:     {BG_IMAGE}")
print(f"Desk:   {DESK_FG}")
print(f"Live2D: {LIVE2D_WEBM.name}")
print(f"Output: {OUTPUT}")
print("=" * 60)

result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=120,
)

if result.returncode == 0:
    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"\n✅ OK! Output: {OUTPUT}")
    print(f"   Size: {size_mb:.1f} MB")
else:
    print(f"\n❌ FAILED!")
    print(f"stderr: {result.stderr[-1500:]}")
