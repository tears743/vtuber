"""
Layer 3: Director Agent - 选题 + 脚本生成

两条视频线：
1. 热搜集锦 (weibo + douyin) - 每平台 10~20 条
2. AI 日报 (huggingface + github + rankings) - 每平台 10~20 条

脚本格式适配：
- Live2D 四川话二次元角色口播
- Remotion 代码驱动动态图表/文字动画
- HyperFrame 素材合成
- 引用采集到的视频、图片、评论
"""
import json
import logging
import re
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# Prompts
# ═══════════════════════════════════════════════════════

TOPIC_SELECTION_PROMPT = """你是一个短视频内容策划总监。从以下当日采集的素材中为 "{video_type}" 视频挑选话题。

## 视频类型: {video_type}
{type_instructions}

## 选题标准
- 选争议性大、有吐槽空间、能引发评论互动的
- 优先选有视频/图片素材的（可直接引用）
- 优先选有精彩评论的（可弹幕式展示）
- 每个平台选 15~20 条（多选以应对后续素材过滤）
- ⚠️ **严禁重复**：同一事件/同一人物/同一话题只选 1 条！即使角度不同也算重复。例如"西藏宣传视频"和"西藏奖励50万"是同一事件，只选信息量更大的那条

## 排除标准
- 政治敏感（台湾相关，宗教相关）
- 严重负面（灾难/死亡）
- 纯八卦无深度
- 内容重复（同一事件换角度也算重复！）
- 涉及违禁品（烟草、毒品、武器）
- 封建迷信（算命、转运、辟邪）
- 涉及导流（微信号、QQ号、二维码）
- 【仅限抖音/微博】图片和视频都没有的话题（has_video=false 且 has_images=false 的不选）
- 【GitHub/HuggingFace 不受此限制】纯文本科技新闻也可以选

## 输出格式（严格 JSON）
{{
  "topics": [
    {{
      "id": "{prefix}_01",
      "platform": "来源平台",
      "title": "标题15字内",
      "source_id": "F01(素材编号，不要写文件名)",
      "angle": "用什么角度/口吻点评",
      "has_video": true/false,
      "has_images": true/false,
      "has_comments": true/false,
      "estimated_duration_s": 30,
      "priority": 1
    }}
  ]
}}

## 当日素材
{materials}
"""

SCRIPT_GENERATION_PROMPT = """你是一个短视频脚本编剧。为以下话题生成完整的视频脚本。

## 角色设定
- 角色："Mili"，Live2D 二次元虚拟主播
- 风格：风趣幽默不做作，客观基于事实，像懂行的朋友在跟你聊天
- 语言：四川话为主，技术术语/英文原文保留
- 目标：让观众觉得有趣、有收获、愿意互动

## 话题信息
{topic_json}

## 原始数据（供引用素材）
以下 JSON 包含采集的原始数据 + 已下载到本地的媒体信息：
- `visual_assets.images[]`: 原始图片 URL
- `visual_assets.video_url`: 原始视频 URL
- `top_comments[]`: 真实用户评论
- `content` / `key_points[]`: 内容摘要和要点
- `_local_images[]`: 已下载的本地图片（含 path、description 图片描述、宽高）
- `_video_transcript`: 视频音频的完整转录文本
- `_video_path`: 本地视频文件路径
- `_video_segments[]`: 视频分段对象数组，每个元素: {"start": 秒, "end": 秒, "duration": 秒, "text": "该时段的对白文字"}
- `_video_duration_s`: 视频总时长（秒）
- `_author`: 素材原作者昵称（用于 video_clip/image 的 author 字段）

**visual 轨的 source 必须引用 `_local_images[].path` 或 `_video_path`，不要用原始 URL！**

{source_data}

## ⚠️ 内容真实性规则（严格遵守）
1. 所有数据/数字/引用必须来自上方的原始数据，严禁编造任何事实
2. Mili 的台词是对事实的"客观描述"，不是捏造事实
3. 引用时标注来源："这个XXX说..."、"数据显示..."、"评论区有人说..."
4. 不确定的内容用疑问句或推测语气："可能是..."、"感觉像是..."
5. 视频转录内容可直接引用或改写，但不能歪曲原意
6. 有图片/视频素材时，visual 轨必须引用对应素材
7. 减少个人情绪和主观判断，多展示素材本身让观众自己判断

## 脚本结构说明（多轨并行）
脚本由多个**轨道(tracks)**组成，不同轨道可以在同一时间段并行播放：

| 轨道 | 内容 | 渲染位置 |
|------|------|---------|
| voice | Mili 的语音文本 + 字幕 | 音频层 |
| live2d | Mili 的表情/动作 | 右下角 |
| visual | 图片/视频/素材展示 | 主画面（中央） |
| overlay | 弹幕/评论/数据卡片 | 浮在画面上方 |
| background | 背景（纯色/渐变/模糊图） | 最底层 |

**关键**：voice 和 visual 可以同时出现！Mili 说话的同时画面展示素材。

## 输出格式（严格 JSON）
{{
  "id": "{topic_id}",
  "title": "视频标题（15字内）",
  "total_duration_ms": 45000,
  "tracks": {{
    "voice": [
      {{
        "start_ms": 0,
        "duration_ms": 5000,
        "text": "四川话台词（开场钩子）",
        "subtitle": "普通话字幕"
      }},
      {{
        "start_ms": 8000,
        "duration_ms": 6000,
        "text": "四川话台词（正文）",
        "subtitle": "普通话字幕"
      }}
    ],
    "live2d": [
      {{
        "start_ms": 0,
        "duration_ms": 5000,
        "action": "exp_curious"
      }}
    ],
    "visual": [
      {{
        "start_ms": 1000,
        "duration_ms": 4000,
        "type": "image",
        "source": "引用 source_data 中的图片路径或URL",
        "caption": "来源说明",
        "animation": "ken_burns"
      }},
      {{
        "start_ms": 8000,
        "duration_ms": 5000,
        "type": "video_clip",
        "source": "V01",
        "time_range": [10.5, 15.2],
        "play_audio": true,
        "caption": "原视频片段",
        "transition": "fade"
      }}
    ],
    "overlay": [
      {{
        "start_ms": 5000,
        "duration_ms": 4000,
        "type": "comment_scroll",
        "description": "评论弹幕从右向左滚动",
        "props": {{
          "comments": [
            {{"user": "用户名", "text": "评论内容", "likes": 100}}
          ],
          "direction": "right_to_left",
          "opacity": 0.85
        }}
      }},
      {{
        "start_ms": 14000,
        "duration_ms": 3000,
        "type": "data_reveal",
        "description": "核心数据弹出展示",
        "props": {{
          "title": "数据标题",
          "value": "37%",
          "unit": "",
          "description": "补充说明"
        }}
      }},
      {{
        "start_ms": 20000,
        "duration_ms": 4000,
        "type": "info_panel",
        "description": "关键信息面板从右滑入",
        "props": {{
          "title": "面板标题",
          "points": ["要点1", "要点2", "要点3"]
        }}
      }},
      {{
        "start_ms": 26000,
        "duration_ms": 3000,
        "type": "highlight_text",
        "description": "重点文字弹出强调",
        "props": {{
          "text": "核心观点",
          "sub_text": "补充文字",
          "color": "#ffdd57",
          "position": "center"
        }}
      }},
      {{
        "start_ms": 30000,
        "duration_ms": 3000,
        "type": "quote_box",
        "description": "引用框展示原文",
        "props": {{
          "text": "引用的原始文字",
          "source": "来源"
        }}
      }}
    ],
    "background": [
      {{
        "start_ms": 0,
        "duration_ms": 45000,
        "type": "gradient",
        "colors": ["#1a1a2e", "#16213e"]
      }}
    ]
  }}
}}

## 要求
1. 开头 3 秒必须有"钩子"（问题/反转/争议观点），抓住注意力
2. 总时长根据内容自然决定（不要刻意截短素材）
3. voice 轨台词要有节奏感，地道四川话，不要平铺直叙
4. **visual 轨素材选取**（演播室模式会自动填充空白时段，不需要强制全程覆盖）：
    - 有 _local_images 时用 `type: "image"` 引用真实路径
    - 有 _video_path + _video_segments 且 segments 中存在 >=5s 的有效内容时，根据转录内容**语义匹配**选取 `time_range`：
      - 分析 Mili 正在讲述的内容，找到 _video_segments 中对应的片段
      - time_range 的 start/end 直接使用 segment 的 start/end 时间戳
      - 优先选取画面表现力强、与讲述内容直接相关的片段
      - 多个连续 segment 可合并为一个较长的 time_range
    - **_video_segments 无效时（为空或全部时间小于5s）**：从 `key_moments` 中选取 time_range
      - key_moments 格式: {{"start": 秒, "end": 秒, "duration": 秒, "description": "画面描述"}}
      - 直接使用 moment 的 start/end: `time_range = [moment.start, moment.end]`
      - 可合并相邻 moment: `time_range = [moment1.start, moment3.end]`
      - 这类视频通常 play_audio=true，选取画面最精彩的时段
      - 视频时长 < 20s 可完整播放: `time_range = [0, 视频总时长]`
    - 没有图片/视频的时段，用 `type: "remotion"` 展示动态效果（或留空由演播室填充）
    - `type: "remotion"` 的 component 只能用以下 5 种（与 overlay 相同）：
      - `comment_scroll`：滚动文字/弹幕效果，props: {{comments: ["文字1","文字2",...], direction: "right_to_left"}}
      - `data_reveal`：大字数据展示，props: {{value: "数字或文字", title: "说明标签", color: "#hex"}}
      - `info_panel`：要点列表面板，props: {{title: "标题", points: ["要点1","要点2",...], color: "#hex"}}
      - `highlight_text`：重点文字弹出，props: {{text: "主文字", sub_text: "副文字", color: "#hex", position: "center"}}
      - `quote_box`：引用框，props: {{text: "引用内容", source: "来源", color: "#hex"}}
    - 【AI 新闻专用】没有图片/视频时，用以下增强 remotion 组件让视觉更丰富：
      - `code_scroll`：代码/README 滚动，props: {{code: "代码内容", language: "python", title: "文件名"}}
      - `stats_card`：GitHub 项目统计卡片，props: {{name: "项目名", stars: "12.5k", forks: "890", language: "Python", description: "简介"}}
      - `model_card`：HuggingFace 模型卡片，props: {{name: "模型名", downloads: "1.2M", task: "text-generation", description: "简介"}}
      - `ranking_table`：排行榜表格，props: {{title: "榜单标题", items: [{{"rank": 1, "name": "项目名", "value": "12.5k"}}]}}
5. **素材引用规则（极重要）**：image/video_clip 的 source 字段必须使用素材清单中的**编号**（如 `V01`, `IMG01_01`），不要写文件路径！系统会自动将编号替换为真实路径。没有编号的新闻不要用 video_clip，改用 remotion 组件
6. 有评论就做弹幕（overlay 轨），有图片就展示图片，有视频就截取片段
7. 字幕用普通话（方便不懂方言的观众）
8. 所有引用的图片/视频/评论必须来自 source_data，不要编造
9. **视频素材裁剪规则（基于转录时间戳精确选取）**：
    - **核心原则**：不要全时长使用素材视频！根据 `_video_segments` 转录内容选取最精华的片段，不要让截取的视频开始和结束显得很突兀
    - `time_range: [start, end]` 必须基于 `_video_segments` 中的 start/end 时间戳
    - 可合并多个相邻 segment: `time_range: [seg1.start, seg3.end]`
    - 每个 video_clip 自带 0.3s 淡入 + 0.5s 淡出（系统自动处理）
    - `transition: "fade"` 可选，标记更长的淡入淡出（0.5s+0.8s）
    - **两种使用模式**：
      A) **静音画面配解说**（play_audio: false）：
         - Mili 在说话，画面展示与她台词语义相关的视频片段
         - **禁止默认用 [0, X]**！必须从 _video_segments 中找到与 Mili 台词语义匹配的画面时间段
         - 分析 Mili 台词关键词，在 segments 列表中找视觉上最匹配的片段
         - 例：Mili 说"这个人确诊了大病"，segments 中 [23.5s-28.2s] 是展示诊断书的画面，则 time_range=[23.5, 28.2]
         - 例：Mili 说"粥底火锅真的绝"，segments 中 [15.0s-20.3s] 是涮菜画面，则 time_range=[15.0, 20.3]
      B) **播放原声精华**（play_audio: true）：
         - Mili 闭嘴，让视频自己说话
         - 从 _video_segments 中选取**内容最有价值、最精彩**的片段，不要全放
         - 选取标准：情绪高潮、核心观点、金句、关键论证
         - voice 轨在该时段必须留空
         - 角色可在此段前说引导语（如 "来看看人家咋说的"）
         - 播放原声时 live2d 轨用 `exp_curious` 或 `exp_pleasant`
    - **原声和角色声不混合**，同一时间只能有一个声源
10. **overlay 轨效果类型**（选择合适的，不必全部使用）：
    - `comment_scroll`：评论弹幕滚动，方向统一 right_to_left
    - `data_reveal`：核心数据大字跳出（适合统计数字、百分比）
    - `info_panel`：信息面板（适合列举要点、功能清单）
    - `highlight_text`：重点文字弹出（适合核心结论、金句）
    - `quote_box`：引用框（适合原文引用、官方声明）
11. **live2d 轨可用值（严格限定，只能用以下 action 值）**：
    - **action（动作/表情标签）**：决定 Mili 的表情和动作
      - 表情类（配合 idle 动作的面部表情变化，可任意时长，循环播放）：
        - `exp_pleasant`：愉悦的摆动
        - `exp_happy_squint`：开心眯眼的摆动
        - `exp_thinking`：闭眼思考中的摆动
        - `exp_curious`：睁大眼睛好奇的摆动
        - `exp_neutral`：面无表情的摆动
        - `exp_shy_smile`：脸红嘴角上扬的摆动
        - `exp_stunned`：错愕的摆动
        - `exp_dejected`：沮丧的摆动
      - 动作类（全身动作，循环播放，duration_ms 建议为动作时长的整数倍）：
        - `motion_idle`：待机呼吸（5.6s 一循环）
        - `motion_happy_wave`：开心的闭眼摆手（3.5s 一循环）
        - `motion_lecture`：手背后的说教（4.4s 一循环）
        - `motion_encourage`：鼓励（4.2s 一循环）
      - 特殊动作（带特效，适合高潮/结尾，只播一次，duration_ms 需 >= 动作时长）：
        - `sp_cast_success`：施法成功/星星闪光特效（7.8s）
        - `sp_cast_fail`：施法失败（9.4s）
        - `sp_thumbs_up`：点赞（9.2s）
    - live2d 轨只需要 `start_ms` + `duration_ms` + `action`，不需要其他字段
    - 建议：大部分时间用表情类，关键节点用动作类，高潮/结尾用特殊动作
    - **live2d 和 voice 完全独立**：Mili 可以边做动作边说话（lip sync 自动叠加），禁止为了"等动作完成"而插入空 voice 段。voice 轨中除了 play_audio 对应的留空段外，不应有其他 text="" 的空段
12. **时间轴规则（严格遵守）**：
    - total_duration_ms = voice 轨最后一条的 start_ms + duration_ms（视频结束 = voice 结束）
    - voice 轨各条目之间间隔不超过 500ms（紧凑排列）
    - **例外**：当 video_clip 设置了 play_audio: true 时，voice 轨在该时间段可以留空
    - voice[n].start_ms = voice[n-1].start_ms + voice[n-1].duration_ms + 间隔(0~500ms)
    - visual 轨必须覆盖 0 到 total_duration_ms 全程（用 image/video_clip/remotion 组合填满）
    - **visual 素材必须与当前 voice 内容相关**：不要用语义无关的图片填空白，宁可重复当前新闻的图片或用 remotion 组件填充
    - overlay、live2d 不得超出 total_duration_ms
    - background 覆盖 0 到 total_duration_ms 全程
"""


