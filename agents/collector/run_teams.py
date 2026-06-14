"""
Layer 1: Agent Teams 并发采集入口

用法:
    python -m agents.collector.run_teams

架构:
    Orchestrator (DeepSeek V4-flash) -> Workers (local/remote model, concurrent)
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config_loader import load_config, get_model_config, get_today_dir, ensure_dirs, PROJECT_ROOT
from agents.collector.orchestrator import CollectorOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    cfg = load_config()
    ensure_dirs(cfg)
    
    # 从模型池获取配置
    orch_model = get_model_config(cfg, "orchestrator")
    worker_model = get_model_config(cfg, "worker")
    
    opencli_cfg = cfg.get("opencli", {})
    agents_cfg = cfg.get("agents", {})
    data_dir = get_today_dir(cfg) / "collected"
    
    orchestrator = CollectorOrchestrator(
        # Orchestrator
        orchestrator_base_url=orch_model["base_url"],
        orchestrator_api_key=orch_model["api_key"],
        orchestrator_model=orch_model["model"],
        # Workers
        worker_base_url=worker_model["base_url"],
        worker_api_key=worker_model["api_key"],
        worker_model=worker_model["model"],
        # Shared
        opencli_binary=opencli_cfg.get("binary", "opencli"),
        data_dir=data_dir,
        max_workers=agents_cfg.get("max_workers", 4),
    )
    
    results = orchestrator.run()
    
    logger.info("=" * 60)
    logger.info(f"Agent Teams collection complete:")
    logger.info(f"  Workers launched: {results['workers']}")
    logger.info(f"  Files saved: {results['files_saved']}")
    logger.info(f"  Total items: {results['total_items']}")
    if results["errors"]:
        logger.warning(f"  Total errors: {results['errors']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
