"""
Collector Orchestrator - Agent Teams Architecture

Orchestrator (DeepSeek V4-flash) handles:
1. Fetching hot lists from all platforms
2. Selecting high-value topics
3. Dispatching topics to Workers (local model, concurrent)
4. Aggregating results
"""
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from agents.collector.worker import PlatformWorker

logger = logging.getLogger(__name__)


class CollectorOrchestrator:
    """
    Orchestrator Agent - coordinates parallel platform Workers.
    
    Uses DeepSeek V4-flash for task planning,
    dispatches PlatformWorkers (local model) for execution.
    """
    
    def __init__(
        self,
        # Orchestrator model (DeepSeek V4-flash)
        orchestrator_base_url: str,
        orchestrator_api_key: str,
        orchestrator_model: str,
        # Worker model (local LM Studio)
        worker_base_url: str,
        worker_api_key: str,
        worker_model: str,
        # Shared config
        opencli_binary: str,
        data_dir: Path,
        max_workers: int = 4,
        enabled_platforms: list[str] | None = None,
        collection_mode: str = "ai_tech",
        planning_prompt: str = "",
        progress_callback=None,
    ):
        self.client = OpenAI(base_url=orchestrator_base_url, api_key=orchestrator_api_key)
        self.model = orchestrator_model
        
        self.worker_base_url = worker_base_url
        self.worker_api_key = worker_api_key
        self.worker_model = worker_model
        
        self.opencli_binary = opencli_binary
        self.collection_mode = self._normalize_mode(collection_mode)
        self.data_dir = data_dir
        self.max_workers = max_workers
        self.enabled_platforms = tuple(
            self._effective_platforms(enabled_platforms or ["weibo", "douyin", "github", "huggingface"])
        )
        self.planning_prompt = planning_prompt or ""
        self.progress_callback = progress_callback
        
        # Ensure output dir exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _report_progress(self, message: str, progress: float) -> None:
        if self.progress_callback:
            self.progress_callback(message, min(1.0, max(0.0, float(progress))))

    def _normalize_mode(self, mode: str) -> str:
        mode = str(mode or "ai_tech").strip().lower()
        aliases = {
            "ai": "ai_tech",
            "tech": "ai_tech",
            "ai科技": "ai_tech",
            "ai 科技": "ai_tech",
            "hot": "daily_hot",
            "daily": "daily_hot",
            "今日热搜": "daily_hot",
            "热搜": "daily_hot",
            "all": "mixed",
            "混合": "mixed",
        }
        mode = aliases.get(mode, mode)
        return mode if mode in {"ai_tech", "daily_hot", "mixed"} else "ai_tech"

    def _effective_platforms(self, platforms: list[str]) -> list[str]:
        mode_defaults = {
            "ai_tech": ["github", "huggingface"],
            "daily_hot": ["weibo", "douyin"],
            "mixed": ["weibo", "douyin", "github", "huggingface"],
        }[self.collection_mode]
        selected = []
        for platform in platforms:
            name = str(platform).strip().lower()
            if name in {"weibo", "douyin", "github", "huggingface"} and name not in selected:
                selected.append(name)
        effective = [platform for platform in selected if platform in mode_defaults]
        return effective or mode_defaults

    def _empty_plan(self) -> dict:
        return {platform: [] for platform in self.enabled_platforms}

    def _filter_plan(self, plan: dict) -> dict:
        filtered = self._empty_plan()
        for platform in self.enabled_platforms:
            topics = plan.get(platform, [])
            filtered[platform] = topics if isinstance(topics, list) else []
        return filtered
    
    def run(self) -> dict:
        """
        Full orchestration flow:
        1. Fetch hot lists (quick, serial)
        2. Ask Orchestrator LLM to select & assign topics
        3. Dispatch Workers concurrently
        4. Aggregate results
        """
        logger.info("=" * 60)
        logger.info("[orchestrator] Starting Agent Teams collection")
        logger.info(f"[orchestrator] Mode: {self.collection_mode}; platforms: {list(self.enabled_platforms)}")
        logger.info("=" * 60)
        
        # Phase 1: Fetch raw hot lists
        self._report_progress("获取各平台榜单...", 0.05)
        raw_data = self._fetch_hot_lists()
        self._save_github_trending_snapshot(raw_data.get("github") or [])
        
        # Phase 2: Use Orchestrator LLM to plan tasks
        self._report_progress("LLM 规划采集任务...", 0.3)
        task_plan = self._plan_tasks(raw_data)
        
        # Phase 2.5: Dedup - remove already collected topics
        self._report_progress("去重并准备采集任务...", 0.45)
        task_plan = self._dedup_tasks(task_plan)
        
        # Phase 3: Dispatch Workers concurrently
        self._report_progress("并发执行平台采集...", 0.5)
        results = self._dispatch_workers(task_plan)
        self._report_progress("校验采集完整性...", 0.9)
        self._ensure_github_collected(raw_data.get("github") or [], results)
        
        # Phase 4: Summary
        total_files = sum(len(r["files_saved"]) for r in results.values())
        total_items = sum(r["total_items"] for r in results.values())
        total_errors = sum(len(r["errors"]) for r in results.values())
        
        logger.info("=" * 60)
        self._report_progress(f"采集完成: {total_items} 条", 1.0)
        logger.info(f"[orchestrator] DONE")
        logger.info(f"  Workers: {len(results)}")
        logger.info(f"  Files: {total_files}")
        logger.info(f"  Items: {total_items}")
        if total_errors:
            logger.warning(f"  Errors: {total_errors}")
        logger.info("=" * 60)
        
        return {
            "workers": len(results),
            "files_saved": total_files,
            "total_items": total_items,
            "errors": total_errors,
            "per_worker": results,
        }

    def _save_github_trending_snapshot(self, repositories: list[dict]) -> None:
        if "github" not in self.enabled_platforms:
            return
        meta_dir = self.data_dir / ".meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "repositories": [item for item in repositories if isinstance(item, dict)],
        }
        (meta_dir / "github_trending.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_github_collected(self, repositories: list[dict], results: dict) -> None:
        """Create deterministic records for Trending repos skipped by the LLM worker."""
        if "github" not in self.enabled_platforms or not repositories:
            return

        collected_keys = set()
        for path in self.data_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            key = self._github_repo_key(data.get("url") or "")
            if key:
                collected_keys.add(key)

        github_result = results.setdefault(
            "github",
            {"files_saved": [], "total_items": 0, "errors": [], "topics_done": []},
        )
        added = 0
        for repository in repositories:
            if not isinstance(repository, dict):
                continue
            repo_url = str(repository.get("url") or repository.get("link") or "").strip()
            repo_key = self._github_repo_key(repo_url)
            if not repo_key or repo_key in collected_keys:
                continue

            title = str(repository.get("title") or repository.get("name") or repo_key)
            filename_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", repo_key.replace("/", "_"))
            path = self.data_dir / f"{datetime.now():%Y-%m-%d}_github_{filename_slug}.json"
            data = {
                "title": title,
                "source": "github_trending",
                "url": repo_url,
                "content": f"GitHub Trending repository: {title}. Full README is downloaded in the media stage.",
                "visual_assets": {"readme_url": repo_url},
                "key_points": [],
                "media_type": "tech_news",
                "technical_details": {},
                "meta": {"collection_fallback": True},
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            github_result["files_saved"].append(str(path))
            github_result["total_items"] += 1
            github_result["topics_done"].append({"title": title, "file": path.name})
            collected_keys.add(repo_key)
            added += 1

        expected_keys = {
            self._github_repo_key(item.get("url") or item.get("link") or "")
            for item in repositories
            if isinstance(item, dict)
        }
        expected_keys.discard("")
        missing = sorted(expected_keys - collected_keys)
        if missing:
            raise RuntimeError("GitHub Trending 采集记录不完整: " + ", ".join(missing))
        if added:
            logger.warning("[orchestrator] GitHub worker 遗漏 %s 条，已补建下载记录", added)
        logger.info("[orchestrator] GitHub collection complete: %s/%s", len(collected_keys & expected_keys), len(expected_keys))

    @staticmethod
    def _github_repo_key(repo_url: str) -> str:
        marker = "github.com/"
        text = str(repo_url or "").strip()
        if marker not in text.lower():
            return ""
        tail = re.split(marker, text, maxsplit=1, flags=re.IGNORECASE)[-1]
        parts = [part for part in tail.split("?")[0].strip("/").split("/") if part]
        if len(parts) < 2:
            return ""
        return "/".join(parts[:2]).removesuffix(".git").lower()
    
    # --- Phase 1: Fetch hot lists ---
    
    def _fetch_hot_lists(self) -> dict:
        """Fetch hot lists from all platforms (quick serial calls)."""
        import subprocess
        
        logger.info("[orchestrator] Phase 1: Fetching hot lists...")
        
        results = {}
        commands = {
            "weibo": "weibo hot -f json --limit 50",
            "douyin": "douyin hashtag hot -f json --limit 30",
            "hf_papers": "hf top -f json --limit 20",
            "hf_spaces": "hf spaces -f json --limit 10",
        }

        enabled_sources = set()
        if "weibo" in self.enabled_platforms:
            enabled_sources.add("weibo")
        if "douyin" in self.enabled_platforms:
            enabled_sources.add("douyin")
        if "huggingface" in self.enabled_platforms:
            enabled_sources.update({"hf_papers", "hf_spaces"})
        
        for name, cmd in commands.items():
            if name not in enabled_sources:
                continue
            full_cmd = f"{self.opencli_binary} {cmd}"
            try:
                proc = subprocess.run(
                    full_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    encoding="utf-8",
                    errors="replace",
                )
                if proc.returncode == 0:
                    try:
                        data = json.loads(proc.stdout.strip())
                        results[name] = data if isinstance(data, list) else [data]
                        logger.info(f"[orchestrator] {name}: {len(results[name])} items")
                    except json.JSONDecodeError:
                        results[name] = []
                        logger.warning(f"[orchestrator] {name}: JSON parse failed")
                else:
                    results[name] = []
                    logger.warning(f"[orchestrator] {name}: exit={proc.returncode}")
            except Exception as e:
                results[name] = []
                logger.error(f"[orchestrator] {name}: {e}")
        
        # GitHub Trending via browser (全量)
        if "github" in self.enabled_platforms:
            results["github"] = []
            for attempt in range(1, 4):
                try:
                    full_cmd = f"{self.opencli_binary} browser gh_orch open https://github.com/trending"
                    subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                  encoding="utf-8", errors="replace")
                    time.sleep(2)

                    full_cmd = f'{self.opencli_binary} browser gh_orch eval "Array.from(document.querySelectorAll(\'article h2 a\')).map(a => ({{title: a.textContent.trim(), url: \'https://github.com\' + a.getAttribute(\'href\')}}))"'
                    proc = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                         encoding="utf-8", errors="replace")
                    if proc.returncode != 0:
                        raise RuntimeError(f"browser eval exit={proc.returncode}: {proc.stderr[:200]}")
                    try:
                        data = json.loads(proc.stdout.strip())
                        results["github"] = data if isinstance(data, list) else []
                    except json.JSONDecodeError:
                        raise RuntimeError("browser eval 返回的不是合法 JSON")
                    if results["github"]:
                        logger.info(f"[orchestrator] github: {len(results['github'])} repos")
                        break
                    raise RuntimeError("榜单页面没有解析到仓库")
                except Exception as e:
                    logger.warning("[orchestrator] GitHub Trending 抓取失败 (%s/3): %s", attempt, e)
                    if attempt < 3:
                        time.sleep(min(2 ** attempt, 5))
            if not results["github"]:
                raise RuntimeError("GitHub Trending 榜单连续 3 次抓取为空，已停止采集以避免产生残缺结果")

        # LMSYS Chatbot Arena 排名（AI 科技 / 混合模式下保存，供后续节点使用）
        if self.collection_mode in {"ai_tech", "mixed"}:
            try:
                full_cmd = f"{self.opencli_binary} browser arena_orch open https://lmarena.ai/leaderboard"
                subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace")

                time.sleep(3)  # 等页面加载

                # 字段: col0=model, col1=rank_number, col2=score_or_category
                full_cmd = f'{self.opencli_binary} browser arena_orch eval "Array.from(document.querySelectorAll(\'table tbody tr\')).slice(0,30).map(tr => {{const cells = tr.querySelectorAll(\'td\'); return {{rank: cells[1]?.textContent?.trim(), model: cells[0]?.textContent?.trim(), arena_score: cells[2]?.textContent?.trim()}}}})"'
                proc = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                     encoding="utf-8", errors="replace")
                if proc.returncode == 0:
                    try:
                        data = json.loads(proc.stdout.strip())
                        if data and isinstance(data, list):
                            today = datetime.now().strftime("%Y-%m-%d")
                            filepath = self.data_dir / f"{today}_rankings_lmsys_arena.json"
                            with open(filepath, "w", encoding="utf-8") as f:
                                json.dump({"title": "LMSYS Chatbot Arena Rankings", "source": "lmsys_arena", "date": today, "rankings": data}, f, ensure_ascii=False, indent=2)
                            logger.info(f"[orchestrator] lmsys_arena: {len(data)} models saved")
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.error(f"[orchestrator] lmsys_arena: {e}")

        # OpenRouter 排名（AI 科技 / 混合模式下保存，供后续节点使用）
        if self.collection_mode in {"ai_tech", "mixed"}:
            try:
                full_cmd = f"{self.opencli_binary} browser or_orch open https://openrouter.ai/rankings"
                subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace")

                time.sleep(3)

                full_cmd = f"{self.opencli_binary} browser or_orch extract"
                proc = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                     encoding="utf-8", errors="replace")
                if proc.returncode == 0:
                    try:
                        extract_data = json.loads(proc.stdout.strip())
                        content = extract_data.get("content", "")
                        if content:
                            today = datetime.now().strftime("%Y-%m-%d")
                            filepath = self.data_dir / f"{today}_rankings_openrouter.json"
                            with open(filepath, "w", encoding="utf-8") as f:
                                json.dump({"title": "OpenRouter Model Rankings", "source": "openrouter", "date": today, "content": content}, f, ensure_ascii=False, indent=2)
                            logger.info(f"[orchestrator] openrouter: saved ({len(content)} chars)")
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.error(f"[orchestrator] openrouter: {e}")
        
        # 清理 Orchestrator 打开的浏览器 session
        for session in ["gh_orch", "arena_orch", "or_orch"]:
            try:
                subprocess.run(
                    f"{self.opencli_binary} browser {session} close",
                    shell=True, capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
            except Exception:
                pass
        logger.info("[orchestrator] browser sessions cleaned up")
        
        return results

    # --- Phase 2: Task planning ---
    
    def _plan_tasks(self, raw_data: dict) -> dict:
        """
        Use Orchestrator LLM to select high-value topics and assign to platforms.
        
        Returns: {platform: [topics]}
        """
        logger.info("[orchestrator] Phase 2: Planning tasks...")
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Build data summary for LLM
        data_summary = []
        for platform, items in raw_data.items():
            if not items:
                continue
            data_summary.append(f"\n### {platform} ({len(items)} items)")
            for i, item in enumerate(items[:40]):  # Show more to LLM
                if isinstance(item, dict):
                    title = item.get("title") or item.get("name") or item.get("note", "untitled")
                    hot = item.get("hot_value") or item.get("hot", "") or item.get("upvotes", "")
                    url = item.get("url") or item.get("link", "")
                    data_summary.append(f"  {i+1}. {title} (hot={hot}) {url}")

        prompt = self._build_planning_prompt(today, "\n".join(data_summary))

        base_messages = [
            {"role": "system", "content": "You are a content curator. Respond ONLY in valid JSON."},
            {"role": "user", "content": prompt},
        ]
        messages = list(base_messages)
        last_error = None
        max_attempts = 2  # Initial generation plus one repair based on the first error.
        for attempt in range(1, max_attempts + 1):
            content = ""
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or "{}"
                parsed = self._parse_planning_json(content)
                if not isinstance(parsed, dict):
                    raise ValueError("planning response must be a JSON object")

                plan = self._filter_plan(parsed)
                plan = self._ensure_platform_coverage(plan, raw_data)

                for platform, topics in plan.items():
                    if isinstance(topics, list):
                        logger.info(f"[orchestrator] Plan: {platform} -> {len(topics)} topics")
                return plan
            except Exception as e:
                last_error = e
                if content:
                    self._save_invalid_planning_response(content, attempt)
                    excerpt = self._planning_error_excerpt(content, e)
                    logger.warning(
                        "[orchestrator] Planning response invalid (%s/%s): %s; near=%r",
                        attempt,
                        max_attempts,
                        e,
                        excerpt,
                    )
                    if attempt == 1:
                        messages = [*base_messages,
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": (
                                    "The previous assistant message is the exact invalid JSON that must be repaired.\n"
                                    f"Parser error: {type(e).__name__}: {e}\n"
                                    f"Content near the error: {excerpt!r}\n\n"
                                    "Repair the JSON according to this exact parser error and return the complete "
                                    "JSON object only. Preserve all valid data. Escape all line breaks, tabs, "
                                    "backslashes, quotes, and other control characters inside string values."
                                ),
                            },
                        ]
                else:
                    logger.warning(
                        "[orchestrator] Planning call failed (%s/%s): %s",
                        attempt,
                        max_attempts,
                        e,
                    )

        logger.error("[orchestrator] Planning failed after one repair: %s; using fallback", last_error)
        return self._fallback_plan(raw_data)

    @staticmethod
    def _parse_planning_json(content: str) -> dict:
        text = str(content or "").strip().lstrip("\ufeff")
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start:end + 1]
        # strict=False accepts raw newlines/tabs accidentally emitted inside JSON strings.
        return json.loads(text, strict=False)

    def _save_invalid_planning_response(self, content: str, attempt: int) -> None:
        try:
            meta_dir = self.data_dir / ".meta"
            meta_dir.mkdir(parents=True, exist_ok=True)
            path = meta_dir / f"planning_invalid_{datetime.now():%Y%m%d_%H%M%S}_{attempt}.txt"
            path.write_text(str(content or ""), encoding="utf-8")
        except OSError as e:
            logger.debug("[orchestrator] Failed to save invalid planning response: %s", e)

    @staticmethod
    def _planning_error_excerpt(content: str, error: Exception) -> str:
        position = getattr(error, "pos", 0) or 0
        start = max(0, position - 100)
        end = min(len(content), position + 100)
        return content[start:end].replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")

    def _build_planning_prompt(self, today: str, data_summary: str) -> str:
        if self.planning_prompt.strip():
            return (
                self.planning_prompt
                .replace("{{date}}", today)
                .replace("{{data_summary}}", data_summary)
                .replace("{{collection_mode}}", self.collection_mode)
            )

        mode_intro = {
            "ai_tech": (
                "Collection mode: AI 科技.\n"
                "Goal: collect AI/technology material for a tech commentary video. "
                "Prioritize GitHub repos, HuggingFace papers/models, model rankings, AI tools, chips, robotics, developer tools, benchmarks, and technical demos. "
                "Do not select general social hot topics unless they directly relate to AI or technology."
            ),
            "daily_hot": (
                "Collection mode: 今日热搜.\n"
                "Goal: collect broad daily hot-search material for a news/hot-topic video. "
                "Prioritize viral social topics from Weibo/Douyin, public events, unusual stories, and strong video material. "
                "Skip low-value ads and pure celebrity gossip."
            ),
            "mixed": (
                "Collection mode: 混合.\n"
                "Goal: collect both AI/technology topics and broad daily hot-search topics. "
                "Balance GitHub/HuggingFace technical material with Weibo/Douyin viral material."
            ),
        }[self.collection_mode]

        platform_rules = {
            "ai_tech": (
                "- HuggingFace: papers and models (pass arxiv_id or model_id in url)\n"
                "- GitHub: include EVERY available trending repo; the output count must equal the GitHub input count\n"
                "- Target 15-30 high-value AI/tech topics total\n"
                "- It is okay for weibo/douyin to be empty in this mode"
            ),
            "daily_hot": (
                "- Weibo topics: things that need browser extraction (posts, comments, images)\n"
                "- Douyin topics: things worth finding video content for. SELECT AS MANY DOUYIN TOPICS AS POSSIBLE\n"
                "- Target 20-40 social hot topics total\n"
                "- It is okay for github/huggingface to be empty in this mode"
            ),
            "mixed": (
                "- Weibo topics: things that need browser extraction (posts, comments, images)\n"
                "- Douyin topics: things worth finding video content for. SELECT AS MANY DOUYIN TOPICS AS POSSIBLE\n"
                "- HuggingFace: papers and models (pass arxiv_id or model_id in url)\n"
                "- GitHub: include EVERY available trending repo; the output count must equal the GitHub input count\n"
                "- Target 40-60 topics total"
            ),
        }[self.collection_mode]

        return f"""Today is {today}. You are a content curator for a video channel.

{mode_intro}

Below are available topics from the enabled platforms. Select worthwhile topics for deep collection.

Criteria:
- Select topics that have enough substance for downstream script generation.
- Prefer material with images, video, README, paper abstract, demo, concrete facts, or public discussion.
- Skip ads, duplicates, and low-value topics.
- Deduplicate by meaning, not just title.

For each selected topic, assign it to the appropriate worker platform.

{data_summary}

Respond ONLY in JSON format:
{{
  "weibo": [
    {{"title": "...", "url": "...", "hot_value": 123, "reason": "..."}}
  ],
  "douyin": [],
  "huggingface": [],
  "github": []
}}

Rules:
{platform_rules}
- Only include keys for known platforms: weibo, douyin, huggingface, github.
- If a platform has no suitable topics, return an empty array for it."""

    def _ensure_platform_coverage(self, plan: dict, raw_data: dict) -> dict:
        """Apply deterministic coverage rules after the LLM has ranked the topics."""
        if "github" in self.enabled_platforms:
            trending = [item for item in (raw_data.get("github") or []) if isinstance(item, dict)]
            before = len(plan.get("github") or [])
            plan["github"] = self._merge_unique_topics(plan.get("github") or [], trending)
            if len(plan["github"]) > before:
                logger.info(
                    "[orchestrator] GitHub coverage: planner selected %s/%s; backfilled to %s",
                    before,
                    len(trending),
                    len(plan["github"]),
                )
        return plan

    def _merge_unique_topics(self, preferred: list, candidates: list) -> list:
        merged = []
        seen = set()
        for item in [*preferred, *candidates]:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("url") or item.get("link") or item.get("title") or item.get("name") or "")
            identity = identity.strip().lower().rstrip("/")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
        return merged
    
    def _fallback_plan(self, raw_data: dict) -> dict:
        """Simple fallback if LLM planning fails."""
        plan = self._empty_plan()
        
        # Assign weibo hot to weibo worker
        for item in (raw_data.get("weibo") or [])[:8]:
            if "weibo" in plan and isinstance(item, dict):
                plan["weibo"].append(item)
        
        # Assign douyin to douyin worker
        for item in (raw_data.get("douyin") or [])[:5]:
            if "douyin" in plan and isinstance(item, dict):
                plan["douyin"].append(item)
        
        # HF papers
        for item in (raw_data.get("hf_papers") or [])[:6]:
            if "huggingface" in plan and isinstance(item, dict):
                plan["huggingface"].append(item)
        
        # GitHub
        for item in raw_data.get("github") or []:
            if "github" in plan and isinstance(item, dict):
                plan["github"].append(item)
        
        return plan
    
    # --- Phase 2.5: Deduplication ---
    
    def _dedup_tasks(self, task_plan: dict) -> dict:
        """
        Remove topics that have already been collected.
        Scans existing JSON files for titles and filters duplicates.
        Looks in current collected/ dir AND all previous dates' collected/ dirs.
        """
        # Collect all existing titles from data files
        existing_titles = set()
        
        # Scan current dir
        if self.data_dir.exists():
            for f in self.data_dir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    if isinstance(data, dict):
                        title = data.get("title", "")
                        if title:
                            existing_titles.add(title.lower().strip())
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                title = item.get("title", "")
                                if title:
                                    existing_titles.add(title.lower().strip())
                except Exception:
                    continue
        
        # Also scan other dates' collected/ dirs for cross-day dedup
        data_root = self.data_dir.parent.parent  # data/{date}/collected -> data/
        if data_root.exists():
            for date_dir in data_root.iterdir():
                if not date_dir.is_dir():
                    continue
                collected_dir = date_dir / "collected"
                if collected_dir == self.data_dir or not collected_dir.exists():
                    continue
                for f in collected_dir.glob("*.json"):
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        if isinstance(data, dict):
                            title = data.get("title", "")
                            if title:
                                existing_titles.add(title.lower().strip())
                    except Exception:
                        continue
        
        if not existing_titles:
            return task_plan
        
        logger.info(f"[dedup] Found {len(existing_titles)} existing titles")
        
        # Filter each platform's topics
        deduped_plan = {}
        total_removed = 0
        
        for platform, topics in task_plan.items():
            if not isinstance(topics, list):
                deduped_plan[platform] = topics
                continue
            
            filtered = []
            for topic in topics:
                if not isinstance(topic, dict):
                    filtered.append(topic)
                    continue
                
                title = (topic.get("title") or "").lower().strip()
                
                # Check exact match or substring match
                is_dup = False
                if title and title in existing_titles:
                    is_dup = True
                elif title:
                    # Fuzzy: check if any existing title contains this or vice versa
                    for existing in existing_titles:
                        if len(title) > 5 and (title in existing or existing in title):
                            is_dup = True
                            break
                
                if is_dup:
                    total_removed += 1
                    logger.info(f"[dedup] skip: {topic.get('title', '?')}")
                else:
                    filtered.append(topic)
            
            deduped_plan[platform] = filtered
        
        if total_removed:
            logger.info(f"[dedup] Removed {total_removed} duplicate topics")
        
        return deduped_plan
    
    # --- Phase 3: Dispatch Workers ---
    
    def _dispatch_workers(self, task_plan: dict) -> dict:
        """Launch Workers concurrently, one per platform."""
        logger.info("[orchestrator] Phase 3: Dispatching workers...")
        
        results = {}
        
        # Filter platforms with actual tasks
        active_tasks = {
            platform: topics 
            for platform, topics in task_plan.items() 
            if isinstance(topics, list) and len(topics) > 0
        }
        
        if not active_tasks:
            logger.warning("[orchestrator] No tasks to dispatch!")
            return results
        
        logger.info(f"[orchestrator] Launching {len(active_tasks)} workers: {list(active_tasks.keys())}")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            
            for platform, topics in active_tasks.items():
                # 按平台选模型（支持 worker_overrides）
                from config_loader import load_config, get_worker_model_config
                cfg = load_config()
                platform_model = get_worker_model_config(cfg, platform)
                
                worker = PlatformWorker(
                    platform=platform,
                    llm_base_url=platform_model["base_url"],
                    llm_api_key=platform_model["api_key"],
                    llm_model=platform_model["model"],
                    opencli_binary=self.opencli_binary,
                    data_dir=self.data_dir,
                )
                
                future = executor.submit(worker.run, topics)
                futures[future] = platform
            
            # Collect results as they complete
            completed_workers = 0
            for future in as_completed(futures):
                platform = futures[future]
                try:
                    worker_result = future.result(timeout=300)  # 5 min timeout per worker
                    results[platform] = worker_result
                    logger.info(
                        f"[orchestrator] Worker-{platform} done: "
                        f"{len(worker_result['files_saved'])} files"
                    )
                except Exception as e:
                    logger.error(f"[orchestrator] Worker-{platform} failed: {e}")
                    results[platform] = {
                        "files_saved": [],
                        "total_items": 0,
                        "errors": [str(e)],
                        "topics_done": [],
                    }
                finally:
                    completed_workers += 1
                    self._report_progress(
                        f"平台采集 [{completed_workers}/{len(futures)}]: {platform}",
                        0.5 + 0.35 * completed_workers / max(len(futures), 1),
                    )
        
        return results
