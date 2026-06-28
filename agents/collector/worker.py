"""
Platform Worker - 单平台深度采集 Agent

每个 Worker 负责一个平台的深度采集，独立运行自己的 tool-calling loop。
可以使用本地模型（LM Studio）或远程模型（DeepSeek）。
"""
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from openai import OpenAI

logger = logging.getLogger(__name__)


# --- Worker System Prompts (per platform) ---

WORKER_PROMPTS = {
    "weibo": """You are a Weibo deep-collection worker. Today is {date}.

Your task: Deep-collect the following Weibo topics. For each topic:
1. Use `browser <session> open <url>` to open the topic page
2. Use `browser <session> extract` to get page content
3. **CRITICAL: Extract image URLs** using:
   `browser <session> eval "Array.from(document.querySelectorAll('img[src*=sinaimg]')).map(i=>i.src.replace(/\\/thumb\\d+\\/|orj\\d+\\/|mw\\d+\\//,'/large/')).filter(u=>u.includes('/large/'))"` 
4. Extract: post text, top comments (user + text + likes)
5. If search page has no images, open one of the top posts to extract images from detail page
6. Save each topic immediately with `save_data`

Topics to collect:
{topics}

## Save format (JSON object per topic):
- title, source ("weibo"), content (200+ chars), hot_value, url
- visual_assets: {{images: [url1, url2, ...]}}  ← 必须至少1张图！
- top_comments: [{{user, text, likes}}] (3-5 per topic)
- key_points: [3-5 bullet points]
- media_type: "hot_topic|tech_news|funny"

## Image extraction rules (VERY IMPORTANT):
- visual_assets.images MUST contain at least 1 image URL
- Prefer large images: replace /thumb150/, /orj360/, /mw690/ with /large/ in URL
- Only include sinaimg.cn URLs (ignore icons, avatars, emojis)
- If extract gives no images, use browser eval to query img tags directly

## Rules:
- Use different session names for each topic (e.g. wb1, wb2, wb3)
- If you encounter AUTH_REQUIRED, call notify_user
- Save each topic immediately after collection, do NOT batch
- Respond with a brief summary when done
""",

    "douyin": """You are a Douyin deep-collection worker. Today is {date}.

Your task: Deep-collect the following Douyin topics. For each topic, find relevant videos and extract details.

## Available opencli douyin commands:
```
Usage: opencli douyin [command]

Commands:
  hashtag <action>       话题搜索 / AI推荐 / 热点词
    actions: search, suggest, hot
    options: --keyword [value], --limit [value], -f json
    output columns: name, id, view_count

  user-videos <sec_uid>  获取指定用户的视频列表（含下载地址和热门评论）
    options: -f json

  videos                 获取自己的作品列表
    options: -f json
```

## Also available: browser commands
- `browser <session> open <url>` - open a URL
- `browser <session> extract` - extract page content
- `browser <session> eval "<js>"` - execute JavaScript

## Strategy:
1. Use `douyin hashtag search --keyword "<topic keyword>" --limit 5 -f json` to find related hashtags
2. Use `browser <session> open https://www.douyin.com/search/<keyword>` if hashtag search fails
3. Extract video URLs from search results or page (format: https://www.douyin.com/video/XXXXX)
4. Open the video page with browser to get details (title, **author name**, comments, description)
5. Save each topic immediately with `save_data`

Topics to collect:
{topics}

## Save format (JSON object per topic):
- title, source ("douyin"), content (200+ chars), hot_value, url (MUST be https://www.douyin.com/video/XXXXX format!)
- author: "视频作者抖音昵称"  ← 必须记录！用于视频中标注素材来源
- visual_assets: {{video_url: "<same as url, the douyin video page URL>"}}
- top_comments: [{{user, text, likes}}] (3-5 per topic)
- key_points: [3-5 bullet points]
- media_type: "hot_topic|tech_news|funny"

## CRITICAL Rules:
- The `url` field MUST be a valid douyin video URL like https://www.douyin.com/video/7649231660986141994
- NEVER use search URLs like https://www.douyin.com/search/xxx — these CANNOT be parsed for video download!
- NEVER use hashtag URLs like https://www.douyin.com/hashtag/xxx — only /video/NUMBER format is valid!
- visual_assets.video_url MUST also contain this URL (needed for video download later)
- Use different session names (dy1, dy2, dy3...)
- If a topic search fails after 2 attempts, skip it and move to the next topic
- Save each topic immediately after collection, do NOT batch
- Respond with a brief summary when done
""",

    "huggingface": """You are a HuggingFace deep-collection worker. Today is {date}.

Your task: Deep-collect the following HF papers and models. For each:
1. Use `hf paper <arxiv_id> -f json` to get full paper details (summary, aiSummary, aiKeywords)
2. For models, use browser to open model page and extract Model Card
3. Save each item immediately with `save_data`

Items to collect:
{topics}

## Save format (JSON object per item):
- title, source ("HuggingFace"), content (200+ chars), hot_value (upvotes), url
- key_points: [3-5 bullet points]
- media_type: "tech_news"
- technical_details: {{
    paper_abstract_en: "FULL English abstract (MUST keep original)",
    ai_summary: "AI-generated summary",
    model_size: "param count",
    benchmark: "key results",
    demo_url: "Space/demo link if any"
  }}

## Rules:
- MUST preserve the original English abstract in paper_abstract_en
- Save each paper/model immediately
- Respond with a brief summary when done
""",

    "github": """You are a GitHub deep-collection worker. Today is {date}.

Your task: Deep-collect the following GitHub repos. For each:
1. Use `browser <session> open <url>` to open the repo page
2. Extract README using `browser <session> eval "document.querySelector('article.markdown-body')?.innerText?.substring(0, 5000) || document.querySelector('[data-testid=readme] article')?.innerText?.substring(0, 5000) || 'NO_README'"`
3. Also extract repo stats: `browser <session> eval "JSON.stringify({stars: document.querySelector('.Counter.js-social-count')?.title || '', forks: document.querySelectorAll('.Counter')[1]?.title || '', about: document.querySelector('.f4.my-3')?.innerText || ''})"`
4. Save each repo immediately with `save_data`

Repos to collect:
{topics}

## Save format (JSON object per repo):
- title, source ("github_trending"), content (500+ chars! Include README key sections), url (MUST be full GitHub repo URL like https://github.com/owner/repo)
- visual_assets: {{readme_url: "<same repo url, signals download stage to fetch full README.md and images>"}}
- key_points: [5-8 bullet points about what the project does, features, usage]
- media_type: "tech_news"
- technical_details: {{
    readme_excerpt: "First 2000 chars of README",
    stars: "star count",
    forks: "fork count", 
    language: "primary language",
    demo_url: "demo link if mentioned in README"
  }}

## Rules:
- Use different session names (gh1, gh2, gh3...)
- source MUST be exactly "github_trending" (lowercase with underscore)
- url MUST be the full repo URL (https://github.com/owner/repo)
- content must be 500+ characters! Include README overview and key features
- If README extraction fails, try alternative: `browser <session> eval "document.querySelector('.Box-body.px-5.pb-5')?.innerText?.substring(0, 5000)"`
- Save each repo immediately
- Respond with a brief summary when done
""",

    "tech_36kr": """You are a 36Kr tech news deep-collection worker. Today is {date}.

Your task: Deep-collect the following tech/startup news articles. For each:
1. Use `browser <session> open <url>` to open the article page
2. Use `browser <session> extract` to get full article content
3. Extract: title, full text (500+ chars), author, publish time, key quotes
4. Save each article immediately with `save_data`

Articles to collect:
{topics}

## Save format (JSON object per article):
- title, source ("36kr"), content (500+ chars of article body), url
- key_points: [3-5 bullet points summarizing the article]
- media_type: "tech_news"
- technical_details: {{
    author: "article author",
    publish_time: "publish date/time",
    tags: ["relevant", "tags"]
  }}

## Rules:
- Use different session names (kr1, kr2, kr3...)
- Extract FULL article content, not just summary
- Save each article immediately
- Respond with a brief summary when done
""",
}