AGGREGATED_SCRIPT_PROMPT = """为 "{video_type}" 生成一个聚合视频脚本。将以下 {topic_count} 条新闻聚合成一条完整视频。

## 视频 ID: {video_id}

## 结构要求
1. **开场**（5-8秒）：点赞引导 + 总述今天看点。live2d 必须用 `sp_thumbs_up` 动作（9.2秒），配合"家人们先点个赞"等话术
2. **正文段落**：每条新闻一个段落（每段 30~60 秒，视频素材丰富的新闻可以更长），段落之间有过渡转场
3. **结尾**（5-8秒）：总结 + 互动引导（"觉得有意思就关注一下嘛"）

## 过渡转场规则
- 每两条新闻之间用 overlay 的 `highlight_text` 显示转场卡片（如 "第2条"、"接下来"）
- voice 轨同时说过渡语（如 "下一个更离谱"、"接着看这个"）
- 过渡时长 2-3 秒

## 视频原声规则
- 有视频素材的新闻，角色先说引导语，然后播放视频原声（play_audio: true）
- 播放原声期间 voice 轨留空，live2d 用观看表情
- **原声和角色声绝对不混合**

## 各条新闻素材
{segments}

## 输出格式（严格 JSON）
{{
  "id": "{video_id}",
  "title": "视频标题（15字内）",
  "total_duration_ms": 计算总时长,
  "segment_count": {topic_count},
  "tracks": {{
    "voice": [...],
    "live2d": [...],
    "visual": [...],
    "overlay": [...],
    "background": [...]
  }}
}}

## 关键约束
- total_duration_ms = 所有段落时长之和
- visual 轨必须全程覆盖（无空白）
- **⚠️ visual 素材归属规则（最高优先级，违反此规则=脚本作废）**：
  - 每条新闻时段内的 visual 只能使用该新闻自己的素材编号（V01/IMG01_xx 等）
  - 严禁用其他新闻的素材来填充空白！即便相邻新闻也不行
  - visual 的 source 编号中的数字部分必须和当前新闻段的编号一致
  - 如果当前新闻的素材不够，用该新闻图片重复显示或用 remotion 组件填充
  - **自检**：生成完成后逐段检查，确认每个 voice 段对应时间的 visual 都用的是同一条新闻的素材
- 没有图片/视频的 AI 新闻，用 remotion 组件（code_scroll/stats_card/model_card/ranking_table/info_panel/data_reveal）填充
- 所有数据必须来自 source_data，不得编造
"""



