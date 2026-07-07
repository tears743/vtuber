"""
Collect 节点 — 数据采集

对应: agents/collector/run_teams.py → CollectorOrchestrator
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register
from server.models import PipelineContext, CollectedData

logger = logging.getLogger(__name__)


@register
class CollectNode(BaseNode):
    type = "collect"
    label = "数据采集"
    category = "数据采集"
    description = "从微博/抖音/HuggingFace/GitHub 采集热点数据"
    version = "1.0.0"
    icon = "🕷️"
    color = "#4CAF50"
    author = "videofactory"

    # 新方式：连线桩声明
    inputs = []  # collect 是入口节点，无上游连线
    outputs = [
        NodeOutput(name="collected", type="CollectedData", label="采集数据",
                   description="采集的原始数据（JSON 文件列表）"),
    ]

    # 向后兼容
    reads = []
    writes = ["collected"]
    output_dirs = ["collected"]
    cacheable = True

    # 失败策略：采集失败可以跳过（用缓存数据）
    on_failure = "skip"
    max_retries = 2
    retry_delay = 5.0
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

    SUPPORTED_PLATFORMS = {"weibo", "douyin", "github", "huggingface"}

    def _get_enabled_platforms(self) -> list[str]:
        platforms = self.get_config("platforms", ["weibo", "douyin", "github", "huggingface"])
        if not isinstance(platforms, list):
            return ["weibo", "douyin", "github", "huggingface"]

        enabled = []
        for platform in platforms:
            name = str(platform).strip().lower()
            if name in self.SUPPORTED_PLATFORMS and name not in enabled:
                enabled.append(name)
        return enabled or ["weibo", "douyin", "github", "huggingface"]

    def _get_platform_files(self, data_dir: Path, date_str: str, platform: str) -> list[str]:
        pattern = f"{date_str}_{platform}_*.json"
        return sorted(f.name for f in data_dir.glob(pattern) if f.is_file())

    def _build_collected_data(self, data_dir: Path) -> CollectedData:
        files = sorted(f.name for f in data_dir.glob("*.json") if f.is_file())
        platforms = {}
        for filename in files:
            parts = Path(filename).stem.split("_", 2)
            if len(parts) >= 3 and parts[1] in self.SUPPORTED_PLATFORMS:
                platforms[parts[1]] = platforms.get(parts[1], 0) + 1

        return CollectedData(
            dir=data_dir,
            files=files,
            count=len(files),
            platforms=platforms,
        )

    async def check_cache(self, ctx: PipelineContext) -> bool:
        """按日期+站点判断缓存命中。

        只有当前日期下所选站点都已经产出过文件时，才跳过整次采集。
        """
        data_dir = ctx.data_root / ctx.date / "collected"
        if not data_dir.exists():
            return False

        enabled_platforms = self._get_enabled_platforms()
        missing = [
            platform
            for platform in enabled_platforms
            if not self._get_platform_files(data_dir, ctx.date, platform)
        ]
        if missing:
            logger.info(f"[{self.id}] collect 缓存未命中，缺少站点: {', '.join(missing)}")
            return False

        logger.info(
            f"[{self.id}] collect 缓存命中: date={ctx.date}, platforms={enabled_platforms}"
        )
        return True

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
        enabled_platforms = self._get_enabled_platforms()

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
            enabled_platforms=enabled_platforms,
        )

        on_progress(f"采集中... ({', '.join(enabled_platforms)})", 0.2)
        import asyncio
        await asyncio.to_thread(orchestrator.run)
        on_progress("采集完成", 0.9)

        ctx.collected = self._build_collected_data(data_dir)
        on_progress(f"采集完成: {ctx.collected.count} 条", 1.0)

    async def restore_cache(self, ctx):
        """从磁盘恢复 collected 数据"""
        data_dir = ctx.data_root / ctx.date / "collected"
        ctx.collected = self._build_collected_data(data_dir)
