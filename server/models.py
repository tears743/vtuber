"""Pipeline data models and runtime context."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CollectedData:
    dir: Path
    files: list = field(default_factory=list)
    count: int = 0
    platforms: dict = field(default_factory=dict)


@dataclass
class MediaData:
    dir: Path
    manifest_path: Path = None
    manifest: dict = field(default_factory=dict)
    total_items: int = 0
    total_images: int = 0
    total_videos: int = 0
    total_readmes: int = 0


@dataclass
class SelectedData:
    dir: Path
    file: Path = None
    hot_topics: list = field(default_factory=list)
    ai_topics: list = field(default_factory=list)


@dataclass
class ScriptsData:
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)
    total_duration_ms: dict = field(default_factory=dict)


@dataclass
class AudioData:
    dir: Path
    durations_path: Path = None
    durations: dict = field(default_factory=dict)
    segments: dict = field(default_factory=dict)


@dataclass
class AlignedData:
    dir: Path
    files: list = field(default_factory=list)
    scripts: dict = field(default_factory=dict)


@dataclass
class OverlayData:
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0
    failed_count: int = 0


@dataclass
class VisualData:
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class SubtitleData:
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class Live2DData:
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0


@dataclass
class FinalData:
    dir: Path
    files: dict = field(default_factory=dict)
    success_count: int = 0
    total_duration_s: dict = field(default_factory=dict)


class MessageBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()

    def on(self, event: str, handler: Callable):
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, data: dict):
        self._queue.put_nowait({"event": event, "data": data})

    async def drain(self):
        while not self._queue.empty():
            item = self._queue.get_nowait()
            event = item["event"]
            data = item["data"]
            for handler in self._handlers.get(event, []):
                try:
                    result = handler(data)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logging.getLogger("workflow.messagebus").error(
                        "Message handler failed (%s): %s", event, e
                    )


class PipelineContext:
    def __init__(
        self,
        date: str = "",
        data_root: Path = None,
        config: dict = None,
        run_id: str = "",
    ):
        self.date = date
        self.data_root = data_root or Path("data")
        self.config = config or {}
        self.run_id = run_id
        self.data: dict[str, Any] = {}
        self.message_bus = MessageBus()
        self.logger = logging.getLogger(f"workflow.{run_id}") if run_id else logging.getLogger("workflow")
        self._legacy_fields: dict[str, Any] = {}
        self._edge_aliases: dict[str, tuple[str, str]] = {}

    def write(self, node_id: str, output_name: str, value: Any) -> None:
        key = f"{node_id}:{output_name}"
        self.data[key] = value
        self.logger.debug("ctx.write: %s = %s", key, type(value).__name__)

    def read(self, node_id: str, output_name: str) -> Any:
        return self.data.get(f"{node_id}:{output_name}")

    def read_raw(self, key: str) -> Any:
        return self.data.get(key)

    def find_by_type(self, type_name: str) -> list[Any]:
        results = []
        for value in self.data.values():
            if type(value).__name__ == type_name:
                results.append(value)
        return results

    def find_latest_by_type(self, type_name: str) -> Any:
        results = self.find_by_type(type_name)
        return results[-1] if results else None

    def emit(self, event: str, data: dict) -> None:
        self.message_bus.emit(event, data)

    def on(self, event: str, handler: Callable) -> None:
        self.message_bus.on(event, handler)

    async def drain_messages(self) -> None:
        await self.message_bus.drain()

    def call_tool(self, tool_name: str, params: dict) -> dict:
        from server.tools.registry import tool_registry

        return tool_registry.execute(tool_name, params)

    def _get_legacy(self, name: str) -> Any:
        if name in self._legacy_fields:
            return self._legacy_fields[name]
        if name in self._edge_aliases:
            src_id, src_output = self._edge_aliases[name]
            val = self.read(src_id, src_output)
            if val is not None:
                return val
        type_map = {
            "collected": "CollectedData",
            "media": "MediaData",
            "selected": "SelectedData",
            "scripts": "ScriptsData",
            "audio": "AudioData",
            "aligned": "AlignedData",
            "overlay": "OverlayData",
            "visual": "VisualData",
            "subtitles": "SubtitleData",
            "live2d": "Live2DData",
            "final": "FinalData",
        }
        if name in type_map:
            return self.find_latest_by_type(type_map[name])
        return None

    def _set_legacy(self, name: str, value: Any) -> None:
        self._legacy_fields[name] = value
        self.data[f"_legacy:{name}"] = value

    @property
    def collected(self) -> Optional[CollectedData]:
        return self._get_legacy("collected")

    @collected.setter
    def collected(self, value):
        self._set_legacy("collected", value)

    @property
    def media(self) -> Optional[MediaData]:
        return self._get_legacy("media")

    @media.setter
    def media(self, value):
        self._set_legacy("media", value)

    @property
    def recognized(self) -> Optional[bool]:
        return self._get_legacy("recognized")

    @recognized.setter
    def recognized(self, value):
        self._set_legacy("recognized", value)

    @property
    def transcribed(self) -> Optional[bool]:
        return self._get_legacy("transcribed")

    @transcribed.setter
    def transcribed(self, value):
        self._set_legacy("transcribed", value)

    @property
    def selected(self) -> Optional[SelectedData]:
        return self._get_legacy("selected")

    @selected.setter
    def selected(self, value):
        self._set_legacy("selected", value)

    @property
    def scripts(self) -> Optional[ScriptsData]:
        return self._get_legacy("scripts")

    @scripts.setter
    def scripts(self, value):
        self._set_legacy("scripts", value)

    @property
    def audio(self) -> Optional[AudioData]:
        return self._get_legacy("audio")

    @audio.setter
    def audio(self, value):
        self._set_legacy("audio", value)

    @property
    def aligned(self) -> Optional[AlignedData]:
        return self._get_legacy("aligned")

    @aligned.setter
    def aligned(self, value):
        self._set_legacy("aligned", value)

    @property
    def overlay(self) -> Optional[OverlayData]:
        return self._get_legacy("overlay")

    @overlay.setter
    def overlay(self, value):
        self._set_legacy("overlay", value)

    @property
    def visual(self) -> Optional[VisualData]:
        return self._get_legacy("visual")

    @visual.setter
    def visual(self, value):
        self._set_legacy("visual", value)

    @property
    def subtitles(self) -> Optional[SubtitleData]:
        return self._get_legacy("subtitles")

    @subtitles.setter
    def subtitles(self, value):
        self._set_legacy("subtitles", value)

    @property
    def live2d(self) -> Optional[Live2DData]:
        return self._get_legacy("live2d")

    @live2d.setter
    def live2d(self, value):
        self._set_legacy("live2d", value)

    @property
    def final(self) -> Optional[FinalData]:
        return self._get_legacy("final")

    @final.setter
    def final(self, value):
        self._set_legacy("final", value)