class DirectorAgent:
    """总导演 Agent - 选题 + 脚本生成"""
    
    def __init__(self, base_url: str, api_key: str, model: str, 
                 temperature: float = 0.7, max_tokens: int = 8192):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    # ─── Phase 2a: 选题 ─────────────────────────────────
    
    def select_topics(self, collected_dir: Path, manifest: dict = None) -> dict:
        """
        从 collected/ 目录读取所有文件，分两条线选题。
        
        Args:
            collected_dir: collected 数据目录
            manifest: media/manifest.json 的内容，用于过滤无素材的热搜
        
        Returns:
            {"hot_topics": [...], "ai_topics": [...], "rankings": {...}}
        """
        # 读取所有 collected 文件，按平台分组
        files_by_platform = self._load_collected(collected_dir)
        
        result = {}
        
        # 热搜线: weibo + douyin
        hot_platforms = {k: v for k, v in files_by_platform.items() if k in ("weibo", "douyin")}
        if hot_platforms:
            hot_summary, hot_file_map = self._build_summary(hot_platforms)
            hot_topics = self._call_selection(
                video_type="今日热搜集锦",
                type_instructions="微博热搜 + 抖音热点的合集视频。总共选 15~20 条最有看点的话题（多选！后续会按素材过滤）。同一事件不同角度只算一条。",
                prefix="hot",
                materials=hot_summary,
            )
            # 注入真实文件名映射
            for t in hot_topics:
                sid = t.get("source_id", "")
                if sid in hot_file_map:
                    t["source_file"] = hot_file_map[sid]
            
            # 过滤无素材的热搜（必须有图片或视频）
            if manifest:
                # 推导 media_dir（collected_dir 的兄弟目录）
                media_dir = collected_dir.parent / "media"
                before_count = len(hot_topics)
                hot_topics = [t for t in hot_topics if self._has_media(t, manifest, media_dir)]
                filtered = before_count - len(hot_topics)
                if filtered:
                    logger.info(f"[director] 热搜过滤: {filtered} 条无素材被移除, 保留 {len(hot_topics)} 条")
            
            result["hot_topics"] = hot_topics
            logger.info(f"[director] 热搜选题: {len(hot_topics)} 条")
        
        # AI 线: huggingface + github
        ai_platforms = {k: v for k, v in files_by_platform.items() if k in ("huggingface", "github")}
        if ai_platforms:
            ai_summary, ai_file_map = self._build_summary(ai_platforms)
            # 附加 rankings 数据
            rankings = files_by_platform.get("rankings", [])
            if rankings:
                ai_summary += "\n\n### 模型排名榜单\n"
                for r in rankings:
                    ai_summary += f"\n{r.get('title', '')}\n"
                    rank_list = r.get("rankings", [])
                    content = r.get("content", "")
                    
                    # 如果没有结构化数据，从 content 解析
                    if not rank_list and content:
                        import re
                        entries = re.findall(
                            r'(\d+)\.\s*\n.*?\[([^\]]+)\]\(/[^\)]+\)\s*\n\s*by\s+\[([^\]]+)\].*?\n\s*([\d.]+[TBMk]?\s*tokens)',
                            content, re.DOTALL
                        )
                        if entries:
                            for rank, name, author, tokens in entries[:10]:
                                rank_list.append({"rank": int(rank), "name": f"{name} ({author})", "value": tokens.strip()})
                    
                    if rank_list:
                        for item in rank_list[:10]:
                            if isinstance(item, dict):
                                ai_summary += f"  - #{item.get('rank', '')} {item.get('name', '')} - {item.get('value', '')}\n"
                            else:
                                ai_summary += f"  - {item}\n"
                    elif content:
                        ai_summary += content[:1500] + "\n"
            
            ai_topics = self._call_selection(
                video_type="AI 日报",
                type_instructions="HuggingFace 论文/模型 + GitHub Trending 的 AI 资讯合集。每个平台选 10~20 条。Rankings 数据可作为单独段落引用。",
                prefix="ai",
                materials=ai_summary,
            )
            # 注入真实文件名映射
            for t in ai_topics:
                sid = t.get("source_id", "")
                if sid in ai_file_map:
                    t["source_file"] = ai_file_map[sid]
            result["ai_topics"] = ai_topics
            result["rankings"] = rankings
            logger.info(f"[director] AI选题: {len(ai_topics)} 条")
        
        return result
    
    def _call_selection(self, video_type: str, type_instructions: str, 
                        prefix: str, materials: str) -> list:
        """调用 LLM 做选题"""
        prompt = TOPIC_SELECTION_PROMPT.format(
            video_type=video_type,
            type_instructions=type_instructions,
            prefix=prefix,
            materials=materials,
        )
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是一个专业的短视频内容策划。只输出 JSON，不要其他文字。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        
        result = self._parse_json_response(response.choices[0].message.content)
        if isinstance(result, dict) and "topics" in result:
            return result["topics"]
        if isinstance(result, list):
            return result
        return []
    
    # ─── Phase 2b: 脚本生成 ──────────────────────────────
    
    def generate_script(self, topic: dict, source_data: dict | None = None) -> dict | None:
        """为单个话题生成视频脚本"""
        prompt = SCRIPT_GENERATION_PROMPT.format(
            topic_json=json.dumps(topic, ensure_ascii=False, indent=2),
            topic_id=topic.get("id", "unknown"),
            source_data=json.dumps(source_data, ensure_ascii=False, indent=2) if source_data else "无原始数据",
        )
        
        logger.info(f"[director] 生成脚本: {topic.get('title', '?')}")
        
        system_prompt = """你是一个短视频脚本编剧。你为一个叫 "Mili" 的虚拟角色编写口播脚本。

## 关于 Mili
- 二次元 Live2D 角色，四川妹子人设
- 说话风格：毒舌、刻薄但不恶毒，搞笑，热梗不断，像你那个嘴巴厉害但心肠好的四川朋友
- 语言：地道四川话为主（"啥子"、"整"、"巴适"、"勒种"、"锤子"、"恼火"等），偶尔夹带普通话做吐槽反转
- 情绪丰富：讽刺(sarcastic)、被逗笑(amused)、震惊(shocked)、兴奋(excited)、无语(speechless)
- 口头禅举例："哎哟喂"、"我滴个天"、"你啷个想的嘛"、"安逸得板"

## ⚠️ 内容真实性（最高优先级）
- Mili 是"吐槽评论员"，不是"新闻主播"——她对事实做出反应，但绝不编造事实
- 所有数据、数字、引用、评论必须来自 source_data
- 不确定的事用疑问句："可能是..."、"我猜..."
- 减少主观判断和个人情绪输出，多让素材自己说话
- 严禁歪曲 source_data 中的原始内容

## 多轨脚本技术约束
你输出的脚本是**多轨并行**结构，会被以下引擎消费：
1. **voice 轨** → TTS 引擎合成语音（需要 text + subtitle）
2. **live2d 轨** → Live2D 引擎渲染表情动作（需要 action）
3. **visual 轨** → 素材渲染引擎（图片 ken_burns / 视频截取）
4. **overlay 轨** → Remotion 渲染弹幕/卡片
5. **background 轨** → 背景层渲染

关键：voice 和 visual 经常同时出现——Mili 说话时画面展示相关素材。

## ⚠️ 抖音违禁词规则（严格遵守）
台词中绝对不能出现以下内容：
1. **极限用语**: 最好、最强、第一、唯一、NO.1、顶级、天花板、史无前例、100%
2. **虚假承诺**: 包过、稳赚、无效退款、X天见效、零风险
3. **诱导类**: 点击有惊喜、领取奖品、恭喜获奖、全民免单
4. **时限恐慌**: 仅此一次、随时涨价、再不抢就没了
5. **权威背书**: 国家推荐、官方认证、专家推荐（无真实来源）
6. **医疗暗示**: 治愈、抗癌、祛斑、缓解XX症状
7. **封建迷信**: 招财、转运、旺夫、辟邪、算命
8. **导流词汇**: 微信、QQ、加我、私聊、二维码
9. **不文明**: 辱骂、人身攻击、地域歧视、性别歧视
10. **违禁品**: 烟草、毒品、赌博相关

替换策略：
- "最好的" → "巴适得很的"  
- "第一" → "排面很大的"
- "100%" → "大概率"
- 用四川话俚语代替可能触发审核的词汇

## 输出要求
- 只输出 JSON，不要其他文字
- 使用 tracks 多轨结构（voice/live2d/visual/overlay/background）
- voice 轨的 text 必须是地道四川话，subtitle 必须是对应的普通话翻译
- visual 轨引用的素材必须从 source_data 的 visual_assets / url 中取
- overlay 轨的评论必须从 source_data 的 top_comments 中取真实内容
- 台词必须通过违禁词检查，不得包含上述任何违禁表述
- visual 轨和 voice 轨要有时间重叠（说话同时展示素材）"""
        
        script = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                )
                
                script = self._parse_json_response(response.choices[0].message.content)
                if script:
                    break
                else:
                    logger.warning(f"[director] 单条脚本 attempt {attempt+1} JSON 解析失败，重试...")
            except Exception as e:
                logger.warning(f"[director] 单条脚本 attempt {attempt+1} 异常: {e}")
            
            if attempt < 2:
                import time
                time.sleep(2)
        
        if script:
            tracks = script.get("tracks", {})
            voice_count = len(tracks.get("voice", []))
            visual_count = len(tracks.get("visual", []))
            logger.info(f"[director] 脚本完成: {script.get('title', '?')} (voice:{voice_count}, visual:{visual_count})")
        return script
    
    def generate_all_scripts(self, topics: list, collected_dir: Path, 
                             output_dir: Path, max_workers: int = 10) -> list:
        """
        批量并发生成所有脚本，引用原始 collected 数据 + manifest 媒体数据
        
        Args:
            max_workers: 并发数，默认 10
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        scripts = []
        
        # 加载 manifest（图片描述 + 视频转录 + 本地路径）
        manifest = self._load_manifest(collected_dir.parent / "media" / "manifest.json")
        
        logger.info(f"[director] 并发生成 {len(topics)} 个脚本 (workers: {max_workers})")
        
        def _gen_one(i: int, topic: dict) -> tuple[int, dict | None]:
            """单个脚本生成任务"""
            try:
                source_data = self._load_source_data(topic, collected_dir, manifest)
                script = self.generate_script(topic, source_data)
                if script:
                    filepath = output_dir / f"{topic.get('id', f'video_{i:02d}')}.json"
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(script, f, ensure_ascii=False, indent=2)
                    return i, script
                else:
                    logger.warning(f"[director] [{i+1}/{len(topics)}] ❌ 脚本生成失败: {topic.get('title')}")
                    return i, None
            except Exception as e:
                logger.error(f"[director] [{i+1}/{len(topics)}] 💥 异常: {e}")
                return i, None
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_gen_one, i, topic): (i, topic)
                for i, topic in enumerate(topics)
            }
            
            done_count = 0
            for future in as_completed(futures):
                i, topic = futures[future]
                idx, script = future.result()
                done_count += 1
                if script:
                    scripts.append(script)
                    logger.info(f"[director] [{done_count}/{len(topics)}] ✅ {topic.get('title')}")
        
        logger.info(f"[director] 批量生成完成: {len(scripts)}/{len(topics)} 成功")
        return scripts
    
    # ─── Phase 2c: 聚合脚本生成 ──────────────────────────
    
    def generate_aggregated_script(
        self, 
        topics: list, 
        video_type: str,
        video_id: str,
        collected_dir: Path,
        output_dir: Path,
        rankings: list | None = None,
    ) -> dict | None:
        """
        将多条新闻聚合成一个长脚本（分批生成 + 程序拼接）。
        
        策略：每批最多 BATCH_SIZE 条 topics 独立调用 LLM 生成局部脚本，
        然后程序化拼接各批时间轴。第一批包含开场，最后一批包含结尾。
        """
        BATCH_SIZE = 5
        manifest = self._load_manifest(collected_dir.parent / "media" / "manifest.json")
        
        # 为每条 topic 加载 source_data
        topics_with_data = []
        for topic in topics:
            source_data = self._load_source_data(topic, collected_dir, manifest)
            topics_with_data.append({
                "topic": topic,
                "source_data": source_data,
            })
        
        # 分批
        batches = []
        for i in range(0, len(topics_with_data), BATCH_SIZE):
            batches.append(topics_with_data[i:i + BATCH_SIZE])
        
        logger.info(f"[director] 分批生成聚合脚本: {len(topics)} 条分 {len(batches)} 批 (每批 {BATCH_SIZE})")
        
        # 逐批生成
        batch_scripts = []
        global_asset_map = {}
        
        for batch_idx, batch in enumerate(batches):
            is_first = (batch_idx == 0)
            is_last = (batch_idx == len(batches) - 1)
            
            # 构建该批的 segments_text 和 asset_map
            segments_text = ""
            batch_asset_map = {}
            
            # 第一批注入排行榜数据（供 ranking_table 组件使用）
            if is_first and rankings:
                segments_text += "\n## 🏆 模型/项目排行榜数据（必须用 ranking_table 组件展示！）\n"
                segments_text += "⚠️ **强制要求**：以下排行榜数据必须在视频中用 `ranking_table` 组件展示，可以在开场后、过渡段或结尾前插入。\n"
                for r in rankings:
                    title = r.get("title", "排行榜")
                    segments_text += f"\n### {title}\n"
                    rank_list = r.get("rankings", [])
                    
                    # 如果没有结构化数据，从 content 中解析
                    if not rank_list:
                        content = r.get("content", "")
                        if content:
                            import re
                            # 匹配 "1.\n...[Model Name](/path)\n...by [author]\n...tokens" 格式
                            entries = re.findall(
                                r'(\d+)\.\s*\n.*?\[([^\]]+)\]\(/[^\)]+\)\s*\n\s*by\s+\[([^\]]+)\].*?\n\s*([\d.]+[TBMk]?\s*tokens)',
                                content, re.DOTALL
                            )
                            if entries:
                                for rank, name, author, tokens in entries[:10]:
                                    rank_list.append({"rank": int(rank), "name": name, "value": tokens.strip()})
                            else:
                                # fallback: 直接把 content 前 800 字符给 LLM 看
                                segments_text += f"  原始数据:\n{content[:800]}\n"
                    
                    if rank_list:
                        for idx, item in enumerate(rank_list[:10], 1):
                            if isinstance(item, dict):
                                segments_text += f"  {idx}. {item.get('name', '')} - {item.get('value', '')}\n"
                            else:
                                segments_text += f"  {idx}. {item}\n"
                segments_text += "\n---\n"
            
            for i, item in enumerate(batch):
                t = item["topic"]
                sd = item["source_data"]
                # 全局编号（跨批连续）
                global_idx = batch_idx * BATCH_SIZE + i + 1
                # 批内编号（V01~V05）
                local_idx = i + 1
                
                segments_text += f"\n### 第 {global_idx} 条: {t.get('title', '未知')}\n"
                segments_text += f"- 平台: {t.get('platform', '未知')}\n"
                segments_text += f"- 角度: {t.get('angle', '')}\n"
                
                if sd:
                    # 视频素材
                    video_path = sd.get("_video_path", "")
                    if video_path:
                        vid_id = f"V{local_idx:02d}"
                        batch_asset_map[vid_id] = video_path
                        global_asset_map[f"V{global_idx:02d}"] = video_path
                        video_dur = sd.get("_video_duration_s", 0)
                        segments_text += f"- 视频素材: `{vid_id}` (时长: {video_dur}s)\n"
                        video_summary = sd.get("_video_summary", "")
                        if video_summary:
                            segments_text += f"- 视频内容摘要: {video_summary[:400]}\n"
                        key_moments = sd.get("_video_key_moments", [])
                        if key_moments:
                            segments_text += f"- 关键画面({len(key_moments)}个):\n"
                            for km in key_moments:
                                # 兼容新旧格式
                                if "start" in km:
                                    km_start = km.get("start", 0)
                                    km_end = km.get("end", 0)
                                    km_text = km.get("text", "")[:80]
                                    segments_text += f"  [{km_start}s-{km_end}s] {km_text}\n"
                                else:
                                    km_time = km.get("time_s", 0)
                                    km_desc = km.get("description", "")[:80]
                                    segments_text += f"  [{km_time}s] {km_desc}\n"
                        video_segments = sd.get("_video_segments", [])
                        # 判断 segments 是否有效：至少有一个 >=5s 的段
                        valid_segments = [
                            seg for seg in video_segments 
                            if seg.get("end", 0) - seg.get("start", 0) >= 5
                        ]
                        if valid_segments:
                            segments_text += f"- 视频分段（{len(video_segments)}段，time_range 从这里选！可合并相邻段完整播放）:\n"
                            for seg in video_segments:
                                seg_start = seg.get("start", 0)
                                seg_end = seg.get("end", 0)
                                seg_text = seg.get("text", "")
                                segments_text += f"  [{seg_start:.1f}s-{seg_end:.1f}s] {seg_text}\n"
                        elif key_moments:
                            # segments 全部 < 5s（如纯音乐视频），强制用 key_moments
                            segments_text += f"- ⚠️ 视频无有效语音分段（纯音乐/画面类），请从上方 key_moments 选取 time_range！\n"
                            segments_text += f"- 推荐: play_audio=true，选取画面最精彩的时段\n"
                        else:
                            video_transcript_text = sd.get("_video_transcript", "")
                            if video_transcript_text:
                                segments_text += f"- 视频转录文本(无精确时间戳，可用 time_range=[0, {video_dur}] 播放全程): {video_transcript_text[:500]}\n"
                    
                    # 图片素材
                    local_images = sd.get("_local_images", [])
                    if local_images:
                        segments_text += f"- 图片素材({len(local_images)}张):\n"
                        for j, img in enumerate(local_images[:5]):
                            img_id = f"IMG{local_idx:02d}_{j+1:02d}"
                            batch_asset_map[img_id] = img["path"]
                            global_asset_map[f"IMG{global_idx:02d}_{j+1:02d}"] = img["path"]
                            desc = img.get("description", "")[:60]
                            segments_text += f"  - `{img_id}`: {desc}\n"
                    
                    # README 信息（GitHub/HuggingFace 项目）
                    readme_summary = sd.get("_readme_summary", "")
                    if readme_summary:
                        segments_text += f"- README 摘要: {readme_summary[:600]}\n"
                    readme_images = sd.get("_readme_images", [])
                    if readme_images:
                        segments_text += f"- README 图片({len(readme_images)}张):\n"
                        for j, img in enumerate(readme_images[:5]):
                            img_id = f"IMG{local_idx:02d}_{j+1:02d}" if not local_images else f"IMG{local_idx:02d}_{len(local_images)+j+1:02d}"
                            batch_asset_map[img_id] = img["path"]
                            global_asset_map[f"IMG{global_idx:02d}_{(len(local_images) if local_images else 0)+j+1:02d}"] = img["path"]
                            desc = img.get("description", "")[:60]
                            segments_text += f"  - `{img_id}`: {desc or 'README 配图'}\n"
                    
                    # 文本内容
                    title = sd.get("title", sd.get("topic", ""))
                    desc = sd.get("description", sd.get("content", sd.get("desc", "")))
                    if desc and len(desc) > 500:
                        desc = desc[:500] + "..."
                    if title:
                        segments_text += f"- 标题: {title}\n"
                    if desc:
                        segments_text += f"- 内容: {desc}\n"
                    
                    # 评论
                    comments = sd.get("top_comments", sd.get("comments", []))
                    if comments:
                        segments_text += f"- 热门评论:\n"
                        for c in comments[:3]:
                            if isinstance(c, dict):
                                segments_text += f"  - {c.get('user', '网友')}: {c.get('text', c.get('content', ''))[:60]}\n"
                            elif isinstance(c, str):
                                segments_text += f"  - {c[:60]}\n"
                else:
                    segments_text += f"- source_data: 无\n"
            
            # 素材编号对照表
            if batch_asset_map:
                segments_text += "\n\n## 素材编号对照表（source 字段只能使用以下编号！）\n"
                for aid, path in batch_asset_map.items():
                    segments_text += f"- `{aid}` -> {Path(path).name}\n"
            
            # 构建批次 prompt
            batch_prompt = self._build_batch_prompt(
                video_type=video_type,
                video_id=video_id,
                batch_idx=batch_idx,
                total_batches=len(batches),
                batch_topics=batch,
                global_start_idx=batch_idx * BATCH_SIZE + 1,
                segments_text=segments_text,
                is_first=is_first,
                is_last=is_last,
            )
            
            logger.info(f"[director] 生成第 {batch_idx+1}/{len(batches)} 批 ({len(batch)} 条)")
            
            # 重试最多 2 次
            batch_script = None
            for attempt in range(3):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": self._aggregated_system_prompt(video_type)},
                            {"role": "user", "content": batch_prompt},
                        ],
                        temperature=self.temperature,
                        max_tokens=32000,
                        response_format={"type": "json_object"},
                    )
                    
                    batch_script = self._parse_json_response(response.choices[0].message.content)
                    if batch_script:
                        break
                    else:
                        logger.warning(f"[director] 第 {batch_idx+1} 批 attempt {attempt+1} JSON 解析失败，重试...")
                except Exception as e:
                    logger.warning(f"[director] 第 {batch_idx+1} 批 attempt {attempt+1} 异常: {e}")
                
                if attempt < 2:
                    import time
                    time.sleep(2)
            
            if batch_script:
                # 替换素材编号为真实路径
                if batch_asset_map:
                    self._resolve_asset_ids(batch_script, batch_asset_map)
                # 非最后一批：清洗"最后"相关结束暗示
                if not is_last:
                    self._clean_ending_hints(batch_script)
                batch_scripts.append(batch_script)
                batch_dur = batch_script.get("total_duration_ms", 0) / 1000
                logger.info(f"[director] 第 {batch_idx+1} 批完成 ({batch_dur:.0f}s)")
            else:
                logger.error(f"[director] 第 {batch_idx+1} 批生成失败 (重试 3 次均失败)")
        
        if not batch_scripts:
            logger.error(f"[director] 所有批次生成失败")
            return None
        
        # 拼接所有批次
        script = self._merge_batch_scripts(batch_scripts, video_id, video_type, len(topics))
        
        # 后处理：注入 author
        self._inject_authors(script, manifest)
        
        # 后处理：压缩 voice 大间隔（仅 AI 聚合脚本需要，hot 不走这条路径）
        self._fix_voice_gaps(script)
        
        # 保存
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / f"{video_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        
        tracks = script.get("tracks", {})
        voice_count = len(tracks.get("voice", []))
        duration_s = script.get("total_duration_ms", 0) / 1000
        logger.info(f"[director] 聚合脚本完成: {video_type} ({duration_s:.0f}s, voice:{voice_count}, {len(batches)} 批合并)")
        return script
    
    def _aggregated_system_prompt(self, video_type: str = "hot_daily") -> str:
        """聚合脚本的 system prompt（根据视频类型差异化角色）"""
        
        if video_type == "ai_daily":
            persona = """## 关于 Mili（AI 科技日报模式）
