"""
BaseNode 抽象类

所有节点的基类，定义统一接口：
- reads/writes 声明
- config_schema 供 UI 渲染表单
- execute() 执行逻辑
- validate() 校验上游数据就绪
- render_prompt() 模板变量注入
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from server.models import PipelineContext

logger = logging.getLogger(__name__)


class BaseNode(ABC):
    """节点基类"""

    # ── 子类必须覆盖 ──
    type: str = ""
    label: str = ""
    category: str = ""  # "数据采集" | "内容处理" | "音视频" | "输出"
    reads: list[str] = []
    writes: list[str] = []
    config_schema: dict = {}

    def __init__(self, node_id: str, config: Optional[dict] = None):
        self.id = node_id
        self.config = config or {}
        # 用 config_schema 的 default 填充未设置的配置
        for key, schema in self.config_schema.items():
            if key not in self.config and "default" in schema:
                self.config[key] = schema["default"]

    @abstractmethod
    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: Callable[[str, float], None],
    ) -> None:
        """
        执行节点逻辑。
        
        从 ctx 读取 self.reads 中声明的字段，处理后写入 self.writes 声明的字段。
        
        Args:
            ctx: 管线上下文（共享数据）
            on_progress: 进度回调 (message, progress_0_to_1)
        """
        ...

    def validate(self, ctx: PipelineContext) -> list[str]:
        """检查 reads 中的字段是否已就绪，返回错误列表"""
        errors = []
        for key in self.reads:
            if getattr(ctx, key, None) is None:
                errors.append(f"缺少上游数据: {key}")
        return errors

    def check_cache(self, ctx: PipelineContext) -> bool:
        """
        检查本节点产出是否已有缓存（可跳过执行）。
        
        默认逻辑：检查 output_dirs 对应的 data/{date}/{dir} 是否存在且非空。
        子类可覆盖此方法实现更精细的缓存策略。
        
        Returns:
            True = 缓存命中，可跳过; False = 需要执行
        """
        from pathlib import Path

        # 如果节点没有定义 output_dirs，则不缓存
        output_dirs = getattr(self, 'output_dirs', None)
        if not output_dirs:
            return False

        for dir_name in output_dirs:
            output_dir = ctx.data_root / ctx.date / dir_name
            if not output_dir.exists():
                return False
            if not any(output_dir.iterdir()):
                return False
        return True

    def restore_cache(self, ctx: PipelineContext) -> None:
        """
        缓存命中时，从磁盘恢复产出数据到 ctx。
        子类必须覆盖此方法以正确恢复上下文。
        """
        pass

    def render_prompt(self, template: str, variables: dict) -> str:
        """将模板中的 {{变量}} 替换为实际值"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def get_config(self, key: str, fallback: Any = None) -> Any:
        """获取节点配置，支持 fallback"""
        return self.config.get(key, fallback)

    def to_dict(self) -> dict:
        """序列化为 JSON 可存储的 dict"""
        return {
            "id": self.id,
            "type": self.type,
            "config": self.config,
        }

    @classmethod
    def get_definition(cls) -> dict:
        """返回节点类型定义（供前端节点库使用）"""
        schema = {}
        for key, field in cls.config_schema.items():
            field_copy = dict(field)
            # 如果指定了 prompt_file，从文件读取 default 内容
            if "prompt_file" in field_copy:
                from pathlib import Path
                prompt_path = Path(__file__).parent.parent / "prompts" / field_copy["prompt_file"]
                try:
                    field_copy["default"] = prompt_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    logger.warning(f"Prompt file not found: {prompt_path}")
                del field_copy["prompt_file"]
            schema[key] = field_copy
        return {
            "type": cls.type,
            "label": cls.label,
            "category": cls.category,
            "reads": cls.reads,
            "writes": cls.writes,
            "config_schema": schema,
        }

