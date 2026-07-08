"""
CronTrigger 节点 — 定时触发器

按 Cron 表达式定时触发下游节点执行。
依赖: croniter（pip install croniter）

工作流模式: scheduled
用法:
    {"id": "cron_1", "type": "cron_trigger", "config": {"cron_expr": "0 8 * * *"}}
"""
import asyncio
from datetime import datetime

from server.nodes.base import NodeInput, NodeOutput, TriggerNode
from server.nodes.registry import node


@node(
    "cron_trigger",
    version="1.0.0",
    icon="⏰",
    color="#FF9800",
    author="videofactory",
)
class CronTriggerNode(TriggerNode):
    """定时触发器 — Cron 表达式驱动工作流"""

    label = "定时触发"
    category = "触发器"
    description = "按 Cron 表达式定时触发下游节点（标准5字段：分 时 日 月 周）"

    inputs = []  # 触发器无输入连线

    outputs = [
        NodeOutput(name="trigger", type="Trigger", label="触发信号",
                   description="包含 triggered_at 和 date 字段"),
    ]

    config_schema = {
        "cron_expr": {
            "type": "string",
            "label": "Cron 表达式",
            "default": "0 8 * * *",
            "description": "标准5字段：分 时 日 月 周（如 '0 8 * * *' = 每天8点）",
        },
        "timezone": {
            "type": "string",
            "label": "时区",
            "default": "Asia/Shanghai",
            "description": "IANA 时区名（如 Asia/Shanghai, UTC, America/New_York）",
        },
    }

    async def listen(self, ctx, emit):
        """定时监听循环"""
        try:
            from croniter import croniter
            from zoneinfo import ZoneInfo
        except ImportError as e:
            ctx.logger.error(f"缺少依赖: {e}. 请运行 pip install croniter")
            raise

        cron_expr = self.get_config("cron_expr", "0 8 * * *")
        tz_name = self.get_config("timezone", "Asia/Shanghai")

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            ctx.logger.warning(f"未知时区 '{tz_name}'，使用本地时区")
            tz = None

        ctx.logger.info(f"CronTrigger 启动: '{cron_expr}' (时区: {tz_name})")

        while True:
            now = datetime.now(tz) if tz else datetime.now()

            try:
                next_run = croniter(cron_expr, now).get_next(datetime)
            except Exception as e:
                ctx.logger.error(f"无效的 Cron 表达式 '{cron_expr}': {e}")
                await asyncio.sleep(60)
                continue

            wait_s = (next_run - now).total_seconds()
            ctx.logger.info(f"下次触发: {next_run}, 等待 {wait_s:.0f}s")

            # 分段 sleep，以便能响应 stop 请求
            while wait_s > 0:
                sleep_step = min(wait_s, 5.0)
                await asyncio.sleep(sleep_step)
                wait_s -= sleep_step

            trigger_time = datetime.now(tz) if tz else datetime.now()
            ctx.logger.info(f"触发! 时间: {trigger_time.isoformat()}")

            await emit({
                "triggered_at": trigger_time.isoformat(),
                "date": trigger_time.strftime("%Y-%m-%d"),
                "cron_expr": cron_expr,
            })