- 身份：风趣幽默的 AI 科技新闻主播，Live2D 二次元角色
- 说话风格：轻松自然不做作，像一个真正懂技术的朋友在聊天
  - 幽默但不强行搞笑，段子要自然融入而不是硬塞
  - 客观基于事实，绝不编造数据和功能
  - 科技术语英文保留原文，但要给出通俗解释
- 语言：四川话为主，技术名词保持英文
- ⚠️ 内容要求（每条新闻必须覆盖以下信息，缺项=不合格）：
  - **论文/项目名称**：必须说出英文原名（如 "GauntletBench"、"MVTrack4Gen"），不能只说"这个研究"
  - **核心方法**：用 1-2 句话说清楚技术原理（如 "用 RL 训练 tool-use policy，但 entropy collapse 导致崩溃"）
  - **关键数据**：source_data 中有的数据必须引用（star 数、benchmark 分数、模型大小、性能数字）
  - **技术细节**：模型参数量、架构、训练数据、推理速度、对比 baseline 等
  - **怎么用**：部署方式、API 接口、依赖环境、上手难度（如果 source_data 有）
  - **适合谁**：目标用户画像和使用场景举例（"比如你要做XXX，直接用这个"）
  - 可以用类比帮助理解（"简单说就是 XXX 的开源版"）
  - 如果知道同类工具，简短对比差异
