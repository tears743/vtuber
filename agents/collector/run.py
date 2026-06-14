"""
Layer 1: 采集 Agent 运行入口
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config_loader import load_config, ensure_dirs, PROJECT_ROOT
from agents.collector.agent import CollectorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    cfg = load_config()
    ensure_dirs(cfg)
    
    director_cfg = cfg["director"]
    opencli_cfg = cfg.get("opencli", {})
    data_dir = PROJECT_ROOT / cfg["paths"]["data"]
    
    agent = CollectorAgent(
        llm_base_url=director_cfg["base_url"],
        llm_api_key=director_cfg["api_key"],
        llm_model=director_cfg["model"],
        opencli_binary=opencli_cfg.get("binary", "opencli"),
        data_dir=data_dir,
    )
    
    results = agent.run()
    
    logger.info("═" * 50)
    logger.info(f"📊 采集完成:")
    logger.info(f"   文件数: {len(results['files_saved'])}")
    logger.info(f"   总条目: {results['total_items']}")
    if results["errors"]:
        logger.warning(f"   错误数: {len(results['errors'])}")


if __name__ == "__main__":
    main()
