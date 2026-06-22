"""分析 aligned 脚本的 visual 轨结构"""
import json

for name in ["ai_daily", "hot_daily"]:
    path = f"data/2026-06-12/scripts_aligned/{name}.json"
    with open(path, "r", encoding="utf-8") as f:
        script = json.load(f)
    
    visual = script["tracks"]["visual"]
    print(f"\n{'='*60}")
    print(f"{name}: {len(visual)} visual items, total={script.get('total_duration_ms')}ms")
    print(f"{'='*60}")
    
    types = {}
    for v in visual:
        t = v.get("type", "?")
        types[t] = types.get(t, 0) + 1
    print(f"Types: {types}")
    
    for i, v in enumerate(visual):
        t = v.get("type", "?")
        src = str(v.get("source", ""))
        if src:
            src = src.split("\\")[-1].split("/")[-1][:40]
        else:
            src = v.get("component", "")[:30]
        print(f"  [{i:2d}] {t:12s} start={v.get('start_ms'):>7d} dur={v.get('duration_ms'):>6d}  {src}")