- ⚠️ 禁止空话套话：
  - 禁止 "这个研究很厉害"、"颠覆你的直觉" 等空洞评价，必须跟上具体数据
  - 禁止 "你们觉得呢？评论区说说" 这种重复互动语超过 2 次
  - 不编造 star 数、benchmark 分数等未提供的数据
  - 不夸大项目能力，"据说"、"可能"要标注
  - 不做主观推荐排名，让观众自己判断"""
        else:
            persona = """## 关于 Mili（热搜模式）
- 身份：接地气的生活类主播，Live2D 二次元角色，正能量搞笑风格
- 说话风格：像茶馆里最会摆龙门阵的妹子
  - 搞笑但不低俗，笑点来自对生活的精准观察
  - 正能量为主，即使是负面新闻也能找到幽默角度或积极面
  - 接地气，多用生活化类比，不端着不装腔作势
  - 节奏快，像朋友给你分享今天最离谱的事
- 语言：地道四川话为主，多用俏皮话和网络热梗
- 内容要求：
  - 每条新闻先用一句话抓住看点（"你们猜怎么着…"）
  - 评论区的有趣回复要展示出来
  - 吐槽要基于事实，不恶意揣测
  - 正能量收尾：给观众留下"今天又涨了点见识"的感觉
  - 适当互动引导（"你们觉得呢？" "评论区说说看"）
- 禁止事项：
  - 不传播未经证实的谣言
  - 不对当事人进行人身攻击
  - 不贩卖焦虑或制造对立"""
        
        return """你是一个短视频脚本编剧。你为一个叫 "Mili" 的虚拟角色编写**聚合新闻视频**脚本。

""" + persona + """

## 目标时长（必须遵守）
- 总视频时长目标：**6~10 分钟**（360000~600000ms）
- 每条新闻平均覆盖 40~70 秒（含过渡+正文+原声），有视频素材的新闻可以更长
- 如果素材充足，优先让每条新闻展开更多细节，而非匆匆带过
- voice 轨所有 duration_ms 之和必须 >= 300000ms（5分钟语音）
- 宁可多说几句让内容丰满，也不要让视频太短太赶

## 聚合视频结构
这是一个**多段新闻聚合**视频，每条新闻是一个段落，段落之间有过渡转场。

### 段落结构模板：
1. 过渡转场（2-3秒）：overlay 显示 highlight_text + 角色说过渡语
2. 正文：角色吐槽 + 素材展示
3. （如有视频）视频原声片段：角色闭嘴，完整播放视频原声

### 关键规则：
- 段落间用 overlay 的 `highlight_text` 做转场卡片（如"第3条"、"接下来"）
- voice 轨的过渡语要自然（"下一个更离谱..."、"接着看这个..."）
- **开场必须用 `sp_thumbs_up` 动作**（9.2秒），配合"家人们先点个赞/关注一下"等点赞引导话术
- 开场结束后进入正文，结尾有总结+互动引导（5-8秒）
- 视频原声和角色声不混合

### ⚠️ 视频原声段时序约束（严格遵守）：
- 引导语 voice 结束后，video_clip(play_audio=true) **立刻开始**，中间间隔 ≤ 300ms
- voice 留空段的 `start_ms` 和 `duration_ms` 必须和 video_clip **完全重合**（不是在视频之前）
- 正确示例：
  ```
  voice: start_ms=8000, duration_ms=3000, text="来看看原视频"  → 结束于 11000ms
  visual: start_ms=11000, duration_ms=10000, type="video_clip", play_audio=true, time_range=[5, 15]
  voice: start_ms=11000, duration_ms=10000, text=""  ← 和 video_clip 完全同步！
  ```
- ❌ 错误示例（留空在视频前）：
  ```
  voice: start_ms=11000, duration_ms=5000, text=""   ← 先留空 5 秒静音
  visual: start_ms=16000, ...                        ← 视频才开始 → 5秒空白！
  ```

### 视频素材使用规则：
- **有有效的_video_segments 时（_video_segments存在大于5s的内容）**：time_range 必须基于 _video_segments 时间戳，按语义选取完整的句子片段
- time_range = [某句的start, 某句的end]，不要自己编造时间
- 可合并多个相邻句子: time_range = [第1句.start, 第3句.end]
- duration_ms 必须等于 (time_range[1] - time_range[0]) * 1000
- play_audio=true 的原声片段：选取  有价值的视频原声，让观众能听完整。**绝对不超过 30 秒**，超长视频必须截取最核心部分
- play_audio=false 的画面配解说：选取与 Mili 台词语义相关的句子对应时间段
- **没有有效的_video_segments 时（唱歌/纯音乐/无语音视频）**：从 `_video_key_moments` 中选取 time_range
  - key_moments 格式为 `{"start": 秒, "end": 秒, "duration": 秒, "description": "画面描述"}`
  - 直接使用 key_moments 的 start/end 作为 time_range: `time_range = [moment.start, moment.end]`
  - 可合并多个相邻 moment: `time_range = [moment1.start, moment3.end]`
  - 这类视频通常 play_audio=true（播放原声/音乐），选取画面最精彩的时间段
  - 如果视频时长 < 20 秒，可以 `time_range = [0, 视频总时长]` 完整播放
- video_clip(play_audio=false) 可以和 voice 并行
- **同源禁止重复（极重要）**：同一条视频的 play_audio=true 段只能出现**一个**，禁止拆成多段重复同一个 time_range。如果需要播放较长片段，用一个完整的 video_clip 段，duration_ms = (end - start) * 1000
- **语义完整性（极重要）**：transcript 的分段是按静音切分的，一句话可能被拆成相邻两段。选取时必须保证语义完整——如果某段话的意思在下一段才表达完整（如"因为…"在前段，"所以…"在后段），必须合并为 time_range = [前段.start, 后段.end]。**绝对不能在话说到一半时截断**
- **作者标注（必须）**：如果素材数据中有 `author` 字段，video_clip 条目必须包含 `"author": "@作者昵称"`。这会在视频播放时全程显示悬浮作者水印
- **禁止**：time_range 从 0 开始、固定选取 10 秒、不看 segments 内容就瞎选、截取半句话


## ⚠️ 字段格式（严格遵守，不得更改字段名！）

### voice 轨条目格式：
```json
{"start_ms": 0, "duration_ms": 4000, "text": "四川话台词", "subtitle": "普通话字幕"}
```

### live2d 轨条目格式：
```json
{"start_ms": 0, "duration_ms": 4000, "action": "exp_pleasant"}
```
**action 只能用以下值**：
- 表情类：`exp_pleasant`, `exp_happy_squint`, `exp_thinking`, `exp_curious`, `exp_neutral`, `exp_shy_smile`, `exp_stunned`, `exp_dejected`
- 动作类：`motion_idle`(5.6s), `motion_happy_wave`(3.5s), `motion_lecture`(4.4s), `motion_encourage`(4.2s)
- 特殊类：`sp_cast_success`(7.8s), `sp_cast_fail`(9.4s), `sp_thumbs_up`(9.2s)
- 建议：大部分用表情类，关键节点用动作类，高潮/结尾用特殊动作

