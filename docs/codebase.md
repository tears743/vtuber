# VideoFactory Codebase 技术文档

## 项目概述

VideoFactory 是一个全自动 AI 短视频生产管线，每天从多个平台采集热点新闻，通过 LLM 编排脚本，最终合成带 Live2D 虚拟角色口播的竖屏短视频。

**输出产物：**
- `hot_daily.mp4` — 热搜集锦（微博 + 抖音），7-8 分钟
- `ai_daily.mp4` — AI 日报（HuggingFace + GitHub），4-5 分钟

**技术栈：**
- Python 3.11 + PowerShell 编排
- DeepSeek V4-flash (LLM)、Gemma-4 (Vision)、VoxCPM2 (TTS)
- Remotion (TypeScript 动效渲染)
- FFmpeg (视频合成)
- OpenCLI (浏览器自动化)

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    run_pipeline.ps1                          │
│              (编排层 - 串联 10 个步骤)                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐  │
│  │Collector│──▶│ Director │──▶│Renderer │──▶│ Compose  │  │
│  │ (采集)  │   │ (编排)    │   │ (渲染)  │   │ (合成)   │  │
│  └─────────┘   └──────────┘   └─────────┘   └──────────┘  │
│       │              │              │              │         │
│  collected/     scripts/      overlay/       final/         │
│  media/         scripts_aligned/ visual/                    │
│                                 live2d/                     │
│                                 audio/                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
videoFactory/
├── config.yaml              # 全局配置（模型、路径、参数）
├── config_loader.py         # 配置加载工具
├── requirements.txt         # Python 依赖
│
├── agents/                  # 核心 Agent 模块
│   ├── collector/           # Layer 1: 数据采集
│   │   ├── orchestrator.py  # 采集编排器（选题+调度）
│   │   ├── worker.py        # 平台 Worker（浏览器自动化采集）
│   │   ├── sources.py       # 数据源定义
│   │   ├── agent.py         # 旧版单体 Agent（已弃用）
│   │   ├── run.py           # 单体入口（已弃用）
│   │   └── run_teams.py     # Agent Teams 入口
│   │
│   ├── director/            # Layer 2: 内容编排
│   │   ├── agent.py         # Director Agent（选题+脚本生成）
│   │   └── run_director.py  # Director 入口
│   │
│   └── renderer/            # Layer 3: 视频渲染
│       ├── run_render.py    # 渲染入口 + 步骤调度
│       ├── media_downloader.py   # 素材下载（kukutool + yt-dlp）
│       ├── media_recognizer.py   # 图片/视频识别（MiMo Vision）
│       ├── audio_transcriber.py  # 音频转文字（faster-whisper）
│       ├── tts.py                # TTS 语音合成（VoxCPM2）
│       ├── realigner.py          # 时间轴对齐
│       ├── remotion_renderer.py  # Overlay 卡片渲染（调 Remotion）
│       ├── visual_renderer.py    # 背景视觉层合成
│       ├── live2d_renderer.py    # Live2D 角色渲染
│       ├── live2d_mapping.py     # 表情映射表
│       ├── layout_validator.py   # 布局校验
│       └── visual_qa.py          # 视觉质量检查
│
├── remotion/                # Remotion 项目（TypeScript）
│   ├── src/
│   │   ├── Root.tsx              # Remotion 入口
│   │   ├── Composition.tsx       # Overlay 卡片合成
│   │   ├── Live2DComposition.tsx # Live2D 渲染合成
│   │   ├── VisualComposition.tsx # 视觉层合成
│   │   ├── MeteorOverlay.tsx     # 流星特效
│   │   ├── StudioBackground.tsx  # 演播室背景
│   │   ├── styles.ts             # 全局样式
│   │   └── components/           # 动效组件
│   │       ├── CommentScroll.tsx  # 弹幕评论滚动
│   │       ├── DataReveal.tsx     # 数据揭示动画
│   │       ├── ModelCard.tsx      # AI 模型卡片
│   │       ├── RankingTable.tsx   # 排行榜表格
│   │       ├── StatsCard.tsx      # 统计卡片
│   │       ├── InfoPanel.tsx      # 信息面板
│   │       ├── HighlightText.tsx  # 高亮文字动画
│   │       ├── QuoteBox.tsx       # 引用框
│   │       ├── CodeScroll.tsx     # 代码滚动展示
│   │       └── AuthorTag.tsx      # 作者标签
│   └── package.json
│
├── scripts/                 # 运维脚本
│   ├── run_pipeline.ps1     # 主管线编排
│   ├── scheduler.ps1        # 定时任务
│   ├── activate_chrome.ps1  # Chrome 前台激活
│   ├── start_tts.bat        # TTS 服务启动
│   └── step_*.bat           # 单步执行快捷方式
│
├── assets/                  # 静态资产
│   └── studio/              # 演播室素材
│       ├── bg_starry.png    # 星空背景
│       ├── desk_foreground.png  # 演播台前景
│       └── meteor_fx.webm   # 流星特效（VP9 alpha）
│
├── data/                    # 运行时数据（按日期）
│   └── {yyyy-MM-dd}/
│       ├── collected/       # 采集的原始数据 (JSON)
│       ├── media/           # 下载的素材（视频/图片）
│       ├── scripts/         # Director 生成的脚本
│       ├── scripts_aligned/ # 时间轴对齐后的脚本
│       ├── audio/           # TTS 语音 (WAV)
│       ├── overlay/         # Remotion 渲染的卡片 (WebM)
│       ├── visual/          # 背景视觉层 (MP4)
│       ├── live2d/          # Live2D 动画 (WebM)
│       └── final/           # 最终成片 (MP4)
│
└── docs/
    └── pipeline.md          # 管线使用文档
