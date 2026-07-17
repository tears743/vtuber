"""
Download 节点 — 素材下载

对应: run_render.py → step_download() → MediaDownloader.download_all()
"""
import json
import logging
from pathlib import Path

from server.nodes.base import BaseNode
from server.nodes.registry import register
from server.models import PipelineContext, MediaData

logger = logging.getLogger(__name__)


@register
class DownloadNode(BaseNode):
    type = "download"
    label = "素材下载"
    category = "数据采集"
    reads = ["collected"]
    writes = ["media"]
    output_dirs = ["media"]
    config_schema = {
        "max_retries": {
            "type": "int", "label": "下载重试次数",
            "default": 10, "min": 1, "max": 20,
            "description": "kukutool 下载失败后的最大重试次数"
        },
        "github_readme_retries": {
            "type": "int", "label": "GitHub README 重试次数",
            "default": 3, "min": 1, "max": 10,
            "description": "每个 GitHub Trending 仓库 README 下载失败后的重试次数"
        },
        "opencli_binary": {
            "type": "str", "label": "OpenCLI 路径",
            "default": "node D:/workspace/opencli/dist/src/main.js"
        },
        "skip_invalid_urls": {
            "type": "bool", "label": "跳过无效URL",
            "default": True,
            "description": "自动跳过非 /video/数字 格式的抖音 URL"
        },
    }

    async def execute(self, ctx: PipelineContext, on_progress):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from agents.renderer.media_downloader import MediaDownloader

        on_progress("初始化下载器...", 0.0)

        config = ctx.config
        collected_dir = ctx.collected.dir
        media_dir = ctx.data_root / ctx.date / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        opencli = self.get_config("opencli_binary", config.get("opencli", {}).get("binary", "opencli"))

        downloader = MediaDownloader(
            opencli_binary=opencli,
            github_readme_retries=self.get_config("github_readme_retries", 3),
        )

        on_progress("下载素材中...", 0.1)
        import asyncio
        def report_download(message, progress):
            on_progress(message, 0.1 + 0.8 * progress)

        manifest = await asyncio.to_thread(
            downloader.download_all,
            collected_dir,
            media_dir,
            report_download,
        )
        on_progress("下载完成", 0.9)

        # 统计
        total_images = sum(len(v.get("images", [])) for v in manifest.values())
        total_videos = sum(1 for v in manifest.values() if v.get("video"))
        total_readmes = sum(1 for v in manifest.values() if v.get("readme"))

        ctx.media = MediaData(
            dir=media_dir,
            manifest_path=media_dir / "manifest.json",
            manifest=manifest,
            total_items=len(manifest),
            total_images=total_images,
            total_videos=total_videos,
            total_readmes=total_readmes,
        )
        on_progress(
            f"下载完成: {len(manifest)} 条素材, {total_images} 图片, "
            f"{total_videos} 视频, {total_readmes} README",
            1.0,
        )

    def restore_cache(self, ctx):
        """从磁盘恢复 media 数据，并修补 manifest 中的缺失条目"""
        import json
        from pathlib import Path
        media_dir = ctx.data_root / ctx.date / "media"
        manifest_path = media_dir / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        
        # 修补：扫描磁盘上的 media 子目录，补全 manifest 中缺失的 images/video
        patched = False
        for item_dir in media_dir.iterdir():
            if not item_dir.is_dir():
                continue
            # 推导 source_file key: slug + .json
            source_key = item_dir.name + ".json"
            entry = manifest.get(source_key, {})
            
            # 只在 images 为空（未记录）时补全，不覆盖已有识别结果
            has_recorded_images = bool(entry.get("images"))
            if not has_recorded_images:
                disk_imgs = sorted(item_dir.glob("img_*.*"))
                if disk_imgs:
                    entry.setdefault("images", [])
                    for img_file in disk_imgs:
                        entry["images"].append(str(img_file))
                    patched = True
            
            # 只在 video 为空时补全
            has_recorded_video = bool(entry.get("video"))
            if not has_recorded_video:
                vid_files = list(item_dir.glob("video.*"))
                if vid_files:
                    entry["video"] = {"path": str(vid_files[0])}
                    patched = True
            
            if entry.get("images") or entry.get("video") or entry.get("readme"):
                manifest[source_key] = entry
        
        # 如果有修补，写回 manifest
        if patched:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"[download] manifest 已修补（磁盘文件补全）")
        
        total_images = sum(len(v.get("images", [])) for v in manifest.values())
        total_videos = sum(1 for v in manifest.values() if v.get("video"))
        total_readmes = sum(1 for v in manifest.values() if v.get("readme"))
        ctx.media = MediaData(
            dir=media_dir,
            manifest_path=manifest_path,
            manifest=manifest,
            total_items=len(manifest),
            total_images=total_images,
            total_videos=total_videos,
            total_readmes=total_readmes,
        )