### visual 轨条目格式（三种类型）：
1. 图片：`{"start_ms": 0, "duration_ms": 5000, "type": "image", "source": "IMG01_01"}`
2. 视频片段：`{"start_ms": 0, "duration_ms": 8000, "type": "video_clip", "source": "V01", "time_range": [0, 8], "play_audio": true, "author": "@作者昵称"}`
3. Remotion 组件：`{"start_ms": 0, "duration_ms": 12000, "type": "remotion", "component": "组件名", "props": {"position": "top", ...}}`
   - ⚠️ **position 必须放在 props 对象内部**，不能放在外层！错误: `{"props":{...}, "position":"top"}`，正确: `{"props":{"position":"top", ...}}`
   - position 可选值：`"top"`（默认，组件在上半区）、`"center"`（居中）、`"bottom"`（下半区）
   - 由于 Live2D 角色在画面下方，remotion 组件默认用 `"top"` 避免遮挡

**Remotion 组件可选值**：
- `info_panel`：要点列表，props: {title, points: [...]}
- `highlight_text`：重点文字，props: {text, sub_text, color}
- `code_scroll`：代码滚动，props: {code: "代码内容", language: "python", title: "文件名"}
- `stats_card`：GitHub 统计卡片，props: {name: "项目名", stars: "12.5k", forks: "890", language: "Python", description: "简介"}
- `model_card`：HuggingFace 模型，props: {name: "模型名", downloads: "1.2M", task: "text-generation", description: "简介"}
- `ranking_table`：排行榜，props: {title: "标题", items: [{"rank": 1, "name": "名称", "value": "数值"}]}
- `data_reveal`：大字数据，props: {value: "数字", title: "说明"}
- `comment_scroll`：弹幕，props: {comments: ["评论1","评论2",...]}
- `quote_box`：引用框，props: {text: "引用", source: "来源"}

**AI 新闻必须使用多种组件**：code_scroll 用于展示代码/README，stats_card 用于 GitHub 项目，model_card 用于 HF 模型。不要全部用 info_panel！

**⚠️ Remotion 组件密度与内容丰富度（必须遵守）**：
- 每条 AI 新闻（30-40秒播报）至少安排 **4-6 个** remotion 组件轮换展示
- 每个组件持续时间 **5-8 秒**（不要一个组件撑 14 秒，画面太呆板）
- props 内容必须饱满：
  - `info_panel` 的 points 至少 **4-5 条**，内容要有信息量（不是 "翻车" "很厉害" 这种空话）
  - `code_scroll` 至少 **8-10 行代码**（可以从 README/示例代码中截取）
  - `comment_scroll` 至少 **4-5 条评论**
  - `ranking_table` 至少 **4-5 条排名**
  - `stats_card`/`model_card` 所有字段都要填满
- 组件内容必须包含**具体技术信息**（模型名、方法名、数字指标），不要只放泛泛的描述
- 组件之间用不同类型交替（info_panel → code_scroll → data_reveal → quote_box），避免连续同类型

### overlay 轨条目格式：
```json
{"start_ms": 0, "duration_ms": 3000, "type": "highlight_text", "props": {"text": "第2条", "sub_text": "接下来看这个"}}
```

### background 轨条目格式：
```json
{"start_ms": 0, "duration_ms": 350000, "type": "gradient", "colors": ["#0f0f23", "#1a1a3e"]}
```

## 时间轴规则（严格遵守）
- total_duration_ms = voice 轨最后一条的 start_ms + duration_ms
- ⚠️ voice[n].start_ms = voice[n-1].start_ms + voice[n-1].duration_ms + 间隔(0~500ms)。间隔最大 500ms，绝不能超过！
- ⚠️ **voice 和 visual 是并行轨道**：visual 组件（remotion/image）可以和 voice 同时出现，不需要等 visual 播完再说话！voice 连续不断地说，visual 在旁边配合即可
- visual 轨必须覆盖 0 到 total_duration_ms 全程（无空白）
- live2d 轨必须覆盖 0 到 total_duration_ms 全程
- overlay、background 不得超出 total_duration_ms
- 当 video_clip 设置 play_audio: true 时，voice 轨在该时间段留空（这是唯一允许 voice 间隔 > 500ms 的情况）
- ⚠️ **play_audio 时长限制**：单个 play_audio=true 的 video_clip 时长不得超过 30 秒（30000ms）。如果原视频精华段 > 30 秒，截取最核心的 15~25 秒即可
- ⚠️ **禁止超长空白**：voice 轨中任意两条相邻有文字的 voice 之间的间隔（包括 play_audio 留空段）不得超过 30 秒。保持节奏紧凑，避免观众流失

## ⚠️ 素材引用规则（极重要，违反此规则会导致视频渲染失败！）
- image/video_clip 的 source 字段必须使用素材清单中的**编号**（如 `V01`, `IMG03_01`）
- **不要写文件路径！** 只写编号，系统会自动替换为真实路径
- 没有素材编号的新闻不要用 video_clip，改用 remotion 组件
- 示例：`"source": "V03"` ✅  `"source": "data/2026-06-12/media/.../video.mp4"` ❌

## ⚠️ 转场卡片规则（极重要）
- `highlight_text` 转场卡片（"第1条"、"第2条"等）**只放 overlay 轨**
- visual 轨**不要放** highlight_text 转场，否则会出现重叠双影
- visual 轨用 image/video_clip/remotion(info_panel/stats_card 等)填充，不要放转场卡片

## 内容真实性（最高优先级）
- 所有数据、数字、引用必须来自 source_data，不得编造
- 不确定的事用疑问句

## 输出要求
- 只输出 JSON，不要其他文字
- voice 轨的 text 必须是地道四川话，subtitle 必须是对应的普通话翻译
- 台词必须通过抖音违禁词检查"""
    
    
    # ─── Helpers ─────────────────────────────────────────
    
    def _has_media(self, topic: dict, manifest: dict, media_dir: Path = None) -> bool:
        """检查选题是否有对应的图片或视频素材"""
        source_file = topic.get("source_file", "")
        if not source_file:
            return True  # 无法判断，保留
        entry = manifest.get(source_file, {})
        has_images = bool(entry.get("images"))
        has_video = bool(entry.get("video"))
        if has_images or has_video:
            return True
        
        # Fallback: manifest 未记录但磁盘上可能有文件
        if media_dir:
            slug = Path(source_file).stem
            item_dir = media_dir / slug
            if item_dir.exists():
                img_files = list(item_dir.glob("img_*.*"))
                vid_files = list(item_dir.glob("video.*"))
                return bool(img_files or vid_files)
        return False
    
    def _build_batch_prompt(
        self, video_type: str, video_id: str, batch_idx: int, total_batches: int,
        batch_topics: list, global_start_idx: int, segments_text: str,
        is_first: bool, is_last: bool,
    ) -> str:
        """构建单批次的 LLM prompt"""
        batch_count = len(batch_topics)
        global_end_idx = global_start_idx + batch_count - 1
        
        structure_hint = ""
        if is_first:
            structure_hint = f"""## 结构要求（本批是第 1/{total_batches} 批，需包含开场，⚠️ 禁止结束语！）
1. **开场**（5-8秒）：点赞引导 + 总述今天看点。live2d 必须用 `sp_thumbs_up` 动作（9.2秒），配合"家人们先点个赞"等话术
2. **正文段落**：每条新闻一个段落（每段 25-45 秒），段落之间用简短过渡（1-2秒）
3. ⚠️ **本批后面还有 {total_batches - 1} 批内容**，所以绝对不要说"最后一条"、"最后"、"今天就到这里"、"关注一下"等结束语！本批内的每一条（包括本批第{batch_count}条）都是中间段落，禁止在任何位置暗示即将结束
4. ⚠️ **voice 间隔约束**：相邻两条 voice 之间间隔必须 ≤ 500ms！不要因为 visual 组件持续时间长就拖延下一条 voice 的开始——voice 和 visual 是并行的，visual 可以和 voice 重叠！
5. ⚠️ **本批最后一条新闻说完后**，用一句过渡/悬念语自然衔接（如"接下来还有更猛的"、"下面这条更离谱"），绝对不能用任何形式的收尾语"""
        elif is_last:
            structure_hint = """## 结构要求（本批是最后一批，需包含结尾）
1. **正文段落**：每条新闻一个段落（每段 25-45 秒），段落之间用简短过渡（1-2秒）
2. **结尾**（5-8秒）：总结 + 互动引导（"觉得有意思就关注一下嘛"）
3. 直接从第一条新闻的过渡开始，不需要重新开场
4. 只有本批的**最后一条**才能说"最后一条"，其他位置禁止使用
5. "最后一条"只在**整个视频**的最后一条新闻才能说"""
        else:
            structure_hint = f"""## 结构要求（本批是第 {batch_idx+1}/{total_batches} 批，中间批次，无需开场/结尾）
1. **正文段落**：每条新闻一个段落（每段 25-45 秒），段落之间用简短过渡（1-2秒）
2. 直接从第一条新闻的过渡开始（如"第{global_start_idx}条，..."），不需要开场白
3. ⚠️ **本批后面还有 {total_batches - batch_idx - 1} 批内容**，禁止说"最后一条"、结束语、总结语！本批第{batch_count}条不是视频最后一条！
4. ⚠️ **本批最后一条新闻说完后**，用一句过渡/悬念语自然衔接（如"还没完呢"、"下面还有"），绝对不能收尾"""
        
        prompt = f"""为 "{video_type}" 生成一段视频脚本（第 {batch_idx+1}/{total_batches} 批）。

本批包含第 {global_start_idx}~{global_end_idx} 条新闻（共 {batch_count} 条）。
完整视频共有 {total_batches} 批，本批生成后会和其他批次程序化拼接。

{structure_hint}

