"""
Director 入口脚本 - Phase 2: 选题 + 脚本生成

Usage:
    python -m agents.director.run_director
    python -m agents.director.run_director --date 2026-06-12
"""
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config_loader import load_config, get_model_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Director Agent - 选题 + 脚本生成")
    parser.add_argument("--date", type=str, default=None, help="日期 (YYYY-MM-DD)")
    args = parser.parse_args()
    
    today = args.date or datetime.now().strftime("%Y-%m-%d")
    
    # Load config
    config = load_config()
    
    # Paths
    data_root = Path(config.get("paths", {}).get("data_root", "data"))
    collected_dir = data_root / today / "collected"
    selected_dir = data_root / today / "selected"
    scripts_dir = data_root / today / "scripts"
    
    if not collected_dir.exists():
        logger.error(f"Collected 目录不存在: {collected_dir}")
        return
    
    file_count = len(list(collected_dir.glob("*.json")))
    logger.info(f"[director] 读取 {collected_dir} ({file_count} files)")
    
    # Init Director
    from agents.director.agent import DirectorAgent
    
    model_cfg = get_model_config(config, "director")
    agents_cfg = config.get("agents", {})
    max_tokens = agents_cfg.get("max_tokens_override", {}).get("director", agents_cfg.get("max_tokens", 8192))
    
    director = DirectorAgent(
        base_url=model_cfg["base_url"],
        api_key=model_cfg["api_key"],
        model=model_cfg["model"],
        temperature=agents_cfg.get("temperature", 0.7),
        max_tokens=max_tokens,
    )
    
    # ─── Phase 2a: 选题 ──────────────────────────────────
    logger.info("=" * 60)
    logger.info("[director] Phase 2a: 选题开始")
    logger.info("=" * 60)
    
    # 加载 manifest（用于过滤无素材的热搜）
    manifest_path = data_root / today / "media" / "manifest.json"
    manifest = None
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            logger.info(f"[director] 加载 manifest: {len(manifest)} 条素材")
        except Exception as e:
            logger.warning(f"[director] manifest 加载失败: {e}")
    
    selection = director.select_topics(collected_dir, manifest=manifest)
    
    # 保存选题结果
    selected_dir.mkdir(parents=True, exist_ok=True)
    selection_file = selected_dir / "selection.json"
    with open(selection_file, "w", encoding="utf-8") as f:
        json.dump(selection, f, ensure_ascii=False, indent=2)
    
    hot_count = len(selection.get("hot_topics", []))
    ai_count = len(selection.get("ai_topics", []))
    logger.info(f"[director] 选题结果: 热搜 {hot_count} 条, AI {ai_count} 条")
    logger.info(f"[director] 保存: {selection_file}")
    
    # ─── Phase 2b: 聚合脚本生成 ──────────────────────────
    logger.info("=" * 60)
    logger.info("[director] Phase 2b: 聚合脚本生成（2 条视频）")
    logger.info("=" * 60)
    
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts = []
    
    # AI 日报: 聚合 ai_topics → 1 条视频
    ai_topics = selection.get("ai_topics", [])
    if ai_topics:
        logger.info(f"[director] 生成 AI 日报（{len(ai_topics)} 条新闻聚合）")
        ai_script = director.generate_aggregated_script(
            topics=ai_topics,
            video_type="AI 日报",
            video_id="ai_daily",
            collected_dir=collected_dir,
            output_dir=scripts_dir,
        )
        if ai_script:
            scripts.append(ai_script)
    
    # 热搜集锦: 聚合 hot_topics → 1 条视频
    hot_topics = selection.get("hot_topics", [])
    if hot_topics:
        logger.info(f"[director] 生成热搜集锦（{len(hot_topics)} 条新闻聚合）")
        hot_script = director.generate_aggregated_script(
            topics=hot_topics,
            video_type="热搜集锦",
            video_id="hot_daily",
            collected_dir=collected_dir,
            output_dir=scripts_dir,
        )
        if hot_script:
            scripts.append(hot_script)
    
    # ─── Summary ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("[director] DONE")
    logger.info(f"  选题: 热搜 {hot_count} 条, AI {ai_count} 条")
    logger.info(f"  聚合脚本: {len(scripts)} 个视频")
    for s in scripts:
        dur = s.get('total_duration_ms', 0) / 1000
        logger.info(f"    - {s.get('id')}: {s.get('title')} ({dur:.0f}s)")
    logger.info(f"  脚本目录: {scripts_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