```

---

## 管线流程详解

### Step 1: Collect（数据采集）

**入口**: `agents/collector/run_teams.py`
**架构**: Orchestrator + Workers (Agent Teams)

```
Orchestrator (DeepSeek V4-flash)
    │
    ├── 获取各平台热榜 (opencli weibo/douyin/hf/github)
    ├── LLM 选题 (40-60 条)
    ├── 去重 (跨日期)
    │
    ├── Worker-weibo  ──── 并发采集微博帖子/评论/图片
    ├── Worker-douyin ──── 并发采集抖音视频页面信息
    ├── Worker-hf     ──── 并发采集 HuggingFace 论文/模型
    └── Worker-github ──── 并发采集 GitHub 仓库信息
```

**关键文件：**
| 文件 | 职责 |
|------|------|
| `orchestrator.py` | 编排采集流程：获取热榜 → LLM选题 → 去重 → 分发Worker |
| `worker.py` | 平台 Worker：接收话题列表，用浏览器自动化逐条深度采集 |
| `sources.py` | 定义各平台数据源和 CLI 命令 |

**输出**: `data/{date}/collected/*.json`（每条新闻一个 JSON）

---

### Step 2: Download（素材下载）

**入口**: `agents/renderer/run_render.py` → `step_download()`
**核心**: `agents/renderer/media_downloader.py`

```
MediaDownloader
    │
    ├── download_all(collected_dir, media_dir)
    │   ├── 遍历 collected JSON
    │   ├── 按来源分发:
    │   │   ├── douyin → _download_douyin_video()
    │   │   │   ├── kukutool.com 浏览器自动化 (主方案, 10次重试)
    │   │   │   └── yt-dlp fallback
    │   │   └── 其他 → _download_video() / _download_images()
    │   └── 生成 manifest.json
```

**清晰度优先级**: 1080p > 720p > 540p > 超高清

**输出**: `data/{date}/media/{item_slug}/video.mp4` + `manifest.json`

---

### Step 3: Recognize（素材识别）

**入口**: `step_recognize()` → `MediaRecognizer`
**模型**: MiMo-v2.5 (Vision, 本地)

对每个下载的图片/视频进行内容理解，写入 JSON 描述：
- 图片：场景描述、文字 OCR
- 视频：关键帧抽取 → 多帧理解

**输出**: 更新 `manifest.json` 中的 `description` 字段

---

### Step 4: Director（脚本生成）

**入口**: `agents/director/run_director.py` → `DirectorAgent`
**模型**: DeepSeek V4-flash

```
DirectorAgent
    │
    ├── 选题 (TOPIC_SELECTION_PROMPT)
    │   ├── 热搜集锦: 微博 + 抖音素材
    │   └── AI日报: HuggingFace + GitHub 素材
    │
    ├── 脚本生成 (SCRIPT_GENERATION_PROMPT)
    │   ├── voice 轨: 四川话口播文案
    │   ├── live2d 轨: 表情/动作标记
    │   ├── overlay 轨: 数据卡片/弹幕定义
    │   ├── visual 轨: 背景素材引用
    │   └── background 轨: 音乐/音效
    │
    └── 输出多轨 JSON 脚本
```

**核心约束**:
- Visual 轨只能引用当前新闻自身素材，禁止跨新闻
- Mili 动作与语音严格并行
- 脚本总时长由各段语音时长决定

**输出**: `data/{date}/scripts/hot_daily.json` + `ai_daily.json`

---

### Step 5: TTS（语音合成）

**入口**: `step_tts()` → `VoxCPMTTS`
**服务**: VoxCPM2 (WSL CUDA, port 8808)

```
VoxCPMTTS
    │
    ├── check_health()          # 检查服务状态
    ├── synthesize_script()     # 遍历脚本 voice 轨
    │   └── _synthesize_one()   # 单句合成
    │       ├── clean_tts_text() # 文本清洗
    │       ├── POST /generate  # 调用 TTS 服务
    │       └── 保存 WAV + 记录时长
    └── 输出 durations.json
```

**参数**: `cfg_value=2.0`, `dialect=四川话`, `speed=快`

**输出**: `data/{date}/audio/{script_id}/voice_00.wav ~ voice_XX.wav` + `durations.json`

---

### Step 6: Align（时间轴对齐）

**入口**: `step_align()` → `realigner.py`
**核心函数**: `realign_timeline(script, audio_durations)`

```
realigner
    │
    ├── _realign_tracks()       # 多轨模式
    │   ├── voice 轨: 用实际音频时长替换预设时长
    │   ├── live2d 轨: 跟随 voice 轨时间
    │   ├── visual 轨: 保持设计时间 + preserved_gap 修正
    │   └── 更新 total_duration_ms
    │
    └── _realign_segments()     # 旧格式兼容
```

**关键机制**: `preserved_gap` 防止线性映射导致时间轴漂移

**输出**: `data/{date}/scripts_aligned/*.json`

---

### Step 7: Overlay（卡片渲染）

**入口**: `step_render()` → `remotion_renderer.py`
**引擎**: Remotion (Node.js + TypeScript)

```
remotion_renderer.render_overlay()
    │
    ├── 解析脚本 overlay 轨
    ├── 生成 Remotion inputProps JSON
    ├── 调用 npx remotion render
    └── 输出透明 WebM (VP9 alpha)
```

**Remotion 组件**:
| 组件 | 用途 |
|------|------|
| `CommentScroll` | 弹幕评论滚动 |
| `DataReveal` | 数据数字揭示动画 |
| `ModelCard` | AI 模型信息卡片 |
| `RankingTable` | 排行榜 |
| `StatsCard` | 统计数据展示 |
| `InfoPanel` | 信息面板 |
| `HighlightText` | 高亮文字动画 |
| `QuoteBox` | 引用框 |
| `CodeScroll` | 代码滚动 |
| `AuthorTag` | 作者/来源标签 |

**输出**: `data/{date}/overlay/{script_id}_overlay.webm`

---

### Step 8: Visual（背景层渲染）

**入口**: `step_visual()` → `visual_renderer.py`

```
render_script_visual()
    │
    ├── 解析 visual 轨段落
    ├── 按时间片合成背景:
    │   ├── image 段: 静态图 + 缓动动画
    │   └── video_clip 段: 视频裁剪 + 缩放
    └── FFmpeg 拼接为连续背景 MP4
```

**约束**: 只使用当前新闻自身素材

**输出**: `data/{date}/visual/{script_id}_visual.mp4`

---

### Step 9: Live2D（角色渲染）

**入口**: `step_live2d()` → `live2d_renderer.py`
**模型**: mao_pro (Live2D Cubism)
**引擎**: Remotion `Live2DComposition`

```
live2d_renderer
    │
    ├── 解析 live2d 轨 (表情/动作)
    ├── 口型同步 (音频 → phoneme → 嘴型参数)
    ├── 表情映射 (emotion_map in config.yaml)
    └── Remotion 渲染透明 WebM
```

**表情映射**: neutral=0, sarcastic=2, amused=3, shocked=3, excited=3...

**输出**: `data/{date}/live2d/{script_id}_live2d.webm`（VP9 alpha 透明通道）

---

### Step 10: Compose（最终合成）

**入口**: `step_compose()` → `_compose_studio()`
**引擎**: FFmpeg

```
_compose_studio()
    │
    ├── 输入层:
    │   ├── [0] 演播室背景 (bg_starry.png, loop)
    │   ├── [1] 流星特效 (meteor_fx.webm, loop, alpha)
    │   ├── [2] Live2D 角色 (alpha)
    │   ├── [3] 演播台前景 (desk_foreground.png, loop)
    │   ├── [4] Overlay 卡片 (alpha)
    │   └── [5+] 素材文件 (image/video_clip)
    │
    ├── 合成模式:
    │   ├── 演播室模式: 背景 + Live2D居中 + 前景 + overlay
    │   └── 素材模式: 全屏素材 + Live2D缩小右下角
    │   └── 两模式间 0.5s fade 转场
    │
    ├── 音频: 合并 TTS WAV + 素材原声(可选)
    └── 输出 H.264 MP4
```

**输出**: `data/{date}/final/hot_daily.mp4` + `ai_daily.mp4`

---

## 配置系统

### config.yaml 结构

```yaml
models:          # 模型池（base_url, api_key, model, context_length）
roles:           # 角色分配（指向模型池中的模型名）
agents:          # 运行参数（并发数、temperature、max_tokens）
opencli:         # OpenCLI 路径
collector:       # 采集配置
understanding:   # 内容理解（Vision + ASR）
tts:             # TTS 参数
composition:     # 视频分辨率、FPS、角色位置
live2d:          # Live2D 模型路径和表情映射
remotion:        # Remotion 项目配置
paths:           # 数据/资源路径
```

### config_loader.py API

| 函数 | 用途 |
|------|------|
| `load_config()` | 加载 config.yaml，支持环境变量覆盖 |
| `get_model_config(cfg, role)` | 按角色获取模型配置 |
| `get_worker_model_config(cfg, platform)` | 按平台获取 Worker 模型（支持覆盖） |
| `ensure_dirs(cfg)` | 创建当日数据目录 |
| `get_today_dir(cfg)` | 获取当日数据根路径 |

---

## 函数调用关系图

```
run_pipeline.ps1
    │
    ├── python -m agents.collector.run_teams
    │   └── CollectorOrchestrator.run()
    │       ├── _fetch_hot_lists()      → opencli CLI 命令
    │       ├── _plan_tasks()           → DeepSeek LLM
    │       ├── _dedup_tasks()          → 本地文件扫描
    │       └── _dispatch_workers()     → ThreadPoolExecutor
    │           └── PlatformWorker.run() → opencli browser 自动化
    │
    ├── python -m agents.renderer.run_render --step download
    │   └── step_download()
    │       └── MediaDownloader.download_all()
    │           ├── _download_douyin_video()
    │           │   ├── _download_via_kukutool()  → opencli browser
    │           │   └── yt-dlp fallback
    │           └── _download_video() / _download_images()
    │
    ├── python -m agents.renderer.run_render --step recognize
    │   └── step_recognize()
    │       └── MediaRecognizer.recognize_all()   → MiMo Vision API
    │
    ├── python -m agents.director.run_director
    │   └── DirectorAgent.run()
    │       ├── _select_topics()                  → DeepSeek LLM
    │       └── _generate_script()                → DeepSeek LLM
    │
    ├── python -m agents.renderer.run_render --step tts
    │   └── step_tts()
    │       └── VoxCPMTTS.synthesize_script()     → HTTP POST :8808
    │
    ├── python -m agents.renderer.run_render --step align
    │   └── step_align()
    │       └── realign_script_file()
    │           └── realign_timeline()
    │               └── _realign_tracks()
    │
    ├── python -m agents.renderer.run_render --step render (overlay)
    │   └── step_render()
    │       └── render_overlay()                  → npx remotion render
    │
    ├── python -m agents.renderer.run_render --step visual
    │   └── step_visual()
    │       └── render_script_visual()            → FFmpeg
    │
    ├── python -m agents.renderer.run_render --step live2d
    │   └── step_live2d()
    │       └── live2d_renderer.step_live2d()     → npx remotion render
    │
    └── python -m agents.renderer.run_render --step compose
        └── step_compose()
            ├── _merge_audio_segments()           → FFmpeg
            └── _compose_studio()                 → FFmpeg
```

---

## 外部依赖

| 服务 | 地址 | 用途 |
|------|------|------|
| VoxCPM2 TTS | `http://127.0.0.1:8808` | 四川话语音合成 (WSL CUDA) |
| LM Studio | `http://127.0.0.1:1234` | Gemma-4 视觉理解 (本地) |
| DeepSeek V4 | `https://api.deepseek.com/v1` | LLM 编排/脚本生成 |
| MiMo V2.5 | `https://token-plan-cn.xiaomimimo.com/v1` | 图片识别 (Vision) |
| OpenCLI | 本地 Node.js 工具 | 浏览器自动化 |
| Remotion | 本地 Node.js | 动效/Live2D 渲染 |
| FFmpeg | 系统 PATH | 视频合成 |
| faster-whisper | Python 库 | 音频转文字 |

---

## 数据格式

### 脚本 JSON 结构 (scripts/*.json)

```json
{
  "id": "hot_daily",
  "type": "hot_compilation",
  "total_duration_ms": 480000,
  "tracks": {
    "voice": [
      {
        "start_ms": 0,
        "duration_ms": 5000,
        "text": "各位老铁大家好...",
        "subtitle": "各位老铁大家好...",
        "audio_file": "audio/hot_daily/voice_00.wav"
      }
    ],
    "live2d": [
      {
        "start_ms": 0,
        "duration_ms": 5000,
        "emotion": "excited",
        "action": "wave"
      }
    ],
    "overlay": [
      {
        "start_ms": 5000,
        "duration_ms": 8000,
        "type": "comment_scroll",
        "data": { "comments": [...] }
      }
    ],
    "visual": [
      {
        "start_ms": 5000,
        "duration_ms": 10000,
        "type": "video_clip",
        "source": "data/2026-06-25/media/xxx/video.mp4",
        "time_range": [2.0, 12.0]
      }
    ]
  }
}
```

### Manifest JSON (media/manifest.json)

```json
{
  "2026-06-25_douyin_topic_name.json": {
    "images": ["path/to/img1.jpg"],
    "video": "path/to/video.mp4",
    "author": "@username",
    "description": "AI 识别的内容描述"
  }
}
```

---

## 已知问题与设计决策

| 决策 | 原因 |
|------|------|
| kukutool 而非直接抖音 API | 抖音无公开 API，kukutool 免登录解析 |
| TTS cfg_value=2.0 | 3.0 时四川话风格跳变严重 |
| 下载清晰度不选超高清 | 文件过大(100MB+)导致超时 |
| preserved_gap 机制 | 防止 realign 时时间轴线性漂移 |
| audio_file 字段定位 WAV | 空段索引偏移问题的修复 |
| Visual 轨素材归属约束 | 禁止跨新闻借用导致画面与口播不匹配 |

---

## 版本历史

| Tag | 内容 |
|-----|------|
| v0.0.1 | 初始 release - 基本管线 |
| v0.0.2 | Director 句子级时间戳 |
| v0.0.3 | 修复轨道错乱、语音重叠、配图跨新闻 |
| v0.0.5 | kukutool 下载优化 + TTS 稳定性 + 管线文档 |
| v0.0.6 | 定时器脚本 + 文档更新 |