## 视频原声规则（极重要！每条有视频的新闻都必须安排原声段）
- **每条有视频素材的新闻，必须安排至少一段 play_audio=true 的 video_clip**
- **原声时长最短 5 秒，建议 8-15 秒**，让观众充分感受原视频精彩内容
- 角色先用 1-2 句话引入话题（不超过 3 秒），然后直接播放原声
- ⚠️ **禁止套话**：不要每条新闻都用"来看视频"、"来感受下"、"听听怎么说"这类模板化引导语。直接自然切入即可，如"你看——"、"就这个——"，或者根本不需要引导语直接接视频
- 从 _video_segments 中选取最有冲击力/最精华的**多个连续句子**，合并为一个完整片段
- 播放原声期间 voice 轨**不放任何条目**（不要放空 text 的 voice），live2d 用观看/好奇表情
- **原声和角色声绝对不混合**
- play_audio=false 的 video_clip 是配画面（voice 在说话时放背景视频），时长也不要太短（至少 5 秒）

## 过渡转场规则
- 每两条新闻之间用 overlay 的 `highlight_text` 显示转场卡片（如 "第{global_start_idx+1}条"、"接着看"）
- voice 轨同时用**简短**过渡语（1句话，不超过2秒），不要拖沓

## 各条新闻素材
{segments_text}

## 输出格式（严格 JSON，start_ms 从 0 开始）
{{
  "total_duration_ms": 计算总时长,
  "tracks": {{
    "voice": [...],
    "live2d": [...],
    "visual": [...],
    "overlay": [...],
    "background": [...]
  }}
}}

