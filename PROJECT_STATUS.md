# VideoFactory — 项目状态

> 最后更新: 2026-06-14 17:53

## 一、项目概述

AI 驱动的短视频自动化生产管线。从热点采集到成品视频，全流程自动化。
目标平台：抖音（竖屏 9:16，1080x1920）。
角色人设：**Mili** — 二次元 Live2D 四川妹子，毒舌口播。

---

## 二、技术架构

```
═══════════════════════════════════════════════════════════════════════════════════
                         VideoFactory 完整数据流架构
═══════════════════════════════════════════════════════════════════════════════════

┌─────────────────────────── Phase 1: COLLECT ───────────────────────────────────┐
│                                                                                │
│  ┌─────────┐   OpenCLI    ┌──────────────────────────────────────────────┐    │
│  │  微博   │──(浏览器)──▶│                                              │    │
│  │  热搜   │              │     CollectorAgent (DeepSeek-V4-Flash)       │    │
│  ├─────────┤              │                                              │    │
│  │  抖音   │──(浏览器)──▶│     输入: 平台页面 HTML/JSON                 │    │
│  │  话题   │              │     处理: LLM 结构化提取                     │    │
│  ├─────────┤              │     输出: title/content/hot_value/url/       │    │
│  │HuggingFace│─(HTTP)───▶│           visual_assets/top_comments/        │    │
│  │ Trending │             │           key_points/media_type              │    │
│  ├─────────┤              │                                              │    │
│  │ GitHub  │──(HTTP)────▶│                                              │    │
│  │Trending │              └──────────────────┬───────────────────────────┘    │
│  └─────────┘                                 │                                │
│                                              ▼                                │
│                              data/{date}/collected/*.json                      │
│                              (每个话题一个 JSON 文件)                          │
└───────────────────────────────────────────────────────────────────────────────┘
                                               │
                                               ▼
┌─────────────────────────── Phase 2: DIRECT ───────────────────────────────────┐
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │              DirectorAgent (DeepSeek-V4-Flash, 384K output)        │       │
│  ├────────────────────────────────────────────────────────────────────┤       │
│  │                                                                    │       │
│  │  Step A: 选题 (Selection)                                          │       │
│  │  ┌──────────────────────────────────────────────────────────┐     │       │
│  │  │ • 读取 collected/ 全部 JSON                              │     │       │
│  │  │ • 评分: 传播力 × 争议性 × 视觉潜力 × 时效性             │     │       │
│  │  │ • 排除: 政治/负面/重复/违禁品/迷信/导流                  │     │       │
│  │  │ • 输出: selected/selection.json (排序后 top N)            │     │       │
│  │  └──────────────────────────────────────────────────────────┘     │       │
│  │                              │                                     │       │
│  │                              ▼                                     │       │
│  │  Step B: 脚本生成 (Script Generation)                              │       │
│  │  ┌──────────────────────────────────────────────────────────┐     │       │
│  │  │ • 每个选中话题 → 生成完整视频脚本                        │     │       │
│  │  │ • Mili 人设: 四川话毒舌 + 表情/动作标注                  │     │       │
│  │  │ • 引用 manifest.json 中的素材识别结果                    │     │       │
│  │  │ • 引用视频转录文本作为口播参考                            │     │       │
│  │  │ • 输出 segments[]:                                       │     │       │
│  │  │   - type: live2d_talk | media_show | data_card |          │     │       │
│  │  │          comment_scroll | transition                      │     │       │
│  │  │   - card_type: ranking | stat | quote | versus | timeline │     │       │
│  │  │   - expression/motion (Live2D 控制)                       │     │       │
│  │  │   - media_url / requires_browser                          │     │       │
│  │  │ • 违禁词检查 (10类) + 四川话替换策略                     │     │       │
│  │  │ • 输出: scripts/{topic_id}.json                          │     │       │
│  │  └──────────────────────────────────────────────────────────┘     │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                                                                                │
│  输出文件:                                                                     │
│    data/{date}/selected/selection.json                                         │
│    data/{date}/scripts/*.json                                                  │
└───────────────────────────────────────────────────────────────────────────────┘
                                               │
                                               ▼
┌─────────────────────────── Phase 3: RENDER ───────────────────────────────────┐
│                                                                                │
│  Step 0: 素材下载 (MediaDownloader)                                           │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • 增量下载: 先加载已有 manifest，只补充缺失素材                   │       │
│  │ • 普通图片: requests 直接下载                                      │       │
│  │ • 抖音视频: yt-dlp 直接下载 (无需 cookie/浏览器)                  │       │
│  │ • 输出: media/{slug}/img_00.jpg, video.mp4                        │       │
│  │ • 输出: media/manifest.json (路径索引，增量更新)                   │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 0.5: 图片识别 (MediaRecognizer → mimo-v2.5 Vision)                     │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • 质量过滤: <200px 或 <10KB → 跳过                                │       │
│  │ • 10 并发识别 + 空结果重试 (max 2次)                               │       │
│  │ • 输出维度: 主体/文字OCR/构图/色调/情绪/来源                       │       │
│  │ • 更新: manifest.json (加入 description/width/height)              │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 0.6: 音频转录 (AudioTranscriber → WSL + faster-whisper CUDA)            │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • 通过 WSL subprocess 调用 faster-whisper large-v3                 │       │
│  │ • RTX 4090 CUDA float16 加速 (~3GB VRAM)                          │       │
│  │ • 9 分钟视频 ≈ 47 秒完成                                          │       │
│  │ • VAD 过滤静音段 + 短句合并 (间隔>1.5s 或 >50字断句)              │       │
│  │ • 输出: manifest.json video.transcript + video.segments            │       │
│  │ • segments 紧凑格式: [start, end, "text"] (531段→50段)            │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 1: TTS 语音合成 (VoxCPM2 → WSL CUDA, port 8808)                        │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • 遍历 scripts/ 中 live2d_talk 段的 text 字段                     │       │
│  │ • 文本清洗 (去 markdown/emoji/括号指令)                             │       │
│  │ • 调用 VoxCPM /generate (dialect="四川话")                         │       │
│  │ • 失败时生成静音 WAV 作为 fallback                                 │       │
│  │ • 输出: audio/{script_id}/seg_00.wav, seg_01.wav...               │       │
│  │ • 输出: audio/durations.json ({script_id: {seg_idx: ms}})         │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 2: Timeline 对齐 (Realigner)                                            │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • 读取 audio/durations.json 获取实际音频时长                       │       │
│  │ • live2d_talk: duration_ms = 实际时长 + 200ms 缓冲                │       │
│  │ • 其他段: 保持脚本预设时长                                         │       │
│  │ • 从头顺推 start_ms，消除间隙/重叠                                 │       │
│  │ • 输出: scripts_aligned/{topic_id}.json                           │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 3: 素材渲染 (已完成)                                                    │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │                                                                    │       │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐   │       │
│  │  │ Live2D Worker    │  │ Visual Worker    │  │ Overlay Worker│   │       │
│  │  │                  │  │                  │  │               │   │       │
│  │  │ • Remotion +     │  │ • Remotion       │  │ • Remotion    │   │       │
│  │  │   pixi-live2d    │  │ • 图片/视频/     │  │ • 弹幕/卡片  │   │       │
│  │  │ • 音频驱动口型   │  │   动态效果       │  │ • VP9+alpha   │   │       │
│  │  │ • actionTimeline │  │ • ken_burns/     │  │               │   │       │
│  │  │   动态切换       │  │   video_clip     │  │               │   │       │
│  │  │ • 模型: mao_pro  │  │                  │  │               │   │       │
│  │  │ • VP9+alpha 输出 │  │                  │  │               │   │       │
│  │  │                  │  │                  │  │               │   │       │
│  │  │ → live2d/*.webm  │  │ → visual/*.mp4   │  │→ overlay/*.webm│  │       │
│  │  └──────────────────┘  └──────────────────┘  └───────────────┘   │       │
│  │                                                                    │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                              │                                                │
│                              ▼                                                │
│  Step 4: 最终合成 (FFmpeg, 已实现)                                            │
│  ┌────────────────────────────────────────────────────────────────────┐       │
│  │ • FFmpeg filter_complex 多层合成 (1080x1920 竖屏)                 │       │
│  │ • 合成层级 (从底到顶):                                             │       │
│  │   1. visual/{id}_visual.mp4 或纯色背景 (底层)                     │       │
│  │   2. live2d/{id}_live2d.webm (VP9 alpha, 右下角 80%)              │       │
│  │   3. overlay/{id}_overlay.webm (VP9 alpha, 全屏叠加)              │       │
│  │   4. audio/ 多段 WAV (adelay+amix 合并到正确时间位)               │       │
│  │ • 输出: final/{id}.mp4 (H.264 + AAC)                             │       │
│  └────────────────────────────────────────────────────────────────────┘       │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 模型配置

| 模型 | 用途 | 上下文 | 最大输出 |
|------|------|--------|----------|
| DeepSeek-V4-Flash | 选题/脚本/编排 | 1M | 384K |
| Gemma-4-26B (本地) | 备用 Worker | 262K | - |
| MiMo-v2.5-Pro | 文本处理 | 1M | 128K |
| MiMo-v2.5 | 图片识别 (Vision) | 1M | 128K |
| VoxCPM2 (WSL/CUDA) | TTS 四川话 | - | - |
| faster-whisper large-v3 | 音频转录 (WSL/CUDA) | - | ~3GB VRAM |

### 关键技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| TTS | VoxCPM2 | WSL CUDA，端口 8808，四川话方言 |
| ASR | faster-whisper large-v3 | WSL CUDA，视频音频转文字 |
| Live2D | pixi-live2d-display + Remotion | 离线渲染口播动画 (VP9 alpha WebM) |
| 数据卡片/Overlay | Remotion | React 组件渲染为视频片段 (VP9 alpha) |
| 最终合成 | FFmpeg filter_complex | 多层合成 + 音频合并 |
| 编码 | FFmpeg | 最终 MP4 输出 |
| 视频下载 | yt-dlp | 抖音视频直接下载（无需 cookie） |

---

## 三、目录结构

```
D:\workspace\videoFactory\
├── config.yaml              # 全局配置（模型/路径/参数）
├── config_loader.py         # 配置加载器
├── requirements.txt         # Python 依赖
├── agents/
│   ├── collector/           # Phase 1: 数据采集
│   │   ├── agent.py         # CollectorAgent (多平台采集)
│   │   └── run_collector.py # 入口脚本
│   ├── director/            # Phase 2: 选题 + 脚本
│   │   ├── agent.py         # DirectorAgent (选题/脚本/违禁词)
│   │   └── run_director.py  # 入口脚本
│   └── renderer/            # Phase 3: 渲染管线
│       ├── __init__.py
│       ├── run_render.py    # 入口脚本 (分步执行)
│       ├── media_downloader.py  # Step 0: 素材下载 (增量)
│       ├── media_recognizer.py  # Step 0.5: 图片识别 (mimo-v2.5)
│       ├── audio_transcriber.py # Step 0.6: 音频转录 (WSL whisper)
│       ├── tts.py           # Step 1: VoxCPM TTS
│       └── realigner.py     # Step 2: Timeline 对齐
├── scripts/
│   ├── run_pipeline.ps1     # 全流程 PowerShell 脚本
│   ├── start_tts.sh         # WSL 启动 VoxCPM
│   ├── start_tts.bat        # Windows 启动器
│   └── test_transcribe.sh   # WSL 转录测试
├── data/
│   └── {date}/
│       ├── collected/       # 采集的原始数据 (JSON)
│       ├── media/           # 下载的素材 + manifest.json
│       ├── selected/        # 选题结果
│       ├── scripts/         # 生成的脚本
│       ├── audio/           # TTS 音频 + durations.json
│       ├── scripts_aligned/ # 对齐后的脚本
│       ├── overlay/         # Overlay WebM
│       ├── visual/          # Visual MP4
│       ├── live2d/          # Live2D WebM
│       └── final/           # 最终成品
└── assets/                  # 静态资源 (Live2D模型等)
```

---

## 四、工作进度

### ✅ Phase 1: Collector (已完成)
- [x] 微博热搜采集
- [x] 抖音话题采集
- [x] HuggingFace 趋势采集
- [x] GitHub Trending 采集
- [x] OpenCLI 浏览器自动化集成
- [x] 多平台并行采集

### ✅ Phase 2: Director (已完成)
- [x] 选题排序 + 过滤（政治/负面/违禁品/迷信/导流）
- [x] 脚本生成（Mili 四川话人设 + card_type 卡片系统）
- [x] 违禁词规则（10 类抖音违禁词 + 四川话替换策略）
- [x] DeepSeek-V4 384K 输出配置
- [x] source_data 引用（图片/视频/评论）

### ✅ Phase 3: Renderer (已完成)
- [x] Step 0: 素材下载 (`media_downloader.py`)
  - [x] 微博图片下载
  - [x] 抖音视频 yt-dlp 直接下载（无需 cookie/浏览器）
  - [x] manifest.json 增量更新（不覆盖已有识别结果）
- [x] Step 0.5: 图片识别 (`media_recognizer.py`)
  - [x] mimo-v2.5 vision 识别
  - [x] 质量过滤（<200px 或 <10KB 跳过）
  - [x] 10 并发 + 空结果重试
  - [x] 128K max_tokens 详细描述
  - [x] 18 张图片 ~20 秒完成
- [x] Step 0.6: 音频转录 (`audio_transcriber.py`)
  - [x] WSL + CUDA + faster-whisper large-v3
  - [x] 9 分钟视频 47 秒转录
  - [x] 短句合并（531 段 → 50 段）
  - [x] 紧凑 segments 格式 [start, end, "text"]
  - [x] 12 个抖音视频已转录
- [x] Step 1: TTS (`tts.py`)
  - [x] VoxCPM2 HTTP 调用 (WSL CUDA, port 8808)
  - [x] 文本清洗 + 静音 fallback
  - [x] 40 个脚本全量 TTS 完成
- [x] Step 2: Timeline 对齐 (`realigner.py`)
  - [x] 音频时长修正 + 顺推 start_ms
  - [x] 多轨结构 (voice/live2d/visual/overlay/background)
  - [x] 40 个脚本对齐完成
- [x] Step 3a: Live2D 渲染 (`live2d_renderer.py`)
  - [x] Remotion + pixi-live2d-display + Cubism 4
  - [x] 音频驱动口型（每帧 RMS 音量 → ParamA）
  - [x] actionTimeline 动态切换表情/动作 (FORCE priority)
  - [x] 15 种 action: 8 表情 + 4 动作 + 3 特殊
  - [x] VP9 alpha 透明背景 WebM 输出
  - [x] 40 个脚本批量渲染
- [x] Step 3b: Visual 渲染 (`visual_renderer.py`)
  - [x] Remotion 渲染图片/视频/动态效果
  - [x] ken_burns / video_clip / remotion 组件
  - [x] 输出: visual/{id}_visual.mp4
- [x] Step 3c: Overlay 渲染 (`remotion_renderer.py`)
  - [x] comment_scroll / data_reveal / info_panel / highlight_text / quote_box
  - [x] VP9 alpha WebM 输出
  - [x] 输出: overlay/{id}_overlay.webm
- [x] Step 4: 最终合成 (`run_render.py` step_compose)
  - [x] FFmpeg filter_complex 多层合成
  - [x] 多段 WAV adelay+amix 时间轴合并
  - [x] 输出: final/{id}.mp4 (H.264 + AAC, 1080x1920)

---

## 五、2026-06-14 更新：视觉优化 + 角色差异化

### 已完成
- [x] 图片/视频全屏裁切铺满 (`force_original_aspect_ratio=increase` + `crop`)
- [x] Live2D 缩放+定位可调（当前 80% 宽度，右下角）
- [x] 角色差异化人设 (`agent.py` `_aggregated_system_prompt`)：
  - AI日报：科技达人，专业不枯燥，讲清"是什么/能干什么/适合谁用"
  - 热搜日报：搞笑正能量，接地气，快节奏，正能量收尾
- [x] Pipeline 加入 collect 步骤（`run_pipeline.ps1`）
- [x] f-string 与 JSON 大括号冲突修复（改用字符串拼接）
- [x] 素材编号系统 + 模糊匹配兜底
- [x] 视频间隙修复（realigner gap 上限 2s）
- [x] 超时修复（Remotion 渲染 60 分钟）
- [x] TTS 服务自动启动

### 进行中：新闻演播室风格重构
参考：VTuber 新闻主播画面布局（类似三立新闻厄伦蒂儿）

**竖屏适配方案：**
- 背景改为"新闻墙"（截图缩小平铺 + 高斯模糊）
- Live2D 半身居中（裁切腿部，类似新闻主播）
- 底部新闻条 ticker（红色标签 + 标题滚动）
- 频道 logo 角标
- 内容卡片叠在角色上方

### 关键配置

| 配置项 | 值 | 文件 |
|--------|-----|------|
| Remotion 超时 | 3600s (60min) | `remotion_renderer.py`, `visual_renderer.py` |
| Realigner gap 上限 | 2000ms | `realigner.py` |
| Live2D 合成尺寸 | 80% 宽度 (864x1536) | `run_render.py` |
| Live2D 位置 | 右下角 (x=216, y=384) | `run_render.py` |
| 图片缩放策略 | increase + crop（全屏铺满） | `visual_renderer.py` |
| 视频缩放策略 | increase + crop（全屏铺满） | `visual_renderer.py` |

---

## 六、后续计划

### 近期 (视觉重构)
1. **新闻演播室风格**
   - 新闻墙背景组件
   - Live2D 半身裁切居中
   - 底部 ticker 新闻条
   - 频道 logo 角标
2. **卡片进场动画**
   - 入场：滑入 + 淡入 (300ms)
   - 退场：滑出 + 淡出 (200ms)
   - 悬浮呼吸动画

### 中期优化
3. **内容多样性**
   - ScreenshotFrame（设备边框包装截图）
   - ProgressBar（当前新闻进度）
   - TopicTag（话题标签云）
4. **Live2D 渲染升级**
   - 考虑升级到 Cubism 5 SDK
   - Special 动作特效修正
5. **多角色支持**
   - 不同 Live2D 模型切换
   - 不同方言/风格
6. **自动发布**
   - 抖音 API 自动上传
   - 定时发布调度

---

## 七、注意事项

### ⚠️ manifest.json 数据安全
- `media_downloader.py` 已改为增量更新，先加载已有 manifest 再合并
- 图片识别 (recognizer) 和音频转录 (transcriber) 只更新各自字段
- **不会互相覆盖**——各模块写不同字段

### ⚠️ 抖音视频下载
- 使用 yt-dlp 直接下载，无需 cookie 或浏览器
- `visual_assets.video_url` 为空时，用顶层 `url` 字段
- 下载速度约 20MB/s

### ⚠️ WSL 相关
- **音频转录**: 通过 `wsl bash` 调用 faster-whisper (WSL Python + CUDA)
- **TTS**: VoxCPM2 在 WSL 中运行 (端口 8808，Windows 可直接访问)
- **HF_TOKEN**: 配置在 WSL `~/.bashrc` 和 `config.yaml` 中
- faster-whisper 模型缓存在 WSL `~/.cache/huggingface/`

### ⚠️ 违禁词
- 10 类违禁词已内置到 Director prompt
- 极限用语/虚假承诺/诱导/时限恐慌/权威背书/医疗/迷信/导流/不文明/违禁品
- 替换策略：用四川话俚语代替可能触发审核的词汇

### ⚠️ TTS 时长对齐
- 脚本中的 `duration_ms` 是预估值，TTS 实际时长会不同
- Realigner 用实际音频时长重新计算所有 segment 的 start_ms
- 每个 live2d_talk segment 加 200ms 尾部缓冲

### ⚠️ Live2D 渲染
- 使用 Remotion + pixi-live2d-display 离线渲染
- 模型路径: `remotion/public/live2d/mao_pro/`
- Motion group: `Idle` (mtn_01) + `Action` (mtn_02~04, special_01~03)
- Expression: exp_01 ~ exp_08
- actionTimeline 系统: 按帧精确切换 motion/expression
- **必须用 priority=3 (FORCE)** 才能覆盖当前播放的 motion
- Special 动作 (sp_*) 带 Multiply blend 特效，在透明背景下渲染异常
  - 方案 D: compose 阶段叠加到底层背景上自然修正

### ⚠️ 图片识别
- mimo-v2.5（非 pro）才支持 vision
- 偶发空结果或 "无法查看图片" 幻觉，已加重试机制
- 过滤: <200px 或 <10KB 的缩略图直接跳过
- 10 并发，18 张图约 20 秒完成

### ⚠️ Compose 合成
- VP9 alpha WebM 解码必须指定 `-vcodec libvpx-vp9`
- Live2D 层缩放到 80% 宽度，右下角定位 (x=216, y=384)
- 音频合并: adelay 定位 + amix (normalize=0 防止音量衰减)

---

## 八、运行命令速查

```powershell
# 全流程 Pipeline（推荐）
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 -Date 2026-06-14
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 -Date 2026-06-14 -From tts
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 -Date 2026-06-14 -From tts -SkipDirector
```

```bash
# 分步执行
python -m agents.collector.run_teams --date 2026-06-14
python -m agents.director.run_director --date 2026-06-14
python -m agents.renderer.run_render --step tts --date 2026-06-14
python -m agents.renderer.run_render --step align --date 2026-06-14
python -m agents.renderer.run_render --step render --date 2026-06-14
python -m agents.renderer.run_render --step visual --date 2026-06-14
python -m agents.renderer.run_render --step live2d --date 2026-06-14
python -m agents.renderer.run_render --step compose --date 2026-06-14
```

---

## 九、已知问题与修复记录

| 日期 | 问题 | 解决方案 |
|------|------|----------|
| 06-14 | f-string 与 JSON 大括号冲突 | 改用字符串拼接 |
| 06-14 | Pipeline 无 collect 步骤 | 加入 run_pipeline.ps1 |
| 06-14 | 角色人设不区分视频类型 | `_aggregated_system_prompt` 按 video_type 差异化 |
| 06-14 | 图片/视频有大片黑边 | scale 改为 increase+crop（全屏铺满） |
| 06-13 | 视频段落间 8-11s 空白 | realigner gap 上限 2000ms |
| 06-13 | Remotion 渲染超时 | 超时改为 3600s |
| 06-13 | Live2D motion 切换不生效 | model.motion() 需要 priority=3 (FORCE) |
| 06-13 | 空字符串 motion group 不生效 | model3.json 中改为 "Action" group |
| 06-12 | Special 动作特效变黑 | Multiply blend 在透明/深色背景下失效，方案 D: compose 阶段处理 |
| 06-12 | Live2D 动画速度过快 | 手动 model.update(dt) 替代 requestAnimationFrame |
| 06-11 | ctranslate2 Windows 下无法加载 | 改用 WSL subprocess 调用 |
| 06-11 | manifest.json 各步骤互相覆盖 | media_downloader 改为增量更新 |
| 06-11 | 抖音下载需要 cookie/浏览器 | 改用 yt-dlp 直接下载 |
| 06-11 | whisper 转录结果太碎 (531段) | 合并短句 (间隔>1.5s 或 >50字断句) |
| 06-09 | MiMo 识别返回空结果 | 重试机制 + 清理 prompt |

---

## 十、依赖环境

| 环境 | 说明 |
|------|------|
| Python 3.11+ | 主环境 (Anaconda) |
| WSL2 + CUDA | VoxCPM TTS + faster-whisper 运行环境 |
| Node.js 18+ | Remotion / HyperFrame |
| FFmpeg | 视频编码 + 音频提取 |
| yt-dlp | 抖音视频下载 |
| OpenCLI | 浏览器自动化（采集阶段） |
| Pillow | 图片质量检测 |
| openai SDK | API 调用 (DeepSeek/MiMo) |
| faster-whisper | WSL 音频转录 |
