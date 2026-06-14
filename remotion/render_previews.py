"""
批量渲染 Live2D 动作和表情预览视频
每个 3 秒 (90 帧)，--concurrency=1 保证动画流畅
"""
import json
import subprocess
from pathlib import Path

REMOTION_DIR = Path(__file__).parent
OUTPUT_DIR = REMOTION_DIR / "output" / "previews"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

config = json.load(open(REMOTION_DIR / "output" / "preview_config.json"))

all_items = []
for m in config["motions"]:
    all_items.append(("motion", m["name"], m["props"]))
for e in config["expressions"]:
    all_items.append(("expression", e["name"], e["props"]))

print(f"渲染 {len(all_items)} 个预览视频...")

for kind, name, props in all_items:
    output_file = OUTPUT_DIR / f"{kind}_{name}.webm"
    if output_file.exists():
        print(f"  [skip] {output_file.name}")
        continue

    props_file = OUTPUT_DIR / f"_{name}_props.json"
    with open(props_file, "w") as f:
        json.dump(props, f)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts", "Live2D",
        f"--props={props_file.resolve()}",
        "--gl=angle",
        "--codec=vp9",
        f"--output={output_file.resolve()}",
        "--frames=0-89",
        "--concurrency=1",
    ]

    print(f"  [render] {kind}: {name}...", end=" ", flush=True)
    result = subprocess.run(
        cmd, cwd=str(REMOTION_DIR),
        capture_output=True, text=True, timeout=120,
        shell=True, encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        size = output_file.stat().st_size / 1024
        print(f"OK {size:.0f}KB")
    else:
        print(f"FAIL")
        print(f"    {result.stderr[:200]}")

print("\n完成! 预览文件在:", OUTPUT_DIR)
