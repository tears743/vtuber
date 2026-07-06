"""
Collect 节点 — 数据采集

对应: agents/collector/run_teams.py → CollectorOrchestrator
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, CollectedData

logger = logging.getLogger(__name__)


@register
class CollectNode(BaseNode):
    type = "collect"
    label = "数据采集"
    category = "数据采集"
    reads = []
    writes = ["collected"]
    output_dirs = ["collected"]
    config_schema = {
        "run_date": {
            "type": "str", "label": "运行日期",
            "default": "",
            "description": "指定采集日期（YYYY-MM-DD），留空则自动使用当天"
        },
        "orchestrator_model": {
            "type": "model", "label": "编排模型",
            "default": "deepseek-v4-flash",
            "description": "用于选题规划的 LLM 模型"
        },
        "worker_model": {
            "type": "model", "label": "Worker 模型",
            "default": "deepseek-v4-flash",
            "description": "执行深度采集的 LLM 模型"
        },
        "platforms": {
            "type": "list", "label": "启用平台",
            "default": ["weibo", "douyin", "github", "huggingface"],
            "options": ["weibo", "douyin", "github", "huggingface"]
        },
        "max_workers": {
            "type": "int", "label": "并发 Worker 数",
            "default": 4, "min": 1, "max": 8
        },
        "weibo_max_items": {
            "type": "int", "label": "微博最大条数",
            "default": 50, "min": 10, "max": 100
        },
        "douyin_max_items": {
            "type": "int", "label": "抖音最大条数",
            "default": 30, "min": 10, "max": 100
        },
        "planning_prompt": {
            "type": "text", "label": "选题规划指令",
            "default": "",
            "prompt_file": "collect_planning.txt",
            "variables": [
                {"name": "date", "description": "当前日期，格式: YYYY-MM-DD"},
                {"name": "data_summary", "description": "各平台热榜摘要，自动从采集结果生成"},
            ],
            "description": "Orchestrator 选题规划的系统指令"
        },
        "worker_prompt": {
            "type": "text", "label": "Worker 采集指令",
            "default": "",
            "prompt_file": "collect_system.txt",
            "variables": [
                {"name": "date", "description": "当前日期"},
                {"name": "topics", "description": "要采集的话题列表"},
            ],
            "description": "各平台 Worker 执行深度采集的系统指令"
        },
        "opencli_binary": {
            "type": "str", "label": "OpenCLI 路径",
            "default": "node D:/workspace/opencli/dist/src/main.js"
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        """执行数据采集"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from config_loader import load_config, get_model_config
        from agents.collector.orchestrator import CollectorOrchestrator

        on_progress("初始化采集器...", 0.0)

        config = ctx.config or load_config()
        orchestrator_cfg = get_model_config(config, "orchestrator")
        worker_cfg = get_model_config(config, "worker")

        # 覆盖模型配置（如果节点上选了不同模型）
        models = config.get("models", {})
        orch_model_name = self.get_config("orchestrator_model", "deepseek-v4-flash")
        work_model_name = self.get_config("worker_model", "deepseek-v4-flash")

        if orch_model_name in models:
            orch_model = models[orch_model_name]
            orchestrator_cfg = {
                "base_url": orch_model["base_url"],
                "api_key": orch_model["api_key"],
                "model": orch_model["model"],
            }
        if work_model_name in models:
            work_model = models[work_model_name]
            worker_cfg = {
                "base_url": work_model["base_url"],
                "api_key": work_model["api_key"],
                "model": work_model["model"],
            }

        data_dir = ctx.data_root / ctx.date / "collected"
        data_dir.mkdir(parents=True, exist_ok=True)

        opencli = self.get_config("opencli_binary", config.get("opencli", {}).get("binary", "opencli"))

        orchestrator = CollectorOrchestrator(
            orchestrator_base_url=orchestrator_cfg["base_url"],
            orchestrator_api_key=orchestrator_cfg["api_key"],
            orchestrator_model=orchestrator_cfg["model"],
            worker_base_url=worker_cfg["base_url"],
            worker_api_key=worker_cfg["api_key"],
            worker_model=worker_cfg["model"],
            opencli_binary=opencli,
            data_dir=data_dir,
            max_workers=self.get_config("max_workers", 4),
        )

        on_progress("采集中...", 0.2)
        import asyncio
        await asyncio.to_thread(orchestrator.run)
        on_progress("采集完成", 0.9)

        # 构建 CollectedData
        files = sorted([f.name for f in data_dir.glob("*.json")])
        platforms = {}
        for f in files:
            parts = f.split("_")
            if len(parts) >= 3:
                platform = parts[2] if parts[2] not in ("topic", "hot") else parts[1]
                platforms[platform] = platforms.get(platform, 0) + 1

        ctx.collected = CollectedData(
            dir=data_dir,
            files=files,
            count=len(files),
            platforms=platforms,
        )
        on_progress(f"采集完成: {len(files)} 条", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 collected 数据"""
        data_dir = ctx.data_root / ctx.date / "collected"
        files = sorted([f.name for f in data_dir.glob("*.json")])
        platforms = {}
        for f in files:
            parts = f.split("_")
            if len(parts) >= 3:
                platform = parts[2] if parts[2] not in ("topic", "hot") else parts[1]
                platforms[platform] = platforms.get(platform, 0) + 1
        ctx.collected = CollectedData(
            dir=data_dir,
            files=files,
            count=len(files),
            platforms=platforms,
        )
