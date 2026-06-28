import logging, sys, json, yaml
from pathlib import Path

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

from agents.director.agent import DirectorAgent

# 从 config 读取模型配置
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

director_model_name = config["roles"]["director"]
model_cfg = config["models"][director_model_name]
director = DirectorAgent(
    base_url=model_cfg["base_url"],
    api_key=model_cfg["api_key"],
    model=model_cfg["model"],
    max_tokens=config["agents"]["max_tokens_override"].get("director", 16384),
)
collected_dir = Path("data/2026-06-16/collected")
output_dir = Path("data/2026-06-16/scripts")
output_dir.mkdir(parents=True, exist_ok=True)

# 从 selection.json 加载选好的 topics
selection_file = Path("data/2026-06-16/selected/selection.json")
with open(selection_file, "r", encoding="utf-8") as f:
    selection = json.load(f)

# 找第一条有视频的 hot_topic
test_topic = None
for t in selection["hot_topics"]:
    if t.get("has_video"):
        test_topic = t
        break

if not test_topic:
    print("No topic with video found")
    sys.exit(1)

print(f"Testing topic: {test_topic.get('title', '')}")
print(f"Source: {test_topic.get('source_file', '')}")
print()

# 加载 manifest 和 source_data
manifest = director._load_manifest(collected_dir.parent / "media" / "manifest.json")
source_data = director._load_source_data(test_topic, collected_dir, manifest)

# 打印传入的 video segments 信息
segments = source_data.get("_video_segments", [])
print(f"Video segments passed to LLM: {len(segments)}")
if segments:
    print(f"  First: start={segments[0].get('start')}, end={segments[0].get('end')}, text={segments[0].get('text', '')[:30]}")
    print(f"  Last:  start={segments[-1].get('start')}, end={segments[-1].get('end')}, text={segments[-1].get('text', '')[:30]}")
print(f"Video duration: {source_data.get('_video_duration_s', 0)}s")
print()

script = director.generate_script(test_topic, source_data)
if not script:
    print("Script generation FAILED")
    sys.exit(1)

# 检查 visual 轨
visual = script.get("tracks", {}).get("visual", [])
print(f"\n=== RESULT ===")
print(f"total_duration_ms: {script.get('total_duration_ms')}")
print(f"visual items: {len(visual)}")
print()

for i, v in enumerate(visual):
    vtype = v.get("type")
    if vtype == "video_clip":
        tr = v.get("time_range", [])
        pa = v.get("play_audio", False)
        dur = v.get("duration_ms", 0)
        cap = v.get("caption", "")
        trans = v.get("transition", "")
        print(f"  [{i}] video_clip: time_range={tr}, play_audio={pa}, duration_ms={dur}, transition={trans}")
        print(f"       caption: {cap}")
    else:
        print(f"  [{i}] {vtype}: start_ms={v.get('start_ms')}, duration_ms={v.get('duration_ms')}")

# 保存完整脚本用于检查
out_file = output_dir / "test_single_script.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(script, f, ensure_ascii=False, indent=2)
print(f"\nFull script saved to: {out_file}")
