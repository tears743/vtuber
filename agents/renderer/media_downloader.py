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
    
    def __init__(
        self,
        opencli_binary: str = "opencli",
        timeout: int = 30,
        github_readme_retries: int = 3,
    ):
        self.opencli = opencli_binary
        self.timeout = timeout
        self.github_readme_retries = max(1, int(github_readme_retries))
    
    def download_all(self, collected_dir: Path, media_dir: Path, progress_callback=None) -> dict:
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

        expected_github = self._load_expected_github_repos(collected_dir)
        downloaded_github = set()
        
        # URL 级去重：追踪本次运行中已下载的视频 URL -> 本地路径
        downloaded_video_urls = {}
        # 直链级去重：追踪已使用的 direct_url（防止 kukutool 返回相同直链）
        downloaded_direct_urls = {}
        
        collected_files = sorted(collected_dir.glob("*.json"))
        total_files = len(collected_files)
        if progress_callback:
            progress_callback(f"准备下载 {total_files} 条素材", 0.0)

        for file_index, filepath in enumerate(collected_files, start=1):
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
                        # URL 级去重：同一个视频 URL 只下载一次
                        if video_url in downloaded_video_urls:
                            existing["video"] = {"path": downloaded_video_urls[video_url]}
                            logger.info(f"[downloader] {slug}: 复用已下载视频 (URL 去重)")
                        else:
                            if source == "douyin":
                                local_path = self._download_douyin_video(video_url, item_dir)
                            else:
                                local_path = self._download_video(video_url, item_dir)
                            
                            if local_path:
                                # 直链去重：检查 url_cache 中该视频的 direct_url 是否已被使用
                                cache_file = media_dir / "url_cache.json"
                                is_duplicate = False
                                if source == "douyin" and cache_file.exists():
                                    try:
                                        cache = json.loads(cache_file.read_text(encoding="utf-8"))
                                        direct_url = cache.get(video_url, {}).get("direct_url", "")
                                        if direct_url:
                                            if direct_url in downloaded_direct_urls:
                                                # 直链重复！kukutool 解析出了上一个视频的链接
                                                logger.warning(
                                                    f"[downloader] {slug}: 直链重复！与 {downloaded_direct_urls[direct_url]} 相同，删除"
                                                )
                                                local_path.unlink(missing_ok=True)
                                                is_duplicate = True
                                            else:
                                                downloaded_direct_urls[direct_url] = slug
                                    except Exception:
                                        pass
                                
                                if not is_duplicate:
                                    existing["video"] = {"path": str(local_path)}
                                    downloaded_video_urls[video_url] = str(local_path)
                
                # GitHub Trending 必须逐仓库下载并校验 README。
                if source in ("github_trending", "GitHub Trending"):
                    repo_url = data.get("url", "") or assets.get("readme_url", "")
                    repo_key = self._github_repo_key(repo_url)
                    if repo_key:
                        expected_github.add(repo_key)
                    existing["source"] = "github_trending"
                    existing["source_url"] = repo_url

                    if not self._readme_entry_valid(existing.get("readme")):
                        existing.pop("readme", None)
                        readme_result = self._download_github_readme_with_retries(repo_url, item_dir)
                        if readme_result:
                            existing["readme"] = readme_result
                    if repo_key and self._readme_entry_valid(existing.get("readme")):
                        downloaded_github.add(repo_key)
                
                # 保留 author 信息（用于视频播放时显示 @作者 标签）
                author = data.get("author", "")
                if author:
                    existing["author"] = author
                
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
            finally:
                if progress_callback:
                    progress_callback(
                        f"下载素材 [{file_index}/{total_files}]: {filepath.stem}",
                        file_index / max(total_files, 1),
                    )
        
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

        missing_github = sorted(expected_github - downloaded_github)
        if missing_github:
            logger.warning(
                "[downloader] GitHub Trending 跳过无有效 README 的仓库: %s/%s，跳过: %s",
                len(downloaded_github & expected_github),
                len(expected_github),
                ", ".join(missing_github),
            )
            (media_dir / "github_readme_skipped.json").write_text(
                json.dumps(
                    {
                        "reason": "README missing or unavailable after retries",
                        "repositories": missing_github,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        if expected_github:
            logger.info(
                "[downloader] GitHub Trending README 可用: %s/%s, 跳过: %s",
                len(downloaded_github & expected_github),
                len(expected_github),
                len(missing_github),
            )
        
        return manifest

    def _load_expected_github_repos(self, collected_dir: Path) -> set[str]:
        snapshot_path = collected_dir / ".meta" / "github_trending.json"
        if not snapshot_path.exists():
            return set()
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        repositories = snapshot.get("repositories", []) if isinstance(snapshot, dict) else []
        keys = {
            self._github_repo_key(item.get("url") or item.get("link") or "")
            for item in repositories
            if isinstance(item, dict)
        }
        keys.discard("")
        return keys

    @staticmethod
    def _github_repo_key(repo_url: str) -> str:
        import re

        text = str(repo_url or "").strip()
        marker = "github.com/"
        if marker not in text.lower():
            return ""
        tail = re.split(marker, text, maxsplit=1, flags=re.IGNORECASE)[-1]
        parts = [part for part in tail.split("?")[0].strip("/").split("/") if part]
        if len(parts) < 2:
            return ""
        return "/".join(parts[:2]).removesuffix(".git").lower()

    @staticmethod
    def _readme_entry_valid(entry) -> bool:
        if not isinstance(entry, dict) or not entry.get("path"):
            return False
        path = Path(entry["path"])
        return path.exists() and path.is_file() and path.stat().st_size > 10

    def _download_github_readme_with_retries(self, repo_url: str, item_dir: Path) -> dict | None:
        for attempt in range(1, self.github_readme_retries + 1):
            readme_path = item_dir / "README.md"
            if readme_path.exists() and readme_path.stat().st_size <= 10:
                readme_path.unlink(missing_ok=True)
            result = self._download_github_readme(repo_url, item_dir)
            if self._readme_entry_valid(result):
                return result
            if result and result.get("path"):
                Path(result["path"]).unlink(missing_ok=True)
            logger.warning(
                "[downloader] GitHub README 下载失败 (%s/%s): %s",
                attempt,
                self.github_readme_retries,
                repo_url,
            )
            if attempt < self.github_readme_retries:
                time.sleep(min(2 ** attempt, 5))
        return None
    
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
        抖音视频下载 - kukutool.com (primary) + yt-dlp (fallback)
        
        Strategy:
        1. 通过 kukutool.com 第三方解析服务 + opencli browser 自动化下载
        2. 失败后尝试 yt-dlp 直接下载（作为 fallback）
        """
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
            local_path = item_dir / "video.mp4"
            
            if local_path.exists() and local_path.stat().st_size > 10000:
                return local_path
            
            # URL 格式校验：只接受 /video/数字 格式
            if "/video/" not in url or "/search/" in url or "/hashtag/" in url:
                logger.warning(f"[downloader] 无效 URL 格式（非视频页），跳过: {url[:80]}")
                return None
            
            # 尝试1: kukutool.com 浏览器自动化下载（主要方案，最多重试10次）
            for attempt in range(10):
                logger.info(f"[downloader] 尝试 kukutool 下载 (第{attempt+1}次): {url[:60]}")
                if self._download_via_kukutool(url, local_path):
                    return local_path
                time.sleep(2)
            
            # 尝试2: yt-dlp 直接下载（fallback）
            logger.info(f"[downloader] kukutool 失败，尝试 yt-dlp fallback...")
            result = subprocess.run(
                ["yt-dlp", "-o", str(local_path), "--no-playlist", url],
                capture_output=True, text=True, timeout=120,
            )
            
            if result.returncode == 0 and local_path.exists():
                size_mb = local_path.stat().st_size / (1024 * 1024)
                logger.info(f"[downloader] 抖音视频下载成功 (yt-dlp): {size_mb:.1f}MB")
                return local_path
            
            return None
            
        except Exception as e:
            logger.warning(f"[downloader] 抖音视频下载失败: {url[:60]} - {e}")
            return None
    
    def _download_via_kukutool(self, douyin_url: str, output_path: Path, quality: str = "1080p") -> bool:
        """
        通过 kukutool.com + opencli browser 自动化下载抖音视频
        
        Flow: open kukutool -> close ad -> input URL -> parse -> copy link -> download
        """
        import re
        
        session = "kuku_dl"
        
        def browser_cmd(args: str, timeout: int = 30) -> str:
            cmd = f"opencli browser {session} {args}"
            try:
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=timeout, encoding="utf-8", errors="replace"
                )
                return proc.stdout.strip()
            except Exception:
                return ""
        
        def close_popup(state_text: str):
            # 检测多种广告弹窗模式
            ad_markers = ["aria-label=关闭", "解锁3小时", "广告", "cn.aliyun.com", "打开"]
            if any(marker in state_text for marker in ad_markers):
                for line in state_text.split("\n"):
                    # 优先找 aria-label=关闭
                    if "aria-label=关闭" in line:
                        m = re.search(r'\[(\d+)\]', line)
                        if m:
                            browser_cmd(f"click {m.group(1)}", timeout=10)
                            time.sleep(1)
                            return True
                # 找纯文字"关闭"按钮（如阿里云广告右上角）
                for line in state_text.split("\n"):
                    if "关闭" in line and ("button" in line or "link" in line or "span" in line):
                        m = re.search(r'\[(\d+)\]', line)
                        if m:
                            browser_cmd(f"click {m.group(1)}", timeout=10)
                            time.sleep(1)
                            return True
                # 最后尝试找任何带"关闭"的可点击元素
                for line in state_text.split("\n"):
                    if "关闭" in line and re.search(r'\[(\d+)\]', line):
                        m = re.search(r'\[(\d+)\]', line)
                        if m:
                            browser_cmd(f"click {m.group(1)}", timeout=10)
                            time.sleep(1)
                            return True
            return False
        
        def find_idx(state_text: str, pattern: str) -> str | None:
            for line in state_text.split("\n"):
                if pattern in line:
                    m = re.search(r'\[(\d+)\]', line)
                    if m:
                        return m.group(1)
            return None
        
        try:
            # Open kukutool
            browser_cmd('open "https://dy.kukutool.com/"', timeout=30)
            time.sleep(3)
            # Activate Chrome to foreground (ads don't render properly in background)
            activate_script = Path(__file__).resolve().parent.parent.parent / "scripts" / "activate_chrome.ps1"
            subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(activate_script)],
                capture_output=True, timeout=5
            )
            time.sleep(2)
            
            # Get state & close popup (可能出现"解锁3小时"弹窗)
            state = browser_cmd("state", timeout=20)
            # 多次尝试关闭弹窗（有时需要关闭多层）
            for _ in range(3):
                if "解锁3小时" in state or "aria-label=关闭" in state or "广告" in state:
                    close_popup(state)
                    time.sleep(2)
                    state = browser_cmd("state", timeout=20)
                else:
                    break
            
            # Find input & clear
            input_idx = find_idx(state, "input type=text") or find_idx(state, "placeholder=粘贴")
            if not input_idx:
                logger.warning("[kukutool] Cannot find input box")
                browser_cmd("close", timeout=5)
                return False
            
            clear_idx = find_idx(state, "清除内容")
            if clear_idx:
                browser_cmd(f"click {clear_idx}", timeout=5)
                time.sleep(0.5)
            
            # Type URL
            browser_cmd(f'type {input_idx} "{douyin_url}"', timeout=15)
            
            # Click parse (may trigger ad popup, retry up to 3 times)
            for parse_try in range(3):
                state = browser_cmd("state", timeout=20)
                parse_idx = find_idx(state, "开始解析")
                if not parse_idx:
                    browser_cmd("close", timeout=5)
                    return False
                
                browser_cmd(f"click {parse_idx}", timeout=15)
                time.sleep(4)
                
                # Check if ad popup appeared after clicking parse
                state = browser_cmd("state", timeout=20)
                if "解锁3小时" in state or "aria-label=关闭" in state or "广告" in state:
                    close_popup(state)
                    time.sleep(3)
                    continue  # Re-click parse after closing ad
                break
            
            # Wait for results (增加等待时间到 10 轮 x 5 秒 = 50 秒)
            video_direct_url = None
            # 清晰度优先级: 1080p > 720p > 540p > 超高清（超高清文件太大容易超时）
            quality_options = ["1080p", "720p", "540p", "超高清"]
            matched_quality = None
            for attempt in range(10):
                time.sleep(5)
                state = browser_cmd("state", timeout=20)
                close_popup(state)
                
                # 按优先级匹配可用的清晰度
                for q in quality_options:
                    if q in state:
                        matched_quality = q
                        break
                
                if matched_quality:
                    logger.info(f"[kukutool] 解析成功，找到 {matched_quality} 选项 (第{attempt+1}轮)")
                    # Try to copy link (may trigger ad on first attempt)
                    for copy_try in range(3):
                        # Re-get state each try (DOM indices change after popup close)
                        if copy_try > 0:
                            state = browser_cmd("state", timeout=20)
                            close_popup(state)
                            time.sleep(1)
                            state = browser_cmd("state", timeout=20)
                        
                        lines = state.split("\n")
                        found_quality = False
                        copy_idx = None
                        for line in lines:
                            if matched_quality in line and "下载" not in line:
                                found_quality = True
                            # 新页面: title=复制链接 的按钮，文字是"复制"
                            if found_quality and ("复制链接" in line or ("复制" in line and "button" in line and "批量" not in line and "所有" not in line)):
                                m = re.search(r'\[(\d+)\]', line)
                                if m:
                                    copy_idx = m.group(1)
                                break
                        
                        # 备选: 直接找 "复制无水印链接" 按钮
                        if not copy_idx:
                            for line in lines:
                                if "复制无水印链接" in line:
                                    m = re.search(r'\[(\d+)\]', line)
                                    if m:
                                        copy_idx = m.group(1)
                                    break
                        
                        if not copy_idx:
                            break
                        
                        # 清空剪贴板（防止读到上一次的直链）
                        subprocess.run(
                            ["powershell", "-Command", "Set-Clipboard -Value ''"],
                            capture_output=True, timeout=5,
                        )
                        
                        browser_cmd(f"click {copy_idx}", timeout=10)
                        time.sleep(2)
                        
                        # Check if ad popup appeared
                        post_state = browser_cmd("state", timeout=15)
                        if "解锁3小时" in post_state or "aria-label=关闭" in post_state:
                            close_popup(post_state)
                            time.sleep(1)
                            continue  # Retry copy after closing ad
                        
                        # Read clipboard
                        clip = subprocess.run(
                            ["powershell", "-Command", "Get-Clipboard"],
                            capture_output=True, text=True, timeout=5,
                            encoding="utf-8", errors="replace"
                        ).stdout.strip()
                        # 验证：必须是 http 开头、非抖音页面 URL、且非空（剪贴板确实更新了）
                        if clip and clip.startswith("http") and "douyin.com/video" not in clip:
                            video_direct_url = clip
                            break
                    
                    if video_direct_url:
                        break
                else:
                    # 解析结果还没出来，检查是否有验证码或错误提示
                    if "验证码" in state or "recaptcha" in state.lower():
                        logger.warning(f"[kukutool] 等待中 (第{attempt+1}轮): 检测到验证码")
                    elif "请输入正确" in state or "链接有误" in state:
                        logger.warning(f"[kukutool] 链接可能无效")
                        break
            
            browser_cmd("close", timeout=5)
            
            if not video_direct_url:
                logger.warning("[kukutool] Failed to get video direct URL")
                return False
            
            # Download
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.douyin.com/",
            }
            parsed = urlparse(video_direct_url)
            max_download_seconds = 120
            started_at = time.monotonic()
            logger.info(
                "[kukutool] 开始下载直链: host=%s path=%s timeout=%ss",
                parsed.netloc,
                parsed.path[:80],
                max_download_seconds,
            )
            r = requests.get(video_direct_url, headers=headers, stream=True, timeout=(10, 30))
            r.raise_for_status()
            content_length = r.headers.get("content-length", "")
            content_type = r.headers.get("content-type", "")
            logger.info(
                "[kukutool] 直链响应: status=%s content_length=%s content_type=%s",
                r.status_code,
                content_length or "?",
                content_type or "?",
            )
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            last_log_at = started_at
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    now = time.monotonic()
                    if now - started_at > max_download_seconds:
                        raise TimeoutError(
                            f"download exceeded {max_download_seconds}s, downloaded={downloaded / (1024 * 1024):.1f}MB"
                        )
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                    if now - last_log_at >= 10:
                        logger.info(
                            "[kukutool] 下载中: %.1fMB elapsed=%.1fs",
                            downloaded / (1024 * 1024),
                            now - started_at,
                        )
                        last_log_at = now
            
            size_mb = output_path.stat().st_size / (1024 * 1024)
            if size_mb < 0.1:
                output_path.unlink(missing_ok=True)
                return False
            
            logger.info(f"[kukutool] 下载成功: {size_mb:.1f}MB")
            
            # 记录直链到本地缓存，方便后续重新下载
            self._save_direct_url_cache(douyin_url, video_direct_url, output_path)
            
            return True
            
        except Exception as e:
            elapsed = None
            try:
                elapsed = time.monotonic() - started_at
            except Exception:
                pass
            extra = f" elapsed={elapsed:.1f}s" if elapsed is not None else ""
            if "downloaded" in locals():
                extra += f" downloaded={downloaded / (1024 * 1024):.1f}MB"
            logger.warning(f"[kukutool] Error:{extra} {e}")
            output_path.unlink(missing_ok=True)
            browser_cmd("close", timeout=5)
            return False
    
    def _save_direct_url_cache(self, douyin_url: str, direct_url: str, output_path: Path):
        """记录抖音URL与解析直链的映射，方便后续重新下载"""
        import json
        cache_file = output_path.parent.parent / "url_cache.json"
        try:
            cache = {}
            if cache_file.exists():
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            cache[douyin_url] = {
                "direct_url": direct_url,
                "output": str(output_path),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[kukutool] cache write error: {e}")
    
    def _get_douyin_cookies(self, video_url: str) -> Path | None:
        """通过 browser 工具访问抖音获取 cookies，导出为 Netscape 格式"""
        import ast
        
        cookies_path = Path(__file__).resolve().parent.parent.parent / "douyin_cookies.txt"
        
        # 如果 cookies 文件存在且不到 10 分钟前生成，直接复用
        if cookies_path.exists():
            import time
            age = time.time() - cookies_path.stat().st_mtime
            if age < 600:
                return cookies_path
        
        try:
            # 打开抖音视频页获取完整 cookies
            subprocess.run(
                ["browser", "--session", "dy_cookies", "open", video_url],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            
            import time
            time.sleep(5)
            
            # 获取 cookies
            result = subprocess.run(
                ["browser", "--session", "dy_cookies", "cookies", "get"],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
            
            # 关闭 session
            subprocess.run(
                ["browser", "--session", "dy_cookies", "close"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            
            output = result.stdout.strip()
            if "cookies:" not in output:
                logger.warning("[downloader] browser cookies 获取失败")
                return None
            
            raw = output.split("cookies:", 1)[1].strip()
            try:
                cookies = ast.literal_eval(raw)
            except Exception:
                import json
                cookies = json.loads(raw)
            
            # 转换为 Netscape 格式
            lines = ["# Netscape HTTP Cookie File", ""]
            for c in cookies:
                domain = c.get("domain", "")
                if "douyin" not in domain:
                    continue
                inc_sub = "TRUE" if domain.startswith(".") else "FALSE"
                secure = "TRUE" if c.get("secure") else "FALSE"
                expires = str(int(c.get("expires", 0)))
                name = c.get("name", "")
                value = c.get("value", "")
                path = c.get("path", "/")
                lines.append(f"{domain}\t{inc_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
            
            if len(lines) <= 2:
                logger.warning("[downloader] 未获取到有效的抖音 cookies")
                return None
            
            cookies_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            logger.info(f"[downloader] 抖音 cookies 已生成: {len(lines) - 2} 条")
            return cookies_path
            
        except Exception as e:
            logger.warning(f"[downloader] browser cookies 获取异常: {e}")
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
            
            # 跳过 SVG URL（通常以 .svg 结尾）
            if url.lower().endswith(".svg"):
                continue
            
            # 跳过 GIF（ffmpeg 合成不支持）
            if url.lower().endswith(".gif"):
                continue
            
            local_path = self._download_image(url, img_dir, f"readme_img_{i:02d}")
            if local_path:
                # 校验真实文件格式（有些 .jpg 实际是 SVG）
                try:
                    with open(local_path, "rb") as f:
                        header = f.read(256)
                    # SVG 检测：文件头包含 <svg 或 <?xml
                    if b"<svg" in header or (b"<?xml" in header and b"<svg" in open(local_path, "rb").read(2048)):
                        Path(local_path).unlink(missing_ok=True)
                        continue
                    # GIF 检测
                    if header[:3] == b"GIF":
                        Path(local_path).unlink(missing_ok=True)
                        continue
                except Exception:
                    pass
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
