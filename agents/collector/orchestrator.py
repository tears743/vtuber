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
    ):
        self.client = OpenAI(base_url=orchestrator_base_url, api_key=orchestrator_api_key)
        self.model = orchestrator_model
        
        self.worker_base_url = worker_base_url
        self.worker_api_key = worker_api_key
        self.worker_model = worker_model
        
        self.opencli_binary = opencli_binary
        self.data_dir = data_dir
        self.max_workers = max_workers
        
        # Ensure output dir exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
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
        logger.info("=" * 60)
        
        # Phase 1: Fetch raw hot lists
        raw_data = self._fetch_hot_lists()
        
        # Phase 2: Use Orchestrator LLM to plan tasks
        task_plan = self._plan_tasks(raw_data)
        
        # Phase 2.5: Dedup - remove already collected topics
        task_plan = self._dedup_tasks(task_plan)
        
        # Phase 3: Dispatch Workers concurrently
        results = self._dispatch_workers(task_plan)
        
        # Phase 4: Summary
        total_files = sum(len(r["files_saved"]) for r in results.values())
        total_items = sum(r["total_items"] for r in results.values())
        total_errors = sum(len(r["errors"]) for r in results.values())
        
        logger.info("=" * 60)
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
        
        for name, cmd in commands.items():
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
        try:
            full_cmd = f"{self.opencli_binary} browser gh_orch open https://github.com/trending"
            subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
            
            full_cmd = f'{self.opencli_binary} browser gh_orch eval "Array.from(document.querySelectorAll(\'article h2 a\')).map(a => ({{title: a.textContent.trim(), url: \'https://github.com\' + a.getAttribute(\'href\')}}))"'
            proc = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                 encoding="utf-8", errors="replace")
            if proc.returncode == 0:
                try:
                    data = json.loads(proc.stdout.strip())
                    results["github"] = data if isinstance(data, list) else []
                    logger.info(f"[orchestrator] github: {len(results.get('github', []))} repos")
                except json.JSONDecodeError:
                    results["github"] = []
            else:
                results["github"] = []
        except Exception as e:
            results["github"] = []
            logger.error(f"[orchestrator] github: {e}")
        
        # LMSYS Chatbot Arena 排名（只拉排名，不深挖）
        try:
            import time
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
        
        # OpenRouter 排名（用 extract 拿 markdown，直接保存）
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
        
        prompt = f"""Today is {today}. You are a content curator for a tech/news video channel.

Below are today's hot topics from multiple platforms. Select ALL worthwhile topics for deep collection (aim for 40-60 total).

Criteria:
- AI/tech news: high priority (papers, models, tools)
- Social hot topics: select interesting/viral ones, skip celebrity gossip
- Funny/unusual stories: good for engagement
- Skip: ads, duplicates, low-value topics

For each selected topic, assign it to the appropriate worker platform.

{chr(10).join(data_summary)}

Respond in JSON format:
{{
  "weibo": [
    {{"title": "...", "url": "...", "hot_value": 123, "reason": "..."}}
  ],
  "douyin": [...],
  "huggingface": [...],
  "github": [...]
}}

Rules:
- Weibo topics: things that need browser extraction (posts, comments, images)
- Douyin topics: things worth finding video content for
- HuggingFace: papers and models (pass arxiv_id or model_id in url)
- GitHub: repos worth describing (include ALL trending repos)
- Each platform should get 10-20 topics (more is better)
- Total 40-60 topics
- We are making a hot-topic video compilation per platform, so include more rather than less"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a content curator. Respond ONLY in valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            
            plan = json.loads(response.choices[0].message.content)
            
            # Log plan
            for platform, topics in plan.items():
                if isinstance(topics, list):
                    logger.info(f"[orchestrator] Plan: {platform} -> {len(topics)} topics")
            
            return plan
            
        except Exception as e:
            logger.error(f"[orchestrator] Planning failed: {e}")
            # Fallback: simple assignment based on source
            return self._fallback_plan(raw_data)
    
    def _fallback_plan(self, raw_data: dict) -> dict:
        """Simple fallback if LLM planning fails."""
        plan = {
            "weibo": [],
            "douyin": [],
            "huggingface": [],
            "github": [],
        }
        
        # Assign weibo hot to weibo worker
        for item in (raw_data.get("weibo") or [])[:8]:
            if isinstance(item, dict):
                plan["weibo"].append(item)
        
        # Assign douyin to douyin worker
        for item in (raw_data.get("douyin") or [])[:5]:
            if isinstance(item, dict):
                plan["douyin"].append(item)
        
        # HF papers
        for item in (raw_data.get("hf_papers") or [])[:6]:
            if isinstance(item, dict):
                plan["huggingface"].append(item)
        
        # GitHub
        for item in (raw_data.get("github") or [])[:5]:
            if isinstance(item, dict):
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
        
        return results
