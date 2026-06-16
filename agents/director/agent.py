"""
Layer 3: Director Agent - 选题 + 脚本生成

两条视频线：
1. 热搜集锦 (weibo + douyin) - 每平台 10 条
2. AI 日报 (huggingface + github + rankings) - 每平台 10 条

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
- 每个平台选 10 条

## 排除标准
- 政治敏感
- 严重负面（灾难/死亡）
- 纯八卦无深度
- 内容重复
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
- `_video_segments[]`: 视频分段 [start_s, end_s, "文字"]
- `_video_duration_s`: 视频总时长（秒）

**visual 轨的 source 必须引用 `_local_images[].path` 或 `_video_path`，不要用原始 URL！**

{source_data}

## ⚠️ 内容真实性规则（严格遵守）
1. 所有数据/数字/引用必须来自上方的原始数据，严禁编造任何事实
2. Mili 的台词是对事实的"吐槽反应"，不是捏造事实
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
        "source": "引用视频路径",
        "time_range": [10.5, 15.2],
        "play_audio": true,
        "caption": "原视频片段"
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
2. 总时长控制在 30-60 秒
3. voice 轨台词要有节奏感，地道四川话，不要平铺直叙
4. **visual 轨必须全程覆盖**（0 到 total_duration_ms 无空白）：
    - 有 _local_images 时用 `type: "image"` 引用真实路径
    - 有 _video_path 时用 `type: "video_clip"` 截取片段
    - 没有图片/视频的时段，用 `type: "remotion"` 填充动态效果
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
9. **视频原声规则**：
    - video_clip 需要指定 time_range（秒）和 play_audio（是否播放原声）
    - 当 `play_audio: true` 时，voice 轨在该 video_clip 的时间段内必须留空（角色不说话）
    - 角色可以在视频片段前说引导语（如 "来看看这段视频"），然后闭嘴让视频自己播放
    - 播放原声时 live2d 轨用 `exp_curious` 或 `exp_pleasant`（看视频的表情）
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
12. **时间轴规则（严格遵守）**：
    - total_duration_ms = voice 轨最后一条的 start_ms + duration_ms（视频结束 = voice 结束）
    - voice 轨各条目之间间隔不超过 500ms（紧凑排列）
    - **例外**：当 video_clip 设置了 play_audio: true 时，voice 轨在该时间段可以留空
    - voice[n].start_ms = voice[n-1].start_ms + voice[n-1].duration_ms + 间隔(0~500ms)
    - visual 轨必须覆盖 0 到 total_duration_ms 全程（用 image/video_clip/remotion 组合填满）
    - overlay、live2d 不得超出 total_duration_ms
    - background 覆盖 0 到 total_duration_ms 全程
"""