# --- Worker Tools (same as main agent but lighter) ---

WORKER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "opencli",
            "description": "Execute an opencli command. Pass the full command string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The opencli command (without 'opencli' prefix)",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_data",
            "description": "Save collected data to a JSON file in today's collected/ directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename (without date prefix or extension, e.g. 'wechat_merge_images')",
                    },
                    "data": {
                        "description": "Structured data to save (JSON object or array)",
                    },
                },
                "required": ["filename", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_user",
            "description": "Notify user when manual action needed (login, captcha, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "What the user needs to do"},
                    "platform": {"type": "string", "description": "Related platform"},
                },
                "required": ["message"],
            },
        },
    },
]


class PlatformWorker:
    """
    Single-platform collection worker.
    
    Each worker runs its own tool-calling loop targeting one platform.
    Can use local model (LM Studio) or remote model (DeepSeek).
    """
    
    MAX_STEPS = 60  # 每个平台做热搜集锦，需要充足步数
    
    def __init__(
        self,
        platform: str,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        opencli_binary: str,
        data_dir: Path,
    ):
        self.platform = platform
        self.client = OpenAI(base_url=llm_base_url, api_key=llm_api_key)
        self.model = llm_model
        self.opencli_binary = opencli_binary
        self.data_dir = data_dir
        
        # Ensure output dir exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Stats
        self.stats = {"files_saved": [], "total_items": 0, "errors": [], "topics_done": []}
        
        # Track browser sessions for cleanup
        self._browser_sessions: set[str] = set()
        self._dispatch: dict[str, Callable] = {
            "opencli": self._exec_opencli,
            "save_data": self._exec_save_data,
            "notify_user": self._exec_notify_user,
        }
    
    def run(self, topics: list[dict]) -> dict:
        """
        Run the worker loop for assigned topics.
        
        Args:
            topics: List of topic dicts from orchestrator, e.g.:
                    [{"title": "...", "url": "...", "hot_value": 123, ...}]
        
        Returns:
            Stats dict with files_saved, total_items, errors
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Format topics for prompt
        topics_text = "\n".join(
            f"- {t.get('title', 'untitled')} (hot: {t.get('hot_value', '?')}, url: {t.get('url', 'N/A')})"
            for t in topics
        )
        
        # Get platform-specific prompt
        prompt_template = WORKER_PROMPTS.get(self.platform, WORKER_PROMPTS["weibo"])
        # Use replace instead of .format() to avoid KeyError when topics_text contains {curly braces}
        system_prompt = prompt_template.replace("{date}", today).replace("{topics}", topics_text)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Start collecting now."},
        ]
        
        logger.info(f"[worker-{self.platform}] Starting with {len(topics)} topics")
        
        for step in range(self.MAX_STEPS):
            logger.info(f"[worker-{self.platform}] step {step + 1}/{self.MAX_STEPS}")
            
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=WORKER_TOOLS,
                    tool_choice="auto",
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"[worker-{self.platform}] LLM error: {e}")
                self.stats["errors"].append(str(e))
                break
            
            message = response.choices[0].message
            messages.append(message)
            
            if not message.tool_calls:
                if message.content:
                    logger.info(f"[worker-{self.platform}] done: {message.content[:100]}")
                break
            
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                handler = self._dispatch.get(name)
                if handler:
                    result = handler(args)
                else:
                    result = {"error": f"Unknown tool: {name}"}
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": self._serialize_result(result),
                })
        else:
            logger.warning(f"[worker-{self.platform}] hit MAX_STEPS")
        
        # 清理：关闭 Worker 打开的浏览器页面
        self._cleanup_browser()
        
        logger.info(
            f"[worker-{self.platform}] finished: "
            f"{len(self.stats['files_saved'])} files, "
            f"{self.stats['total_items']} items, "
            f"{len(self.stats['errors'])} errors"
        )
        return self.stats
    
    # --- Tool Handlers ---
    
    def _exec_opencli(self, args: dict) -> dict:
        command = args.get("command", "")
        if not command:
            return {"success": False, "error": "empty command"}
        
        # Track browser sessions for cleanup
        parts = command.split()
        if len(parts) >= 2 and parts[0] == "browser":
            self._browser_sessions.add(parts[1])
        
        full_cmd = f"{self.opencli_binary} {command}"
        
        try:
            proc = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
            
            output = proc.stdout.strip()
            stderr = proc.stderr.strip()
            
            if proc.returncode == 0:
                # Try parse JSON
                try:
                    data = json.loads(output)
                    if isinstance(data, list):
                        logger.info(f"[worker-{self.platform}] $ {command[:60]} -> {len(data)} items")
                        return {"success": True, "data": data, "count": len(data)}
                    return {"success": True, "data": data}
                except json.JSONDecodeError:
                    return {"success": True, "text": output[:5000]}
            else:
                combined = f"{output}\n{stderr}".strip()
                logger.warning(f"[worker-{self.platform}] $ {command[:60]} -> exit={proc.returncode}")
                return {"success": False, "error": combined[:3000], "exit_code": proc.returncode}
                
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout (120s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _exec_save_data(self, args: dict) -> dict:
        filename = args.get("filename", "unnamed")
        data = args.get("data")
        
        if data is None:
            return {"success": False, "error": "data is None"}
        
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / f"{today}_{self.platform}_{filename}.json"
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"success": False, "error": f"write failed: {e}"}
        
        self.stats["files_saved"].append(str(filepath))
        if isinstance(data, list):
            self.stats["total_items"] += len(data)
        else:
            self.stats["total_items"] += 1
        
        topic_title = ""
        if isinstance(data, dict):
            topic_title = data.get("title", filename)
        elif isinstance(data, list) and data:
            topic_title = data[0].get("title", filename) if isinstance(data[0], dict) else filename
        else:
            topic_title = filename
        self.stats["topics_done"].append({"title": topic_title, "file": filepath.name})
        
        logger.info(f"[worker-{self.platform}] saved: {filepath.name}")
        return {"success": True, "path": str(filepath)}
    
    def _exec_notify_user(self, args: dict) -> dict:
        message = args.get("message", "Need your action")
        platform = args.get("platform", self.platform)
        
        separator = "=" * 50
        print(f"\n{separator}")
        print(f"[!] Worker-{self.platform} needs help!")
        print(f"[platform] {platform}")
        print(f"[action] {message}")
        print(separator)
        
        user_input = input("Press Enter when done (or type 'skip'): ").strip()
        
        if user_input.lower() == "skip":
            logger.info(f"[worker-{self.platform}] user skipped")
            return {"success": True, "user_action": "skipped"}
        
        logger.info(f"[worker-{self.platform}] user confirmed")
        return {"success": True, "user_action": "confirmed"}
    
    # --- Util ---
    
    def _serialize_result(self, result: dict) -> str:
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
        
        if len(text) > 12000:
            if "data" in result and isinstance(result["data"], list):
                truncated = result.copy()
                truncated["data"] = result["data"][:15]
                truncated["_truncated"] = True
                truncated["_total"] = len(result["data"])
                text = json.dumps(truncated, ensure_ascii=False, default=str)
            else:
                text = text[:12000] + "\n...(truncated)"
        
        return text
    
    def _cleanup_browser(self):
        """关闭该 Worker 打开的所有浏览器 session"""
        if not hasattr(self, '_browser_sessions'):
            return
        for session in self._browser_sessions:
            try:
                full_cmd = f"{self.opencli_binary} browser {session} close"
                subprocess.run(
                    full_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception:
                pass
        if self._browser_sessions:
            logger.info(f"[worker-{self.platform}] closed {len(self._browser_sessions)} browser sessions")
        self._browser_sessions.clear()
