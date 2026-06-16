"""
Step 0: Media Downloader - 素材下载 + 识别

在 Director 脚本生成之前执行：
1. 扫描 collected/ 中所有 visual_assets
2. 下载图片/视频到 media/ 目录
3. 抖音视频: 通过浏览器打开 URL 后用 yt-dlp 提取
4. 输出 manifest.json 供 Director 引用真实本地路径
"""
import json
import logging
import subprocess
import time
import requests
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class MediaDownloader:
    """素材下载器"""
    
    def __init__(self, opencli_binary: str = "opencli", timeout: int = 30):
        self.opencli = opencli_binary
        self.timeout = timeout
    
    def download_all(self, collected_dir: Path, media_dir: Path) -> dict:
        """
        扫描 collected/ 中所有文件的 visual_assets，下载到 media/
        增量更新：保留已有的 description/transcript 等字段
        
        Returns:
            manifest: {source_filename: {"images": [...], "video": ...}}
        """
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载已有 manifest，保留之前的识别结果
        manifest_path = media_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {}
        
        for filepath in sorted(collected_dir.glob("*.json")):
            try:
                data = self._load_json(filepath)
                if not data:
                    continue
                
                assets = data.get("visual_assets", {})
                source = data.get("source", "unknown")
                slug = filepath.stem  # e.g. 2026-06-12_douyin_topic_xxx
                
                item_dir = media_dir / slug
                
                # 获取已有条目（保留 description/transcript 等）
                existing = manifest.get(filepath.name, {"images": [], "video": None})
                
                # 下载图片（只下载缺失的）
                images = assets.get("images", [])
                existing_paths = set()
                if existing.get("images"):
                    for img in existing["images"]:
                        if isinstance(img, dict):
                            existing_paths.add(img.get("path", ""))
                        elif isinstance(img, str):
                            existing_paths.add(img)
                
                for i, img_url in enumerate(images):
                    if not img_url or not img_url.startswith("http"):
                        continue
                    local_path = self._download_image(img_url, item_dir, f"img_{i:02d}")
                    if local_path:
                        path_str = str(local_path)
                        # 检查是否已存在（避免重复添加）
                        if path_str not in existing_paths:
                            existing.setdefault("images", []).append(path_str)
                
                # 下载视频（只在没有视频时下载）
                has_video = False
                if isinstance(existing.get("video"), dict) and existing["video"].get("path"):
                    has_video = Path(existing["video"]["path"]).exists()
                elif isinstance(existing.get("video"), str) and existing["video"]:
                    has_video = Path(existing["video"]).exists()
                
                if not has_video:
                    video_url = assets.get("video_url", "")
                    
                    if not video_url and source == "douyin":
                        video_url = data.get("url", "")
                    
                    if video_url and video_url.startswith("http"):
                        if source == "douyin":
                            local_path = self._download_douyin_video(video_url, item_dir)
                        else:
                            local_path = self._download_video(video_url, item_dir)
                        
                        if local_path:
                            existing["video"] = {"path": str(local_path)}
                
                # GitHub README 下载
                if source in ("github_trending", "GitHub Trending") and not existing.get("readme"):
                    repo_url = data.get("url", "") or assets.get("readme_url", "")
                    readme_result = self._download_github_readme(repo_url, item_dir)
                    if readme_result:
                        existing["readme"] = readme_result
                
                if existing.get("images") or existing.get("video") or existing.get("readme"):
                    manifest[filepath.name] = existing
                    logger.info(
                        f"[downloader] {slug}: "
                        f"{len(existing.get('images', []))} images, "
                        f"{'1 video' if existing.get('video') else 'no video'}, "
                        f"{'README' if existing.get('readme') else ''}"
                    )
                    
            except Exception as e:
                logger.warning(f"[downloader] 处理失败 {filepath.name}: {e}")
        
        # 保存 manifest
        manifest_path = media_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        total_images = sum(len(v.get("images", [])) for v in manifest.values())
        total_videos = sum(1 for v in manifest.values() if v.get("video"))
        total_readmes = sum(1 for v in manifest.values() if v.get("readme"))
        logger.info(
            f"[downloader] 完成: {len(manifest)} 条素材, "
            f"{total_images} 图片, {total_videos} 视频, {total_readmes} README"
        )
        
        return manifest
    
    def _download_image(self, url: str, item_dir: Path, name: str) -> Path | None:
        """下载单张图片"""
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
            
            # 确定扩展名
            parsed = urlparse(url)
            ext = Path(parsed.path).suffix or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".jpg"
            
            local_path = item_dir / f"{name}{ext}"
            
            if local_path.exists():
                return local_path
            
            resp = requests.get(url, timeout=self.timeout, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            })
            resp.raise_for_status()
            
            with open(local_path, "wb") as f:
                f.write(resp.content)
            
            return local_path
            
        except Exception as e:
            logger.debug(f"[downloader] 图片下载失败: {url[:60]} - {e}")
            return None
    
    def _download_video(self, url: str, item_dir: Path) -> Path | None:
        """下载普通视频（非抖音）"""
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
            local_path = item_dir / "video.mp4"
            
            if local_path.exists():
                return local_path
            
            # 尝试 yt-dlp
            result = subprocess.run(
                ["yt-dlp", "-o", str(local_path), "--no-playlist", url],
                capture_output=True, text=True, timeout=60,
            )
            
            if result.returncode == 0 and local_path.exists():
                return local_path
            
            # fallback: 直接下载
            resp = requests.get(url, timeout=self.timeout, stream=True, headers={
                "User-Agent": "Mozilla/5.0"
            })
            resp.raise_for_status()
            
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return local_path if local_path.stat().st_size > 1000 else None
            
        except Exception as e:
            logger.debug(f"[downloader] 视频下载失败: {url[:60]} - {e}")
            return None
    
    def _download_douyin_video(self, url: str, item_dir: Path) -> Path | None:
        """
        抖音视频下载 - yt-dlp 直接支持抖音 URL
        
        不需要浏览器，不需要 cookie，yt-dlp 内置了抖音解析器
        """
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
            local_path = item_dir / "video.mp4"
            
            if local_path.exists():
                return local_path
            
            result = subprocess.run(
                ["yt-dlp", "-o", str(local_path), "--no-playlist", url],
                capture_output=True, text=True, timeout=120,
            )
            
            if result.returncode == 0 and local_path.exists():
                size_mb = local_path.stat().st_size / (1024 * 1024)
                logger.info(f"[downloader] 抖音视频下载成功: {size_mb:.1f}MB")
                return local_path
            
            logger.debug(f"[downloader] 抖音视频 yt-dlp 失败: {result.stderr[:200]}")
            return None
            
        except Exception as e:
            logger.debug(f"[downloader] 抖音视频下载失败: {url[:60]} - {e}")
            return None
    
    def _run_opencli(self, command: str) -> str:
        """执行 opencli 命令"""
        full_cmd = f"{self.opencli} {command}"
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        return result.stdout.strip()
    
    def _download_github_readme(self, repo_url: str, item_dir: Path) -> dict | None:
        """
        下载 GitHub 仓库的 README.md 全文 + 内嵌图片/视频
        
        Args:
            repo_url: e.g. https://github.com/owner/repo
            item_dir: 本地保存目录
            
        Returns:
            {"path": "README.md path", "images": ["img paths..."]} or None
        """
        import re
        
        if not repo_url or "github.com" not in repo_url:
            return None
        
        try:
            # 解析 owner/repo
            parts = repo_url.rstrip("/").split("github.com/")
            if len(parts) < 2:
                return None
            repo_path = parts[1]  # e.g. "owner/repo"
            
            # 下载 README.md（尝试多种文件名）
            item_dir.mkdir(parents=True, exist_ok=True)
            readme_local = item_dir / "README.md"
            
            if not readme_local.exists():
                readme_content = None
                for readme_name in ["README.md", "readme.md", "Readme.md", "README.rst", "README"]:
                    raw_url = f"https://raw.githubusercontent.com/{repo_path}/HEAD/{readme_name}"
                    try:
                        resp = requests.get(raw_url, timeout=15, headers={
                            "User-Agent": "Mozilla/5.0"
                        })
                        if resp.status_code == 200 and len(resp.text) > 10:
                            readme_content = resp.text
                            break
                    except Exception:
                        continue
                
                if not readme_content:
                    logger.debug(f"[downloader] GitHub README 未找到: {repo_url}")
                    return None
                
                with open(readme_local, "w", encoding="utf-8") as f:
                    f.write(readme_content)
            else:
                with open(readme_local, "r", encoding="utf-8") as f:
                    readme_content = f.read()
            
            # 提取并下载 README 中的图片
            images = self._download_readme_images(readme_content, repo_path, item_dir)
            
            result = {
                "path": str(readme_local),
                "size_chars": len(readme_content),
            }
            if images:
                result["images"] = images
            
            logger.info(f"[downloader] GitHub README: {repo_path} ({len(readme_content)} chars, {len(images)} images)")
            return result
            
        except Exception as e:
            logger.debug(f"[downloader] GitHub README 下载失败: {repo_url} - {e}")
            return None
    
    def _download_readme_images(self, readme_content: str, repo_path: str, item_dir: Path) -> list[str]:
        """
        从 README.md 内容中提取图片 URL 并下载
        
        支持格式：
        - ![alt](url)
        - <img src="url">
        """
        import re
        
        images = []
        img_dir = item_dir / "readme_images"
        
        # Markdown 图片: ![alt](url)
        md_images = re.findall(r'!\[.*?\]\((.+?)\)', readme_content)
        # HTML 图片: <img src="url">
        html_images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', readme_content)
        
        all_urls = list(dict.fromkeys(md_images + html_images))  # 去重保序
        
        # 最多下载 10 张
        for i, url in enumerate(all_urls[:10]):
            # 处理相对路径
            if url.startswith("./") or (not url.startswith("http") and not url.startswith("//")):
                url = f"https://raw.githubusercontent.com/{repo_path}/HEAD/{url.lstrip('./')}"
            elif url.startswith("//"):
                url = f"https:{url}"
            
            if not url.startswith("http"):
                continue
            
            # 跳过 badge/shield 图片（太小没意义）
            if "shields.io" in url or "badge" in url.lower() or "img.shields" in url:
                continue
            
            local_path = self._download_image(url, img_dir, f"readme_img_{i:02d}")
            if local_path:
                images.append(str(local_path))
        
        return images
    
    def _load_json(self, filepath: Path) -> dict | None:
        """加载 JSON（处理双重编码）"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = f.read()
            if raw.startswith('"'):
                raw = json.loads(raw)
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
