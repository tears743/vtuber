"""
Director 节点 — 选题 + 脚本生成

对应: agents/director/run_director.py → DirectorAgent
产出: selected + scripts
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, SelectedData, ScriptsData

logger = logging.getLogger(__name__)


@register
class DirectorNode(BaseNode):
    type = "director"
    label = "选题编排"
    category = "内容处理"
    reads = ["collected", "media", "recognized", "transcribed"]
    writes = ["selected", "scripts"]
    output_dirs = ["selected", "scripts"]
    config_schema = {
        "model": {
            "type": "model", "label": "LLM 模型",
            "default": "deepseek-v4-flash"
        },
        "temperature": {
            "type": "float", "label": "温度",
            "default": 0.3, "min": 0, "max": 1.5, "step": 0.1
        },
        "max_tokens": {
            "type": "int", "label": "最大输出 tokens",
            "default": 16384, "min": 4096, "max": 65536
        },
        "topic_selection_prompt": {
            "type": "text", "label": "选题指令",
            "default": "",
            "prompt_file": "director_topic_selection.txt",
            "variables": [
                {"name": "video_type", "description": "视频类型名（热搜集锦/AI日报）"},
                {"name": "type_instructions", "description": "该类型的具体说明"},
                {"name": "materials", "description": "当日可用素材列表"},
                {"name": "prefix", "description": "选题 ID 前缀"},
            ],
            "description": "控制选题标准、排除规则、输出格式"
        },
        "script_generation_prompt": {
            "type": "text", "label": "脚本生成指令",
            "default": "",
            "prompt_file": "director_script_generation.txt",
            "variables": [
                {"name": "video_type", "description": "视频类型名"},
                {"name": "topic_data", "description": "选中的话题详细数据"},
                {"name": "media_assets", "description": "可用素材清单"},
                {"name": "duration_target", "description": "目标时长（秒）"},
            ],
            "description": "控制角色设定、风格、轨道格式"
        },
        "video_types": {
            "type": "list", "label": "视频类型",
            "default": ["热搜集锦", "AI 日报"],
            "description": "要生成的视频种类列表"
        },
        "hot_topics_count": {
            "type": "int", "label": "热搜选题数",
            "default": 20, "min": 5, "max": 40
        },
        "ai_topics_count": {
            "type": "int", "label": "AI 选题数",
            "default": 20, "min": 5, "max": 40
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from config_loader import get_model_config
        from agents.director.agent import DirectorAgent

        on_progress("初始化 Director...", 0.0)

        config = ctx.config
        models = config.get("models", {})
        model_name = self.get_config("model", "deepseek-v4-flash")

        if model_name in models:
            model_cfg = models[model_name]
        else:
            model_cfg = get_model_config(config, "director")

        agents_cfg = config.get("agents", {})
        max_tokens = self.get_config("max_tokens", 16384)

        director = DirectorAgent(
            base_url=model_cfg["base_url"],
            api_key=model_cfg["api_key"],
            model=model_cfg["model"],
            temperature=self.get_config("temperature", 0.3),
            max_tokens=max_tokens,
        )

        collected_dir = ctx.collected.dir
        data_root = ctx.data_root
        today = ctx.date
        selected_dir = data_root / today / "selected"
        scripts_dir = data_root / today / "scripts"
        selected_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)

        # 加载 manifest
        manifest = ctx.media.manifest if ctx.media else None

        # Phase 2a: 选题
        on_progress("选题中...", 0.2)
        import asyncio
        selection = await asyncio.to_thread(director.select_topics, collected_dir, manifest)

        selection_file = selected_dir / "selection.json"
        with open(selection_file, "w", encoding="utf-8") as f:
            json.dump(selection, f, ensure_ascii=False, indent=2)

        ctx.selected = SelectedData(
            dir=selected_dir,
            file=selection_file,
            hot_topics=selection.get("hot_topics", []),
            ai_topics=selection.get("ai_topics", []),
        )

        on_progress(f"选题完成: 热搜 {len(ctx.selected.hot_topics)} 条, AI {len(ctx.selected.ai_topics)} 条", 0.5)

        # Phase 2b: 脚本生成
        on_progress("生成脚本中...", 0.6)
        scripts = []

        ai_topics = selection.get("ai_topics", [])
        if ai_topics:
            ai_script = await asyncio.to_thread(
                director.generate_aggregated_script,
                topics=ai_topics,
                video_type="AI 日报",
                video_id="ai_daily",
                collected_dir=collected_dir,
                output_dir=scripts_dir,
                rankings=selection.get("rankings", []),
            )
            if ai_script:
                scripts.append(ai_script)

        hot_topics = selection.get("hot_topics", [])
        if hot_topics:
            hot_script = await asyncio.to_thread(
                director.generate_aggregated_script,
                topics=hot_topics,
                video_type="热搜集锦",
                video_id="hot_daily",
                collected_dir=collected_dir,
                output_dir=scripts_dir,
            )
            if hot_script:
                scripts.append(hot_script)

        # 构建 ScriptsData
        script_files = sorted(scripts_dir.glob("*.json"))
        scripts_dict = {}
        duration_dict = {}
        for sp in script_files:
            with open(sp, "r", encoding="utf-8") as f:
                s = json.load(f)
            sid = s.get("id", sp.stem)
            scripts_dict[sid] = s
            duration_dict[sid] = s.get("total_duration_ms", 0)

        ctx.scripts = ScriptsData(
            dir=scripts_dir,
            files=[p for p in script_files],
            scripts=scripts_dict,
            total_duration_ms=duration_dict,
        )
        on_progress(f"脚本生成完成: {len(scripts)} 个视频", 1.0)

    def restore_cache(self, ctx):
        """从磁盘恢复 selected + scripts"""
        from server.models import SelectedData, ScriptsData
        import json

        selected_dir = ctx.data_root / ctx.date / "selected"
        scripts_dir = ctx.data_root / ctx.date / "scripts"

        # 恢复 selected
        selection_file = selected_dir / "selection.json"
        selection = {}
        if selection_file.exists():
            with open(selection_file, "r", encoding="utf-8") as f:
                selection = json.load(f)
        ctx.selected = SelectedData(
            dir=selected_dir,
            file=selection_file,
            hot_topics=selection.get("hot_topics", []),
            ai_topics=selection.get("ai_topics", []),
        )

        # 恢复 scripts
        script_files = sorted(scripts_dir.glob("*.json"))
        scripts_dict = {}
        duration_dict = {}
        for sp in script_files:
            with open(sp, "r", encoding="utf-8") as f:
                s = json.load(f)
            sid = s.get("id", sp.stem)
            scripts_dict[sid] = s
            duration_dict[sid] = s.get("total_duration_ms", 0)
        ctx.scripts = ScriptsData(
            dir=scripts_dir,
            files=[p for p in script_files],
            scripts=scripts_dict,
            total_duration_ms=duration_dict,
        )