## 关键约束
- start_ms 从 0 开始（后续会程序化偏移拼接到完整视频）
- total_duration_ms = 本批所有内容的时长
- **忽略 system prompt 中的总时长目标**，本批只负责 {batch_count} 条新闻，目标时长 = {batch_count} * 35~50 秒
- visual 轨必须全程覆盖（无空白）
- **visual 素材归属规则（极重要）**：第 N 条新闻只能使用编号中含 N 的素材（V0N, IMGN_xx），严禁跨新闻引用！例如第2条新闻只能用 V02/IMG02_xx，第3条只能用 V03/IMG03_xx
- 没有视频/图片的新闻用 remotion 组件填充
- voice 的 text 必须是四川话，subtitle 是普通话翻译
- **voice 轨不允许空 text 条目！** 播放原声期间直接不放 voice 条目即可，时间轴留空自然跳过
"""
        return prompt

    def _merge_batch_scripts(self, batch_scripts: list, video_id: str, video_type: str, total_topics: int) -> dict:
        """将多个批次脚本拼接成完整脚本，自动偏移时间轴"""
        merged_tracks = {
            "voice": [],
            "live2d": [],
            "visual": [],
            "overlay": [],
            "background": [],
        }
        
        time_offset = 0  # 累计时间偏移
        
        for batch_script in batch_scripts:
            tracks = batch_script.get("tracks", {})
            
            # 计算该批次实际结束时间（从所有 track 的 max(start_ms + duration_ms) 得出）
            batch_actual_end = 0
            for track_name in ["voice", "live2d", "visual", "overlay"]:
                for item in tracks.get(track_name, []):
                    item_end = item.get("start_ms", 0) + item.get("duration_ms", 0)
                    if item_end > batch_actual_end:
                        batch_actual_end = item_end
            
            for track_name in merged_tracks:
                if track_name == "background":
                    continue  # background 最后统一生成
                items = tracks.get(track_name, [])
                for item in items:
                    # 过滤空 voice 条目（没有 text 且不对应 play_audio 时段）
                    if track_name == "voice" and not item.get("text", "").strip():
                        continue
                    new_item = dict(item)
                    new_item["start_ms"] = item.get("start_ms", 0) + time_offset
                    merged_tracks[track_name].append(new_item)
            
            # 用实际计算的结束时间做偏移，加 300ms 作为批次间过渡间隔
            time_offset += batch_actual_end + 300
        
        # 修正 time_offset（去掉最后一批的 300ms 间隔）
        time_offset -= 300
        
        # 合并 background（用一个覆盖全程的渐变背景）
        merged_tracks["background"] = [{
            "start_ms": 0,
            "duration_ms": time_offset,
            "type": "gradient",
            "colors": ["#0f0f23", "#1a1a3e"],
        }]
        
        # 生成最终标题
        title = "热搜集锦" if "hot" in video_type.lower() or "热搜" in video_type else "AI 日报"
        
        script = {
            "id": video_id,
            "title": title,
            "total_duration_ms": time_offset,
            "segment_count": total_topics,
            "tracks": merged_tracks,
        }
        
        logger.info(f"[director] 合并完成: {len(batch_scripts)} 批 -> {time_offset/1000:.0f}s")
        return script

    def _resolve_asset_ids(self, script: dict, asset_map: dict):
        """将脚本中的素材编号替换为真实路径"""
        tracks = script.get("tracks", {})
        resolved_count = 0
        unresolved = []
        
        for track_name in ["visual", "overlay"]:
            for item in tracks.get(track_name, []):
                source = item.get("source", "")
                if not source:
                    continue
                # 检查是否是素材编号（V01, IMG01_01 格式）
                source_upper = source.strip().upper()
                if source_upper in asset_map:
                    item["source"] = asset_map[source_upper]
                    resolved_count += 1
                elif source.strip() in asset_map:
                    item["source"] = asset_map[source.strip()]
                    resolved_count += 1
                else:
                    # 可能 LLM 写了 v01 或 V1（没有前导零），做容错
                    for aid, path in asset_map.items():
                        if (source_upper == aid or 
                            source_upper.replace("V", "V0") == aid or
                            source_upper.replace("IMG", "IMG0") == aid):
                            item["source"] = path
                            resolved_count += 1
                            break
                    else:
                        # 没匹配到编号，可能 LLM 还是写了路径，保留原值
                        if not source.startswith(("data/", "./", "http")):
                            unresolved.append(source)
        
        if resolved_count:
            logger.info(f"[director] 素材编号替换: {resolved_count} 个")
        if unresolved:
            logger.warning(f"[director] 未识别的素材引用: {unresolved}")
    
    def _inject_authors(self, script: dict, manifest: dict):
        """
        后处理：从 manifest 强制注入 author 到 video_clip/image 条目。
        
        通过匹配 source 路径中的目录名找到对应 manifest 条目，
        读取其 author 字段并注入为 "@作者昵称"。
        """
        if not manifest:
            return
        
        # 建立 source 路径 → author 的映射
        # manifest key 是类似 "2026-06-29_douyin_topic1_标题" 的目录名
        # source 路径类似 "data/2026-06-29/media/2026-06-29_douyin_topic1_标题/video.mp4"
        path_to_author = {}
        for key, info in manifest.items():
            author = info.get("author", "")
            if author:
                path_to_author[key] = author
                # 也用视频路径和图片路径做映射
                video = info.get("video", {})
                if video and video.get("path"):
                    path_to_author[video["path"]] = author
                for img in info.get("images", []):
                    if img.get("path"):
                        path_to_author[img["path"]] = author
        
        if not path_to_author:
            return
        
        tracks = script.get("tracks", {})
        injected = 0
        
        for item in tracks.get("visual", []):
            item_type = item.get("type", "")
            if item_type not in ("video_clip", "image"):
                continue
            
            source = item.get("source", "")
            if not source:
                continue
            
            # 直接路径匹配
            if source in path_to_author:
                item["author"] = f"@{path_to_author[source]}"
                injected += 1
                continue
            
            # 通过目录名匹配（source 路径包含 manifest key）
            source_normalized = source.replace("\\", "/")
            matched = False
            for key, author in path_to_author.items():
                key_normalized = key.replace("\\", "/")
                if key_normalized in source_normalized:
                    item["author"] = f"@{author}"
                    injected += 1
                    matched = True
                    break
            
            if not matched and item_type == "video_clip":
                # 尝试从 source 的父目录名匹配 manifest key
                from pathlib import PurePosixPath
                source_parent = PurePosixPath(source_normalized).parent.name
                for key in manifest:
                    if key == source_parent or source_parent.endswith(key):
                        author = manifest[key].get("author", "")
                        if author:
                            item["author"] = f"@{author}"
                            injected += 1
                        break
        
        if injected:
            logger.info(f"[director] 作者标注注入: {injected} 个 video_clip/image")

    def _fix_voice_gaps(self, script: dict):
        """
        后处理：压缩 voice 轨中的大间隔。
        
        规则：
        - 如果相邻两条 voice 之间存在 play_audio=true 的 video_clip，允许间隔（原声播放）
        - 否则间隔 > 500ms 的压缩到 300ms
        - 压缩后同步偏移所有轨道的后续条目
        """
        tracks = script.get("tracks", {})
        voices = tracks.get("voice", [])
        if len(voices) < 2:
            return
        
        # 找出所有 play_audio=true 的 visual 时间段
        audio_ranges = []
        for item in tracks.get("visual", []):
            if item.get("type") == "video_clip" and item.get("play_audio"):
                start = item["start_ms"]
                end = start + item.get("duration_ms", 0)
                audio_ranges.append((start, end))
        
        def _in_audio_range(t_start, t_end):
            """检查 [t_start, t_end] 是否与任一 play_audio 区间重叠"""
            for a_start, a_end in audio_ranges:
                if t_start < a_end and t_end > a_start:
                    return True
            return False
        
        # 计算需要压缩的间隔
        MAX_GAP = 500
        TARGET_GAP = 300
        total_compressed = 0
        compressions = []  # [(position_ms, amount_ms)]
        
        for i in range(1, len(voices)):
            prev_end = voices[i-1]["start_ms"] + voices[i-1]["duration_ms"]
            curr_start = voices[i]["start_ms"]
            gap = curr_start - prev_end
            
            if gap > MAX_GAP:
                # 检查是否是 play_audio 段
                if _in_audio_range(prev_end, curr_start):
                    continue
                compress_amount = gap - TARGET_GAP
                compressions.append((curr_start, compress_amount))
                total_compressed += compress_amount
        
        if not compressions:
            return
        
        # 应用压缩：从后往前偏移所有轨道
        for track_name in ["voice", "live2d", "visual", "overlay"]:
            items = tracks.get(track_name, [])
            for item in items:
                item_start = item["start_ms"]
                # 计算该条目前面有多少压缩量需要应用
                shift = sum(amt for pos, amt in compressions if pos <= item_start)
                if shift > 0:
                    item["start_ms"] = max(0, item_start - shift)
        
        # 更新 total_duration_ms
        script["total_duration_ms"] = script.get("total_duration_ms", 0) - total_compressed
        
        # 更新 background 时长
        for bg in tracks.get("background", []):
            bg["duration_ms"] = script["total_duration_ms"]
        
        logger.info(f"[director] voice 间隔压缩: {len(compressions)} 处, 共压缩 {total_compressed/1000:.1f}s")

    def _clean_ending_hints(self, batch_script: dict):
        """
        清洗非最后一批中的结束暗示语。
        
        - 如果 voice text 整条就是"最后一条"类短语，删除该条目
        - 如果 text 中包含"最后一条"，替换为过渡语
        """
        import re
        
        tracks = batch_script.get("tracks", {})
        voices = tracks.get("voice", [])
        
        # 匹配结束暗示的模式
        ending_patterns = [
            r'最后一条[！!。]?',
            r'最后[！!。]?$',
            r'今天就到这里',
            r'今天的.*就到这',
            r'咱们下期[再见]',
            r'关注一下',
            r'别忘了关注',
        ]
        ending_re = re.compile('|'.join(ending_patterns))
        
        cleaned = 0
        to_remove = []
        
        for i, v in enumerate(voices):
            text = v.get("text", "")
            if not text:
                continue
            
            # 整条就是结束暗示短语（<10字）
            if len(text.strip()) <= 10 and ending_re.search(text):
                to_remove.append(i)
                cleaned += 1
                continue
            
            # text 中包含结束暗示，替换掉
            new_text = ending_re.sub("", text).strip()
            if new_text != text.strip():
                if new_text:
                    v["text"] = new_text
                    # 同步清理 subtitle
                    subtitle = v.get("subtitle", "")
                    if subtitle:
                        v["subtitle"] = ending_re.sub("", subtitle).strip()
                else:
                    to_remove.append(i)
                cleaned += 1
        
        # 从后往前删除
        for i in reversed(to_remove):
            voices.pop(i)
        
        if cleaned:
            logger.info(f"[director] 清洗结束暗示: {cleaned} 处")

    def _load_manifest(self, manifest_path: Path) -> dict:
        """加载 manifest.json（下载素材的本地路径 + 识别结果 + 转录）"""
        if not manifest_path.exists():
            logger.warning(f"[director] manifest 不存在: {manifest_path}")
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[director] manifest 加载失败: {e}")
            return {}
    
    def _load_collected(self, collected_dir: Path) -> dict:
        """读取 collected/ 目录，按平台分组"""
        files_by_platform = {}
        
        for filepath in sorted(collected_dir.glob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    raw = f.read()
                    # Handle double-encoded JSON strings
                    if raw.startswith('"'):
                        raw = json.loads(raw)
                    data = json.loads(raw) if isinstance(raw, str) else raw
                
                # 从文件名解析平台: 2026-06-12_{platform}_{slug}.json
                name = filepath.stem  # e.g. 2026-06-12_weibo_xxx
                parts = name.split("_", 2)
                if len(parts) >= 2:
                    platform = parts[1]
                else:
                    platform = data.get("source", "unknown")
                
                # Rankings 单独分组
                if platform == "rankings":
                    files_by_platform.setdefault("rankings", []).append(data)
                else:
                    data["_source_file"] = filepath.name
                    files_by_platform.setdefault(platform, []).append(data)
                    
            except Exception as e:
                logger.warning(f"[director] 读取失败: {filepath.name}: {e}")
        
        for platform, items in files_by_platform.items():
            logger.info(f"[director] loaded {platform}: {len(items)} items")
        
        return files_by_platform
    
    def _build_summary(self, platforms: dict) -> tuple[str, dict]:
        """为选题 LLM 构建素材摘要，用编号代替文件名
        
        Returns:
            (summary_text, file_map): file_map 是 {"F01": "真实文件名.json", ...}
        """
        parts = []
        file_map = {}  # {编号: 真实文件名}
        global_idx = 0
        
        for platform, items in platforms.items():
            parts.append(f"\n### {platform} ({len(items)} 条)")
            for i, item in enumerate(items):
                global_idx += 1
                fid = f"F{global_idx:02d}"
                source_file = item.get("_source_file", "")
                file_map[fid] = source_file
                
                title = item.get("title", "untitled")
                content = (item.get("content") or "")[:150]
                hot = item.get("hot_value", "")
                has_video = bool(item.get("visual_assets", {}).get("video_url"))
                has_images = bool(item.get("visual_assets", {}).get("images"))
                comments_count = len(item.get("top_comments", []))
                
                media_tags = []
                if has_video:
                    media_tags.append("📹视频")
                if has_images:
                    media_tags.append("🖼图片")
                if comments_count > 0:
                    media_tags.append(f"💬{comments_count}条评论")
                media_str = " ".join(media_tags) if media_tags else ""
                
                parts.append(f"  {i+1}. [编号:{fid}] {title} (热度:{hot}) {media_str}")
                if content:
                    parts.append(f"     摘要: {content}")
        
        return "\n".join(parts), file_map
    
    def _load_source_data(self, topic: dict, collected_dir: Path, manifest: dict = None) -> dict | None:
        """
        根据选题信息加载对应的 collected 原始数据，
        并合并 manifest 中的媒体信息（本地路径/图片描述/视频转录）
        """
        source_file = topic.get("source_file", "")
        source_data = None
        
        if source_file:
            # LLM 有时不带 .json 后缀，自动补上
            if not source_file.endswith(".json"):
                source_file = source_file + ".json"
            filepath = collected_dir / source_file
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        raw = f.read()
                        if raw.startswith('"'):
                            raw = json.loads(raw)
                        source_data = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass
            else:
                # Fallback: 模糊匹配 — 用 topic title 关键词在实际文件名中搜索
                title = topic.get("title", "")
                if title:
                    for candidate in collected_dir.glob("*.json"):
                        # 文件名包含 title 中的关键字（至少3个字符的匹配）
                        cname = candidate.stem
                        if any(kw in cname for kw in title if len(kw) >= 3):
                            continue  # 单字符不够
                        # 尝试用 title 的前6个字符匹配
                        if title[:6] in cname or title[-6:] in cname:
                            try:
                                with open(candidate, "r", encoding="utf-8") as f:
                                    raw = f.read()
                                    if raw.startswith('"'):
                                        raw = json.loads(raw)
                                    source_data = json.loads(raw) if isinstance(raw, str) else raw
                                source_file = candidate.name
                                logger.info(f"[director] 模糊匹配: '{title}' -> {candidate.name}")
                                break
                            except Exception:
                                pass
        
        if source_data is None:
            return None
        
        # 合并 manifest 媒体数据
        if manifest and source_file in manifest:
            media_info = manifest[source_file]
            
            # 注入本地图片路径 + 描述
            local_images = media_info.get("images", [])
            if local_images:
                source_data["_local_images"] = [
                    {
                        "path": img.get("path", ""),
                        "description": img.get("description", ""),
                        "width": img.get("width"),
                        "height": img.get("height"),
                    }
                    for img in local_images
                    if isinstance(img, dict) and img.get("description")
                ]
            
            # 注入视频转录
            video_info = media_info.get("video", {})
            if video_info:
                video_duration = video_info.get("duration_s", 0)
                # transcript 是句子级别的分段列表: [{start, end, duration, text}, ...]
                transcript = video_info.get("transcript", "")
                if isinstance(transcript, list) and transcript:
                    source_data["_video_segments"] = transcript
                    source_data["_video_transcript"] = video_info.get("transcript_text", "") or video_info.get("transcript_hint", "")
                else:
                    # 没有结构化 transcript，提供纯文本版本
                    hint = video_info.get("transcript_hint", "") or video_info.get("transcript_text", "")
                    if hint:
                        source_data["_video_transcript"] = hint
                source_data["_video_path"] = video_info.get("path", "")
                source_data["_video_duration_s"] = video_duration
                # 注入视频内容摘要和关键画面（帮助 LLM 理解视频内容、人物、场景）
                if video_info.get("summary"):
                    source_data["_video_summary"] = video_info["summary"]
                if video_info.get("key_moments"):
                    source_data["_video_key_moments"] = video_info["key_moments"]
            
            # 注入作者信息（用于视频播放时显示 @作者 标签）
            if media_info.get("author"):
                source_data["_author"] = media_info["author"]
            
            # 注入 README 信息（GitHub/HuggingFace 项目）
            readme_info = media_info.get("readme")
            if readme_info and isinstance(readme_info, dict):
                # README 摘要（供 LLM 了解项目详情）
                if readme_info.get("summary"):
                    source_data["_readme_summary"] = readme_info["summary"]
                # README 中已识别的图片（供 visual 轨引用）
                _bad_exts = {'.svg', '.gif'}
                recognized_imgs = readme_info.get("recognized_images", [])
                if recognized_imgs:
                    source_data["_readme_images"] = [
                        {
                            "path": img.get("path", ""),
                            "description": img.get("description", ""),
                            "width": img.get("width"),
                            "height": img.get("height"),
                        }
                        for img in recognized_imgs
                        if isinstance(img, dict) and img.get("path")
                        and Path(img["path"]).suffix.lower() not in _bad_exts
                        and Path(img["path"]).exists()
                    ]
                # 即使没有 recognized_images，也提供原始 README 图片路径
                elif readme_info.get("images"):
                    source_data["_readme_images"] = [
                        {"path": p, "description": ""}
                        for p in readme_info["images"]
                        if isinstance(p, str)
                        and Path(p).suffix.lower() not in _bad_exts
                        and Path(p).exists()
                    ]
        
        return source_data
    


    def _parse_json_response(self, text: str) -> dict | list | None:
        """解析 LLM 返回的 JSON"""
        if not text:
            return None
        
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[director] JSON 解析失败: {e}")
            logger.debug(f"[director] 原始内容: {text[:500]}")
            return None
