"""
Pipeline Context 数据模型定义

所有节点共享的统一上下文，每个节点从中 reads/writes。
与现有代码的文件目录结构完全对齐。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CollectedData:
    """采集阶段产出 — 对应 agents/collector/orchestrator.py"""
    dir: Path
    files: list = field(default_factory=list)
    count: int = 0
    platforms: dict = field(default_factory=dict)  # {"weibo": 16, "douyin": 15, ...}


@dataclass
class MediaData:
    """素材下载+识别阶段产出 — 对应 media_downloader.py + media_recognizer.py

    manifest.json 实际结构:
    {
        "filename.json": {
            "images": [{"path": "...", "width": ..., "description": "..."}],
            "video": {"path": "...", "duration_s": ..., "summary": "..."},
            "readme": {"path": "...", "summary": "..."},
            "author": "@昵称"
        }
    }
    """
    dir: Path
    manifest_path: Path = None
    manifest: dict = field(default_factory=dict)
    total_items: int = 0
    total_images: int = 0
    total_videos: int = 0
    total_readmes: int = 0


@dataclass
class SelectedData:
    """Director 选题阶段产出 — 对应 run_director.py Phase 2a"""
    dir: Path
    file: Path = None
    hot_topics: list = field(default_factory=list)
    ai_topics: list = field(default_factory=list)


@dataclass
class ScriptsData:
    """脚本生成阶段产出 — 对应 run_director.py Phase 2b"""
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)  # {"hot_daily": {完整脚本}, ...}
    total_duration_ms: dict = field(default_factory=dict)


@dataclass
class AudioData:
    """TTS 阶段产出 — 对应 run_render.py step_tts()

    durations.json: {"hot_daily": {"0": 3200, "1": 4100, ...}}
    注意: JSON key 是字符串
    """
    dir: Path
    durations_path: Path = None
    durations: dict = field(default_factory=dict)
    segments: dict = field(default_factory=dict)  # {"hot_daily": [voice_00.wav, ...]}


@dataclass
class AlignedData:
    """时间轴对齐阶段产出 — 对应 run_render.py step_align()"""
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)


@dataclass
class OverlayData:
    """Overlay 卡片渲染产出 — VP9 alpha webm"""
    dir: Path
    files: dict = field(default_factory=dict)  # {"hot_daily": "hot_daily_overlay.webm"}
    success_count: int = 0
    failed_count: int = 0


@dataclass
class VisualData:
    """背景视觉层产出 — 不透明 mp4"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class Live2DData:
    """Live2D 渲染产出 — VP9 alpha webm"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class FinalData:
    """最终合成产出 — H.264 1080x1920"""
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0
    total_duration_s: dict = field(default_factory=dict)


@dataclass
class PipelineContext:
    """全管线共享的数据上下文"""

    # 基础信息
    date: str = ""
    data_root: Path = None
    config: dict = field(default_factory=dict)

    # 各阶段产出物
    collected: Optional[CollectedData] = None
    media: Optional[MediaData] = None
    recognized: Optional[bool] = None   # 识别完成标记
    transcribed: Optional[bool] = None  # 转录完成标记
    selected: Optional[SelectedData] = None
    scripts: Optional[ScriptsData] = None
    audio: Optional[AudioData] = None
    aligned: Optional[AlignedData] = None
    overlay: Optional[OverlayData] = None
    visual: Optional[VisualData] = None
    live2d: Optional[Live2DData] = None
    final: Optional[FinalData] = None
