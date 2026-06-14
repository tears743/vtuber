"""
Layer 1: 智能采集 Agent

标准 Agent Loop 实现：
  while True:
    response = llm(messages, tools)
    if no tool_calls: break
    for each tool_call: execute → append result
    loop

Agent 自主决定采集策略，通过 tool-calling 与 OpenCLI 交互。
遇到不确定的命令时，Agent 会自己查 --help 获取用法。
"""
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from openai import OpenAI

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# Tools Schema
# ═══════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "opencli",
            "description": (
                "执行 OpenCLI 命令获取各平台数据。OpenCLI 支持 153 个站点适配器。\n"
                "如果不确定某个命令怎么用，先用 opencli_help 查看用法。\n"
                "站点适配器命令一般带 -f json 输出结构化数据。\n"
                "browser 子命令格式特殊，需先查 help。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "opencli 命令（不含 'opencli' 前缀）",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 120",
                        "default": 120,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencli_help",
            "description": (
                "查看 OpenCLI 命令的帮助信息。用于了解命令参数、格式和用法。\n"
                "在执行不熟悉的命令前，必须先查 help。\n"
                "示例：\n"
                "- command='weibo' → 查看微博所有子命令\n"
                "- command='weibo hot' → 查看热搜命令的参数\n"
                "- command='browser' → 查看浏览器操作命令\n"
                "- command='douyin hashtag' → 查看抖音话题命令"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要查看帮助的命令（不含 'opencli' 前缀和 '--help'）",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_data",
            "description": "将采集结果保存到本地 JSON 文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["hot_topics", "ai_news", "raw_materials"],
                        "description": "数据分类目录",
                    },
                    "filename": {
                        "type": "string",
                        "description": "文件名（不含路径和扩展名）",
                    },
                    "data": {
                        "description": "要保存的结构化数据（JSON 对象或数组）",
                    },
                },
                "required": ["category", "filename", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_user",
            "description": (
                "当遇到需要用户手动操作的情况时调用（如：需要登录、需要验证码、需要授权等）。"
                "调用后会等待用户完成操作并确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "告诉用户需要做什么操作",
                    },
                    "platform": {
                        "type": "string",
                        "description": "相关平台（如 weibo, douyin）",
                    },
                },
                "required": ["message"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个专业的新闻/热点深度采集 Agent。今天是 {date}。

## 目标
采集当日热门话题和 AI 科技新闻的**完整内容**，包括：
- 文字内容（标题、完整摘要/正文）
- 多媒体素材（图片URL、可播放的视频URL）
- 技术细节（论文英文原始摘要、模型参数、benchmark数据）

最终数据要让下游的视频合成 Agent 和音频 Agent 能直接使用。

## 采集范围与可用命令

### 1. 微博
- `weibo hot -f json` → 热搜列表（rank, word, category, hot_value, url）
- `weibo search "关键词" -f json` → 搜索相关微博（需登录）
- `weibo post <id> -f json` → **单条微博完整内容（含图片、视频附件）**
- 也可用 browser 打开微博话题页面提取内容

### 2. 抖音
- `douyin hashtag hot -f json` → 热榜（name, id, view_count）
- `douyin search "关键词" -f json` → 搜索视频（rank, desc, author, url, plays, likes, comments）
- `douyin user-videos <sec_uid> -f json` → **用户视频列表，含 play_url（可播放链接）和 top_comments**

### 3. HuggingFace
- `hf top -f json` → 每日热门论文列表
- `hf paper <arxiv_id> -f json` → **论文详情：完整 summary（英文原始摘要）、aiSummary（AI总结）、aiKeywords**
- `hf models --sort trending -f json` → 热门模型列表（id, pipelineTag, downloads, likes, tags）
- `hf spaces -f json` → 热门 Spaces/Demo
- 模型 Model Card 需用 browser 打开 `https://huggingface.co/<model_id>` 页面提取

### 4. GitHub
- browser 打开 `https://github.com/trending` 提取
- 对感兴趣的 repo 用 browser 打开详情页提取 README 内容

## 工作流程（三阶段）

### 第一阶段：获取各平台榜单列表
获取微博、抖音、HF、GitHub 的热榜/列表

### 第二阶段：深度采集（关键！）
筛选高价值条目，挖掘详细内容：

**微博深挖：**
- 对感兴趣的话题，用 browser 打开话题 URL 提取微博正文和图片
- 如果能拿到具体微博 ID，用 `weibo post <id>` 获取完整内容

**抖音深挖：**
- 对热点话题用 `douyin search` 搜索相关视频
- 搜索结果中的 url 就是抖音视频页面链接
- 如果需要可播放的视频下载链接，可通过 `douyin user-videos <sec_uid>` 获取 play_url

**HF 论文深挖（重要！）：**
- 对每篇热门论文用 `hf paper <arxiv_id> -f json` 获取：
  - summary：论文英文原始摘要（完整保留）
  - aiSummary：AI 生成的论文要点总结
  - aiKeywords：AI 标注的关键词
  - authors：作者列表

**HF 模型深挖：**
- 对有趣的模型用 browser 打开 `https://huggingface.co/<model_id>` 提取 Model Card
- Model Card 通常包含：模型用途、参数量、训练数据、使用方法、benchmark 对比

**GitHub 深挖：**
- 用 browser 打开 repo 页面提取 README 核心内容
- 关注：项目描述、架构图链接、安装方式、Star 增长

### 第三阶段：结构化保存

### 筛选标准
✅ 科技/AI（最高优先级 — 论文、模型、产品发布）
✅ 社会争议、反转（有吐槽空间）
✅ 离谱/搞笑（有梗）
✅ 财经/民生（跟普通人相关）
❌ 纯粹明星八卦（跳过）
❌ 政治敏感（跳过）

## 保存格式
```json
{{
  "title": "标题",
  "source": "来源平台",
  "content": "详细正文/摘要（至少200字）",
  "hot_value": 热度数值,
  "url": "原始链接",
  "tags": ["标签1", "标签2"],
  "media_type": "科技解读|热点吐槽|趣闻播报",
  "visual_assets": {{
    "images": ["图片URL1", "图片URL2"],
    "video_url": "可播放的视频链接或下载链接"
  }},
  "top_comments": [
    {{"user": "用户名", "text": "评论内容", "likes": 点赞数}}
  ],
  "key_points": ["要点1", "要点2", "要点3"],
  "technical_details": {{
    "paper_abstract_en": "论文英文原始摘要（必须保留原文）",
    "ai_summary": "AI生成的论文要点总结",
    "model_card": "Model Card 关键信息",
    "model_size": "参数量",
    "benchmark": "benchmark 关键结果",
    "demo_url": "在线Demo/Space链接"
  }}
}}
```
字段按实际情况填写。title/source/content/key_points 必填，其他有就填。

## 规则
- 第一次使用某个命令前，先用 opencli_help 查看用法
- 命令失败后读错误信息，调整参数重试（最多 2 次）
- 不要重复执行完全相同的命令
- 深度采集阶段至少对 5 个话题做详细抓取
- 遇到"需要登录"、"AUTH_REQUIRED"等错误时，调用 notify_user 通知用户去登录
- AI/科技类论文：必须保留英文原始摘要（paper_abstract_en），不要只翻译
- 抖音视频：尽量获取可播放链接（play_url），不要只保存封面图
- 每个话题尽量抓 3-5 条代表性热门评论（有助于了解舆论方向，也可以做视频弹幕素材）
- 微博评论可以通过 browser 打开帖子页面提取
- 抖音评论通过 `douyin user-videos --with_comments true` 获取
- ⚠️ **重要：每采集完一条话题就立刻 save_data！** 不要攒数据。每深挖完一个话题，马上保存这条数据，然后继续下一个。这样即使中途中断也不会丢失已采集的数据。
- 全部完成后回复总结
"""





# ═══════════════════════════════════════════════════════
# Agent Loop
# ═══════════════════════════════════════════════════════

class CollectorAgent:
    """
    采集 Agent - 标准 tool-calling loop 实现
    
    Loop:
      1. Call LLM with messages + tools
      2. If response has tool_calls → execute each → append results → continue
      3. If response has no tool_calls → done
      4. Safety: break after MAX_STEPS
    """
    
    MAX_STEPS = 50
    
    def __init__(
        self,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        opencli_binary: str,
        data_dir: Path,
    ):
        self.client = OpenAI(base_url=llm_base_url, api_key=llm_api_key)
        self.model = llm_model
        self.opencli_binary = opencli_binary
        self.data_dir = data_dir
        
        # 确保目录
        for sub in ["hot_topics", "ai_news", "raw_materials"]:
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        
        # Tool dispatch table
        self._dispatch: dict[str, Callable] = {
            "opencli": self._exec_opencli,
            "opencli_help": self._exec_opencli_help,
            "save_data": self._exec_save_data,
            "notify_user": self._exec_notify_user,
        }
        
        # 运行统计
        self.stats = {"files_saved": [], "total_items": 0, "errors": [], "topics_done": []}
    
    def run(self) -> dict:
        """执行 agent loop，返回统计"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(date=today)},
            {"role": "user", "content": "开始今日数据采集。"},
        ]
        
        for step in range(self.MAX_STEPS):
            logger.info(f"[agent] ─── step {step + 1}/{self.MAX_STEPS} ───")
            
            # 1. Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            
            message = response.choices[0].message
            
            # 2. Append assistant message (必须保留 tool_calls 字段)
            messages.append(message)
            
            # 3. 检查是否有 tool_calls
            if not message.tool_calls:
                # Agent 认为完成了
                if message.content:
                    logger.info(f"[agent] 完成: {message.content[:200]}")
                break
            
            # 4. Execute each tool call, append results
            has_save = False
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                
                # Parse args (带容错)
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                # Dispatch
                handler = self._dispatch.get(name)
                if handler:
                    result = handler(args)
                else:
                    result = {"error": f"未知工具: {name}"}
                
                if name == "save_data":
                    has_save = True
                
                # Append tool result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": self._serialize_result(result),
                })
            
            # 注意: 上下文压缩暂时禁用。DeepSeek 64K 上下文足够 50 步使用。
            # 如果未来遇到 token 溢出，可在此处启用：
            # if len(messages) > 60:
            #     messages = self._compact_context(messages)
        else:
            logger.warning(f"[agent] 达到最大步数 {self.MAX_STEPS}，强制终止")
        
        return self.stats
    
    # ─── Tool Handlers ────────────────────────────────

    def _exec_opencli(self, args: dict) -> dict:
        """执行 OpenCLI 命令"""
        command = args.get("command", "")
        timeout = args.get("timeout", 120)
        
        if not command:
            return {"success": False, "error": "command 参数为空"}
        
        full_cmd = f"{self.opencli_binary} {command}"
        logger.info(f"[opencli] $ {full_cmd}")
        
        try:
            proc = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
            )
            
            if proc.returncode != 0:
                # 合并 stdout 和 stderr 给 Agent 更完整的错误信息
                err = (proc.stdout or "") + (proc.stderr or "")
                err = err.strip()[:800]
                logger.warning(f"[opencli] ✗ exit={proc.returncode}: {err}")
                self.stats["errors"].append({"cmd": command, "error": err[:200]})
                return {"success": False, "error": err}
            
            stdout = proc.stdout.strip()
            if not stdout:
                return {"success": True, "data": None, "note": "命令成功但无输出"}
            
            # 尝试 JSON 解析
            try:
                data = json.loads(stdout)
                count = len(data) if isinstance(data, list) else 1
                logger.info(f"[opencli] ✓ {count} items")
                return {"success": True, "data": data, "count": count}
            except json.JSONDecodeError:
                # 原始文本截断返回
                return {"success": True, "data": stdout[:8000], "format": "text"}
        
        except subprocess.TimeoutExpired:
            self.stats["errors"].append({"cmd": command, "error": "timeout"})
            return {"success": False, "error": f"超时 ({timeout}s)"}
        except Exception as e:
            self.stats["errors"].append({"cmd": command, "error": str(e)})
            return {"success": False, "error": str(e)}
    
    def _exec_opencli_help(self, args: dict) -> dict:
        """查看 OpenCLI 命令帮助"""
        command = args.get("command", "")
        
        full_cmd = f"{self.opencli_binary} {command} --help"
        logger.info(f"[opencli-help] $ {full_cmd}")
        
        try:
            proc = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
            )
            
            # --help 通常 exit 0，但有些命令 exit 1 也会打帮助
            output = (proc.stdout or "") + (proc.stderr or "")
            output = output.strip()
            
            if output:
                logger.info(f"[opencli-help] ✓ 返回 {len(output)} 字符")
                return {"success": True, "help": output[:5000]}
            else:
                return {"success": False, "error": "无帮助输出"}
        
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "查询帮助超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _exec_save_data(self, args: dict) -> dict:
        """保存数据到 JSON 文件"""
        category = args.get("category", "raw_materials")
        filename = args.get("filename", "unnamed")
        data = args.get("data")
        
        if data is None:
            return {"success": False, "error": "data 为空"}
        
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / category / f"{today}_{filename}.json"
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"success": False, "error": f"写入失败: {e}"}
        
        # 统计
        self.stats["files_saved"].append(str(filepath))
        if isinstance(data, list):
            self.stats["total_items"] += len(data)
        else:
            self.stats["total_items"] += 1
        
        # 记录已采集的话题（用于 compact 摘要）
        topic_title = ""
        if isinstance(data, dict):
            topic_title = data.get("title", filename)
        elif isinstance(data, list) and data:
            topic_title = data[0].get("title", filename) if isinstance(data[0], dict) else filename
        else:
            topic_title = filename
        self.stats["topics_done"].append({"title": topic_title, "category": category, "file": filepath.name})
        
        logger.info(f"[save] >> {filepath.name}")
        return {"success": True, "path": str(filepath)}
    
    def _exec_notify_user(self, args: dict) -> dict:
        """通知用户需要手动操作，阻塞等待确认"""
        message = args.get("message", "需要你的操作")
        platform = args.get("platform", "")
        
        separator = "=" * 50
        print(f"\n{separator}")
        print(f"[!] Agent 需要你的帮助!")
        if platform:
            print(f"[平台] {platform}")
        print(f"[操作] {message}")
        print(separator)
        
        user_input = input("完成操作后按回车继续（输入 skip 跳过）: ").strip()
        
        if user_input.lower() == "skip":
            logger.info(f"[notify] user skipped: {platform}")
            return {"success": True, "user_action": "skipped", "note": "用户选择跳过此步骤"}
        
        logger.info(f"[notify] user confirmed: {platform}")
        return {"success": True, "user_action": "confirmed", "note": "用户已完成操作"}
    
    # --- Util -----------------------------------------
    
    def _serialize_result(self, result: dict) -> str:
        """序列化 tool result，截断过大内容"""
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
        
        # OpenAI API tool result 限制（保守截断）
        if len(text) > 15000:
            # 保留 data 的前 N 条
            if "data" in result and isinstance(result["data"], list):
                truncated = result.copy()
                truncated["data"] = result["data"][:20]
                truncated["_truncated"] = True
                truncated["_total"] = len(result["data"])
                text = json.dumps(truncated, ensure_ascii=False, default=str)
            else:
                text = text[:15000] + "\n...(truncated)"
        
        return text
    
    def _compact_context(self, messages: list) -> list:
        """
        上下文压缩：把历史 messages 压缩成结构化进度摘要。
        
        摘要包含：
        - 已完成的平台
        - 已深挖的具体话题标题
        - 文件路径
        """
        if len(messages) <= 6:
            return messages
        
        system_msg = messages[0]
        
        # 按 category 分组已完成的话题
        topics_by_cat = {}
        for t in self.stats["topics_done"]:
            cat = t["category"]
            if cat not in topics_by_cat:
                topics_by_cat[cat] = []
            topics_by_cat[cat].append(t)
        
        # 构造进度摘要
        summary_parts = ["【进度更新】以下是你已完成的采集工作："]
        summary_parts.append(f"")
        summary_parts.append(f"已保存 {len(self.stats['files_saved'])} 个文件，共 {self.stats['total_items']} 条数据。")
        summary_parts.append(f"")
        
        if topics_by_cat.get("hot_topics"):
            summary_parts.append("## 已完成 - 热点话题 (hot_topics)")
            for t in topics_by_cat["hot_topics"]:
                summary_parts.append(f"  ✅ {t['title']} → {t['file']}")
        
        if topics_by_cat.get("ai_news"):
            summary_parts.append("## 已完成 - AI/科技 (ai_news)")
            for t in topics_by_cat["ai_news"]:
                summary_parts.append(f"  ✅ {t['title']} → {t['file']}")
        
        if topics_by_cat.get("raw_materials"):
            summary_parts.append("## 已完成 - 原始素材 (raw_materials)")
            for t in topics_by_cat["raw_materials"]:
                summary_parts.append(f"  ✅ {t['title']} → {t['file']}")
        
        if self.stats["errors"]:
            summary_parts.append(f"")
            summary_parts.append(f"遇到 {len(self.stats['errors'])} 个错误（已跳过）。")
        
        summary_parts.append(f"")
        summary_parts.append("请继续采集其他尚未保存的话题。不要重复上述已完成的内容。")
        
        progress_msg = {
            "role": "user",
            "content": "\n".join(summary_parts)
        }
        
        compacted = [system_msg, progress_msg]
        logger.info(f"[compact] 压缩上下文: {len(messages)} → {len(compacted)} 条消息")
        return compacted
