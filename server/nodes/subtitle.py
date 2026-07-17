"""Independent ASS subtitle track generator."""

import json
import re
from pathlib import Path

from server.models import AlignedData, PipelineContext, SubtitleData
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import register


@register
class SubtitleNode(BaseNode):
    type = "subtitle"
    label = "字幕生成"
    category = "音视频"
    description = "根据真实 voice 时间轴生成独立 ASS 字幕轨"
    icon = "字"
    color = "#22C55E"
    cache_revision = "ass_subtitle_v1"

    inputs = [NodeInput("aligned", type="AlignedData", label="多轨脚本", required=True)]
    outputs = [NodeOutput("subtitles", type="SubtitleData", label="字幕轨")]
    reads = ["aligned"]
    writes = ["subtitles"]
    output_dirs = ["subtitles"]

    config_schema = {
        "font_name": {"type": "str", "label": "字体", "default": "Microsoft YaHei"},
        "font_size": {"type": "int", "label": "字号", "default": 52, "min": 24, "max": 96},
        "primary_color": {"type": "color", "label": "文字颜色", "default": "#FFFFFF"},
        "outline_color": {"type": "color", "label": "描边颜色", "default": "#111827"},
        "outline_width": {"type": "float", "label": "描边宽度", "default": 4.0, "min": 0, "max": 10, "step": 0.5},
        "shadow": {"type": "float", "label": "阴影", "default": 1.5, "min": 0, "max": 8, "step": 0.5},
        "margin_bottom": {"type": "int", "label": "底部边距", "default": 260, "min": 40, "max": 700},
        "max_chars_per_line": {"type": "int", "label": "每行最大字数", "default": 18, "min": 8, "max": 32},
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        aligned = self.get_input("aligned") or ctx.aligned
        if aligned is None:
            raise RuntimeError("缺少 aligned 输入")

        subtitle_dir = ctx.data_root / ctx.date / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        script_files = self._script_files(aligned)
        files = {}

        for index, script_path in enumerate(script_files):
            script = json.loads(script_path.read_text(encoding="utf-8"))
            script_id = script.get("id", script_path.stem)
            output_path = subtitle_dir / f"{script_id}.ass"
            events = self._events(script)
            if not events:
                continue
            output_path.write_text(self._build_ass(events), encoding="utf-8-sig")
            files[script_id] = output_path
            on_progress(
                f"字幕 [{index + 1}/{len(script_files)}]: {script_id} ({len(events)} 条)",
                (index + 1) / max(len(script_files), 1),
            )

        if script_files and len(files) != len(script_files):
            raise RuntimeError(f"字幕生成不完整: {len(files)}/{len(script_files)}")

        ctx.subtitles = SubtitleData(dir=subtitle_dir, files=files, success_count=len(files))
        on_progress(f"字幕完成: {len(files)} 个轨道", 1.0)
        return {"subtitles": ctx.subtitles}

    def restore_cache(self, ctx: PipelineContext):
        subtitle_dir = ctx.data_root / ctx.date / "subtitles"
        files = {path.stem: path for path in subtitle_dir.glob("*.ass")}
        ctx.subtitles = SubtitleData(dir=subtitle_dir, files=files, success_count=len(files))

    def _script_files(self, aligned: AlignedData) -> list[Path]:
        files = [Path(path) for path in (aligned.files or []) if Path(path).exists()]
        if files:
            return sorted(files)
        return sorted(Path(aligned.dir).glob("*.json"))

    def _events(self, script: dict) -> list[tuple[int, int, str]]:
        events = []
        for item in script.get("tracks", {}).get("voice", []):
            start_ms = int(item.get("start_ms", 0) or 0)
            duration_ms = int(item.get("duration_ms", 0) or 0)
            text = str(item.get("subtitle") or item.get("text") or "").strip()
            text = re.sub(r"（[^）]{1,30}）", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if duration_ms <= 0 or not text:
                continue
            events.append((start_ms, start_ms + duration_ms, self._wrap_text(text)))
        return events

    def _wrap_text(self, text: str) -> str:
        limit = int(self.get_config("max_chars_per_line", 18))
        chunks = [text[index:index + limit] for index in range(0, len(text), limit)]
        return r"\N".join(chunks)

    def _build_ass(self, events: list[tuple[int, int, str]]) -> str:
        font_name = str(self.get_config("font_name", "Microsoft YaHei")).replace(",", " ")
        font_size = int(self.get_config("font_size", 52))
        primary = self._ass_color(self.get_config("primary_color", "#FFFFFF"))
        outline = self._ass_color(self.get_config("outline_color", "#111827"))
        outline_width = float(self.get_config("outline_width", 4.0))
        shadow = float(self.get_config("shadow", 1.5))
        margin_v = int(self.get_config("margin_bottom", 260))
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},&H64000000,-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        rows = []
        for start_ms, end_ms, text in events:
            safe_text = text.replace("{", r"\{").replace("}", r"\}")
            rows.append(
                f"Dialogue: 0,{self._ass_time(start_ms)},{self._ass_time(end_ms)},Default,,0,0,0,,{safe_text}"
            )
        return header + "\n".join(rows) + "\n"

    @staticmethod
    def _ass_time(milliseconds: int) -> str:
        centiseconds = max(0, milliseconds // 10)
        hours, remainder = divmod(centiseconds, 360000)
        minutes, remainder = divmod(remainder, 6000)
        seconds, centiseconds = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

    @staticmethod
    def _ass_color(value: str) -> str:
        text = str(value or "#FFFFFF").lstrip("#")
        if len(text) != 6:
            text = "FFFFFF"
        red, green, blue = text[0:2], text[2:4], text[4:6]
        return f"&H00{blue}{green}{red}"