AGGREGATED_SCRIPT_PROMPT = """为 "{video_type}" 生成一个聚合视频脚本。将以下 {topic_count} 条新闻聚合成一条完整视频。

## 视频 ID: {video_id}

## 结构要求
1. **开场**（5-8秒）：点赞引导 + 总述今天看点。live2d 必须用 `sp_thumbs_up` 动作（9.2秒），配合"家人们先点个赞"等话术
2. **正文段落**：每条新闻一个段落（每段最长 30 秒），段落之间有过渡转场
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
                type_instructions="微博热搜 + 抖音热点的合集视频。每个平台选 10 条最有看点的话题。",
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
                before_count = len(hot_topics)
                hot_topics = [t for t in hot_topics if self._has_media(t, manifest)]
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
                    content = r.get("content", "")
                    if content:
                        ai_summary += content[:2000] + "\n"
                    rank_list = r.get("rankings", [])
                    for item in rank_list[:10]:
                        ai_summary += f"  - {item}\n"
            
            ai_topics = self._call_selection(
                video_type="AI 日报",
                type_instructions="HuggingFace 论文/模型 + GitHub Trending 的 AI 资讯合集。每个平台选 10 条。Rankings 数据可作为单独段落引用。",
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
- 说话风格：毒舌、刻薄但不恶毒，像你那个嘴巴厉害但心肠好的四川朋友
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
    ) -> dict | None:
        """
        将多条新闻聚合成一个长脚本。
        
        Args:
            topics: 选题列表（10-20条）
            video_type: "AI 日报" 或 "热搜集锦"
            video_id: 输出脚本 ID，如 "ai_daily" 或 "hot_daily"
            collected_dir: collected 数据目录
            output_dir: 脚本输出目录
        
        Returns:
            聚合后的单个脚本 dict
        """
        manifest = self._load_manifest(collected_dir.parent / "media" / "manifest.json")
        
        # 为每条 topic 加载 source_data
        topics_with_data = []
        for topic in topics:
            source_data = self._load_source_data(topic, collected_dir, manifest)
            topics_with_data.append({
                "topic": topic,
                "source_data": source_data,
            })
        
        # 构建聚合 prompt
        # 构建聚合 prompt + 素材编号表
        segments_text = ""
        asset_map = {}  # {编号: 真实路径} 用于后处理替换
        
        for i, item in enumerate(topics_with_data):
            t = item["topic"]
            sd = item["source_data"]
            idx = i + 1
            segments_text += f"\n### 第 {idx} 条: {t.get('title', '未知')}\n"
            segments_text += f"- 平台: {t.get('platform', '未知')}\n"
            segments_text += f"- 角度: {t.get('angle', '')}\n"
            
            if sd:
                # 视频素材 → 分配编号 V01, V02...
                video_path = sd.get("_video_path", "")
                if video_path:
                    vid_id = f"V{idx:02d}"
                    asset_map[vid_id] = video_path
                    video_dur = sd.get("_video_duration_s", 0)
                    segments_text += f"- 视频素材: `{vid_id}` (时长: {video_dur}s)\n"
                    transcript = sd.get("_video_transcript", "")
                    if transcript:
                        segments_text += f"- 视频转录: {transcript[:300]}\n"
                
                # 图片素材 → 分配编号 IMG01_01, IMG01_02...
                local_images = sd.get("_local_images", [])
                if local_images:
                    segments_text += f"- 图片素材({len(local_images)}张):\n"
                    for j, img in enumerate(local_images[:5]):
                        img_id = f"IMG{idx:02d}_{j+1:02d}"
                        asset_map[img_id] = img["path"]
                        desc = img.get("description", "")[:60]
                        segments_text += f"  - `{img_id}`: {desc}\n"
                
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
                
                # 额外数据
                stars = sd.get("stars", sd.get("star_count", 0))
                if stars:
                    segments_text += f"- Stars: {stars}\n"
                lang = sd.get("language", sd.get("lang", ""))
                if lang:
                    segments_text += f"- 语言: {lang}\n"
            else:
                segments_text += f"- source_data: 无\n"
        
        # 附加素材编号对照表
        if asset_map:
            segments_text += "\n\n## 素材编号对照表（source 字段只能使用以下编号！）\n"
            for aid, path in asset_map.items():
                segments_text += f"- `{aid}` → {Path(path).name}\n"
        
        prompt = AGGREGATED_SCRIPT_PROMPT.format(
            video_type=video_type,
            video_id=video_id,
            topic_count=len(topics),
            segments=segments_text,
        )
        
        logger.info(f"[director] 生成聚合脚本: {video_type} ({len(topics)} 条)")
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._aggregated_system_prompt(video_type)},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=65536,  # DeepSeek 支持 384K，聚合脚本较长
            response_format={"type": "json_object"},
        )
        
        script = self._parse_json_response(response.choices[0].message.content)
        if script:
            script["id"] = video_id
            
            # 后处理：将素材编号替换为真实路径
            if asset_map:
                self._resolve_asset_ids(script, asset_map)
            
            output_dir.mkdir(parents=True, exist_ok=True)
            filepath = output_dir / f"{video_id}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            
            tracks = script.get("tracks", {})
            voice_count = len(tracks.get("voice", []))
            duration_s = script.get("total_duration_ms", 0) / 1000
            logger.info(f"[director] ✅ 聚合脚本完成: {video_type} ({duration_s:.0f}s, voice:{voice_count})")
            return script
        else:
            logger.error(f"[director] ❌ 聚合脚本生成失败: {video_type}")
            return None
    
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
- 内容要求（每个项目必须覆盖）：
  - **是什么**：一句话概括项目定位和核心功能
  - **技术细节**：模型参数量、架构、训练数据、推理速度、支持语言等
  - **怎么用**：部署方式、API 接口、依赖环境、上手难度
  - **适合谁**：目标用户画像和使用场景举例（"比如你要做XXX，直接用这个"）
  - **开源协议**：MIT/Apache/GPL 等，商用是否可以
  - **数据**：star 数、下载量、更新频率等客观数据
  - 可以用类比帮助理解（"简单说就是 XXX 的开源版"）
  - 如果知道同类工具，简短对比差异
- 禁止事项：
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

## 聚合视频结构
这是一个**多段新闻聚合**视频，每条新闻是一个段落（最长 30 秒），段落之间有过渡转场。

### 段落结构模板：
1. 过渡转场（2-3秒）：overlay 显示 highlight_text + 角色说过渡语
2. 正文（15-25秒）：角色吐槽 + 素材展示
3. （如有视频）视频原声片段（5-10秒）：角色闭嘴

### 关键规则：
- 每条新闻段落控制在 30 秒内
- 段落间用 overlay 的 `highlight_text` 做转场卡片（如"第3条"、"接下来"）
- voice 轨的过渡语要自然（"下一个更离谱..."、"接着看这个..."）
- **开场必须用 `sp_thumbs_up` 动作**（9.2秒），配合"家人们先点个赞/关注一下"等点赞引导话术
- 开场结束后进入正文，结尾有总结+互动引导（5-8秒）
- 视频原声和角色声不混合

### ⚠️ 视频原声段时序约束（严格遵守）：
- 当 visual 轨有 `play_audio: true` 的 video_clip 时，其 `start_ms` 必须**紧接**前一条 voice 的结束时间（间隔 ≤ 500ms），**不允许出现空白等待**
- voice 轨在 video_clip(play_audio=true) 期间必须留空（不安排台词），留空段的 start_ms 必须和 video_clip 的 start_ms 一致
- 引导播放视频的 voice 台词（如"来看原视频"）结束后，video_clip 必须立刻跟上，时间线示例：
  ```
  voice: start_ms=8000, duration_ms=3000, text="来看看原视频"  → 结束于 11000ms
  visual: start_ms=11000, type="video_clip", play_audio=true   → 紧接开始
  voice: start_ms=11000, duration_ms=10000, text=""             → 留空让原声播放
  ```
- video_clip(play_audio=false) 的预览片段可以和 voice 并行，无此限制


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
1. 图片：`{"start_ms": 0, "duration_ms": 5000, "type": "image", "source": "真实文件路径"}`
2. 视频片段：`{"start_ms": 0, "duration_ms": 8000, "type": "video_clip", "source": "真实文件路径", "time_range": [0, 8], "play_audio": true}`
3. Remotion 组件：`{"start_ms": 0, "duration_ms": 12000, "type": "remotion", "component": "组件名", "props": {"position": "top", ...}}`
   - **position 字段必须**：`"top"`（默认，组件在上半区）、`"center"`（居中）、`"bottom"`（下半区）
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
- voice[n].start_ms = voice[n-1].start_ms + voice[n-1].duration_ms + 间隔(0~500ms)
- visual 轨必须覆盖 0 到 total_duration_ms 全程（无空白）
- live2d 轨必须覆盖 0 到 total_duration_ms 全程
- overlay、background 不得超出 total_duration_ms
- 当 video_clip 设置 play_audio: true 时，voice 轨在该时间段留空

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
    
    def _has_media(self, topic: dict, manifest: dict) -> bool:
        """检查选题是否有对应的图片或视频素材"""
        source_file = topic.get("source_file", "")
        if not source_file:
            return True  # 无法判断，保留
        entry = manifest.get(source_file, {})
        has_images = bool(entry.get("images"))
        has_video = bool(entry.get("video"))
        return has_images or has_video
    
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
                    if img.get("description")  # 只包含有描述的图片
                ]
            
            # 注入视频转录
            video_info = media_info.get("video", {})
            if video_info:
                source_data["_video_transcript"] = video_info.get("transcript", "")
                source_data["_video_path"] = video_info.get("path", "")
                source_data["_video_duration_s"] = video_info.get("duration_s", 0)
                # 精简版 segments（前 20 条）
                segments = video_info.get("segments", [])
                if segments:
                    source_data["_video_segments"] = segments[:20]
        
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
