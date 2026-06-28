"""只跑 hot_daily 聚合脚本生成，验证 video_clip time_range"""
import json, logging, sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

from agents.director.agent import DirectorAgent
from config_loader import load_config, get_model_config

config = load_config()
model_cfg = get_model_config(config, "director")
agents_cfg = config.get("agents", {})
max_tokens = agents_cfg.get("max_tokens_override", {}).get("director", 16384)

director = DirectorAgent(
    base_url=model_cfg["base_url"],
    api_key=model_cfg["api_key"],
    model=model_cfg["model"],
    temperature=agents_cfg.get("temperature", 0.7),
    max_tokens=max_tokens,
)

collected_dir = Path("data/2026-06-16/collected")
scripts_dir = Path("data/2026-06-16/scripts")

with open("data/2026-06-16/selected/selection.json", "r", encoding="utf-8") as f:
    selection = json.load(f)

hot_topics = selection.get("hot_topics", [])
print(f"Generating hot_daily ({len(hot_topics)} topics)")

hot_script = director.generate_aggregated_script(
    topics=hot_topics,
    video_type="热搜集锦",
    video_id="hot_daily",
    collected_dir=collected_dir,
    output_dir=scripts_dir,
)

if hot_script:
    visual = hot_script.get("tracks", {}).get("visual", [])
    for i, v in enumerate(visual):
        if v.get("type") == "video_clip":
            tr = v.get("time_range", [])
            pa = v.get("play_audio", False)
            src = v.get("source", "")
            dur = v.get("duration_ms", 0)
            print(f"  [{i}] video_clip: src={src}, time_range={tr}, play_audio={pa}, dur={dur}ms")
    total = hot_script.get("total_duration_ms", 0)
    print(f"\nDONE: {total}ms, {len(visual)} visual items")
else:
    print("FAILED")
