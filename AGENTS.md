# AGENTS.md — VideoFactory 项目指南

> 本文件面向 AI 编码代理，假设读者对本项目一无所知。
> 正式文档集中在 `docs/`，本文件是其入口与补充，如与 `docs/` 冲突以 `docs/` 为准。

## 项目概述

VideoFactory 是一个全自动 AI 短视频生产管线：每天从微博、抖音、HuggingFace、GitHub 采集热点，经 LLM 编排生成多轨脚本，最终合成带 Live2D 虚拟角色（Mili，四川话口播人设）的竖屏（9:16, 1080x1920）短视频。

最终产物（按日期输出到 `data/{yyyy-MM-dd}/final/`）：

- `hot_daily.mp4` — 热搜集锦（微博 + 抖音），约 7-8 分钟
- `ai_daily.mp4` — AI 日报（HuggingFace + GitHub），约 4-5 分钟

仓库里并存两套系统：

1. **传统脚本管线**：`scripts/run_pipeline.ps1` 串联 10 个步骤，核心代码在 `agents/`（collector → director → renderer）。
2. **可视化 node workflow 系统**（当前开发主线）：FastAPI 后端（`server/`）+ React Flow 画布前端（`web/`）+ 工作流 JSON（`workflows/`），同一管线被拆成可编排的节点。节点体系文档见 `docs/NODE_SYSTEM_RUNTIME.md` 与 `docs/CUSTOM_NODES.md`。

## 技术栈

- **Python 3.11**（当前 3.11.5）：FastAPI + uvicorn（工作流后端）、openai SDK（LLM 调用）、pydantic、pyyaml、psutil、croniter、faster-whisper（音频转写）
- **Node.js v22**：
  - `web/`：React 19 + Vite 8 + @xyflow/react（React Flow）+ react-router 7，lint 用 oxlint
  - `remotion/`：Remotion 4.0.475 + TypeScript，渲染 overlay 卡片与 Live2D 动画（pixi-live2d-display）
- **外部工具/服务**：

| 服务 | 地址 | 用途 |
|------|------|------|
| VoxCPM2 TTS | `http://127.0.0.1:8808` | 四川话语音合成，跑在 WSL Ubuntu + CUDA 里 |
| LM Studio | `http://127.0.0.1:1234` | 本地 Gemma-4 视觉理解 |
| DeepSeek API | `https://api.deepseek.com/v1` | 编排/选题/脚本生成主力 LLM |
| MiMo v2.5 | `https://token-plan-cn.xiaomimimo.com/v1` | 图片识别（Vision） |
| OpenCLI | 本地 Node 工具（`D:/workspace/opencli`） | 浏览器自动化采集 |
| FFmpeg | 系统 PATH | 视频合成 |

- **运行环境**：Windows 工作站（PowerShell / Git Bash），TTS 依赖 WSL。无 CI、无容器化、无正式部署流程，均为本地运行。

## 目录结构与模块划分

```
videoFactory/
├── config.yaml            # 全局配置（模型池/角色/采集/TTS/合成参数），含密钥，已被 gitignore
├── config_loader.py       # 配置加载：load_config / get_model_config / get_worker_model_config / ensure_dirs
├── requirements.txt       # Python 依赖（无 pyproject.toml / setup.py，非打包项目）
├── run_server.py          # 可视化工作流后端入口：python run_server.py（自动选 8100 起的空闲端口）
│
├── agents/                # 传统管线核心
│   ├── collector/         # 采集：orchestrator.py（选题+调度）、worker.py（平台 Worker）、sources.py、run_teams.py（入口）
│   ├── director/          # 脚本：agent.py（DirectorAgent）、run_director.py（入口）
│   └── renderer/          # 渲染：run_render.py（步骤调度入口）+ media_downloader / media_recognizer /
│                          #   audio_transcriber / tts / fish_tts / realigner / remotion_renderer /
│                          #   visual_renderer / live2d_renderer / live2d_mapping / layout_validator / visual_qa
│
├── server/                # 可视化工作流后端
│   ├── models.py          # PipelineContext（产出仓库模式：ctx.write/read/find_by_type/emit）
│   ├── api/               # REST/WS 路由：workflows / nodes / runs / settings / scripts / node_packs / custom_nodes / tools
│   ├── engine/            # executor.py（拓扑排序 + asyncio 并发 + 生命周期 + 停止）、node_cache.py、run_store.py（运行历史 SQLite）
│   ├── nodes/             # base.py（BaseNode/TriggerNode/ListenerNode）、registry.py（@node 装饰器）、
│   │                      # loader.py + pack_manager.py（节点包加载/安装）、collect.py 等内置管线节点、
│   │                      # builtin/（cron_trigger、wechat/feishu/dingtalk channel）
│   ├── prompts/           # LLM 提示词（director、recognize、collect 等 .txt）
│   ├── tools/             # 自定义工具（python_runner 等）
│   └── ai/                # generation_agent.py
│
├── web/                   # 前端（Vite + React）
│   └── src/
│       ├── pages/         # WorkflowEditor.jsx、WorkflowList.jsx、SettingsPage.jsx、TimelinePage.jsx 等
│       ├── components/    # PropertiesPanel、LogPanel、RunHistoryPanel、CronEditor、PipelineNode 等
│       └── api.js         # API/WS 地址从当前页面动态推导
│
├── remotion/              # Remotion TS 项目：Root.tsx、Composition.tsx、Live2DComposition.tsx、
│                          # VisualComposition.tsx + src/components/（CommentScroll、ModelCard 等卡片组件）
│
├── workflows/             # 工作流 JSON（default.json 由服务端首次启动自动生成）
├── settings/global.json   # 全局设置（模型池，前端设置页可编辑）
├── nodes/community/       # 社区节点包安装位置（vf-node.yaml 清单）
├── scripts/               # 运维脚本：run_pipeline.ps1（主管线）、scheduler.ps1（定时）、start_tts.bat、
│                          # step_*.bat（单步快捷方式）、大量 check_*/debug_* 临时验证脚本
├── assets/                # 静态资产：studio/（演播室背景/前景/流星特效）、voice/（TTS 参考音频）
├── data/                  # 运行时数据，按日期分目录（collected/media/scripts/audio/overlay/visual/live2d/final），gitignored
├── docs/                  # 正式文档（见下方索引）
├── skills/                # 工程级 agent skills：custom-node-author、antigravity-bridge
└── test_*.py              # pytest 测试（仓库根目录）
```

管线 10 步：`collect → download → recognize → director → tts → align → overlay → visual → live2d → compose`（每步的输入输出目录与耗时见 `docs/pipeline.md`）。

## 构建与运行命令

### 安装依赖

```bash
pip install -r requirements.txt
cd web && npm install
cd remotion && npm install
```

### 可视化工作流系统（当前主线）

```bash
# 启动后端（同时托管 web/dist 构建产物；自动从 8100 起选空闲端口）
python run_server.py

# 前端开发（Vite dev server :5173，后端 CORS 已放行 5173/8100）
cd web && npm run dev

# 前端构建（产物 web/dist 由后端托管）与 lint
cd web && npm run build
cd web && npm run lint        # oxlint
```

注意：`run_server.py` 始终以 `reload=False` 运行，开发时不要开 uvicorn reload（已知会导致进程退出/重载干扰）。

### 传统脚本管线

```powershell
# 完整管线（可加 -Date 2026-06-24 / -From tts / -SkipDirector）
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1

# 单步执行（step 可选 collect/download/recognize/director/tts/align/overlay/visual/live2d/compose）
python -m agents.renderer.run_render --step download
python -m agents.collector.run_teams
python -m agents.director.run_director

# 定时执行
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Cron "0 8 * * *"
```

TTS 服务未运行时管线会自动尝试启动 WSL 中的 VoxCPM2；手动启动方式与 WSL 踩坑记录（必须用 `bash -lc`、不能用最小化窗口等）见 `docs/pipeline.md` 故障排查章节。

### Remotion

```bash
cd remotion && npm run studio    # 预览
# 实际渲染由 Python 侧（remotion_renderer.py / live2d_renderer.py）调用 npx remotion render 完成
```

## 测试

- 测试框架：**pytest 8.3.3**，测试文件是仓库根目录的 `test_*.py`（如 `test_node_cache_clear.py`、`test_node_progress.py`、`test_voice_tts_constraints.py`、`test_review_fixes.py`）。
- 异步测试用 `unittest.IsolatedAsyncioTestCase` 风格编写，pytest 直接收集运行：

```bash
python -m pytest                      # 跑全部
python -m pytest test_node_cache_clear.py -v
```

- 无 pytest.ini / pyproject.toml / CI 配置。`scripts/` 下的 `check_*.py`、`debug_*.py`、`test_*.py` 是人工排查用的一次性脚本，不属于 pytest 测试套件，不要把新测试放进 `scripts/`。

## 代码规范与开发约定

- **语言**：代码注释、文档、commit message 均使用中文；标识符用英文。
- **节点体系术语**：统一用 `node` / `node pack` / `node runtime`，禁止使用 `plugin` 术语。
- **新增节点**必须遵循 `docs/CUSTOM_NODES.md`（动手前必读，另有 `skills/custom-node-author` skill）：
  - `config_schema`（属性面板配置）与 `inputs`/`outputs`（画布连线桩）严格分离，不要把配置项写成连线桩。
  - 生命周期：`prepare → validate → check_cache → execute → on_error → finalize`；长任务必须调用 `on_progress` 上报进度；资源清理放 `finalize`。
  - 日志只用 `ctx.logger`，不要直接用全局 logging。
  - 缓存默认关闭（`cacheable = False`），LLM 等非幂等节点不要开缓存；需要精细命中条件时覆写 `check_cache()`（参考内置 `collect` 节点按"日期 + 已选站点"命中）。
  - 数据传递三方式：声明式连线（`self.get_input`）、上下文仓库（`ctx.read` / `ctx.find_latest_by_type`）、消息总线（`ctx.emit`）。
- **最小改动**：`agents/` 与 `server/nodes/` 的管线节点存在对应关系（节点是对 agent 步骤的包装），改动时注意两侧一致性，但不要顺手重构无关代码。
- **前端**：函数组件 + Hooks；oxlint 强制 `react/rules-of-hooks`；API/WS 地址必须从当前页面 URL 动态推导（不要硬编码 localhost 端口）。
- **工作流存储**：工作流是 `workflows/*.json` 纯文件；运行历史存 SQLite（`server/engine/run_store.py`）。

## 配置与密钥安全

- `config.yaml` 含有**真实 API 密钥**（DeepSeek、MiMo、HF token），已在 `.gitignore` 中、未被 git 跟踪，**绝不要提交、打印或外发其内容**。需要改密钥时通过环境变量 `DIRECTOR_API_KEY` 覆盖或直接编辑本地文件。
- `settings/global.json` 同样含 API 密钥，`douyin_cookies.txt/json` 含抖音登录 Cookie——这两个文件**当前已被 git 跟踪**（历史原因），修改时注意不要再往里新增敏感信息。
- `config_loader.load_config()` 有特殊回退逻辑：worktree 中找不到 `config.yaml` 时回退到主仓库 `d:\workspace\videoFactory\config.yaml`，相对路径 `data_root` 也会解析到主仓库的 `data/`。修改配置加载逻辑时必须保持这一行为。
- 注意 `config.yaml` 里存在**两段 `tts:` 配置**（voxcpm2 与 voxcpm），PyYAML 解析时后一段生效；编辑 TTS 配置时先确认实际生效的是哪段。
- `data/` 与 `server_*.log` 是本地产物，已被 gitignore，不要提交。

## 外部依赖的运行前提

跑通完整管线需要本机具备：WSL Ubuntu（VoxCPM2 TTS，模型在 `~/.cache/huggingface`）、LM Studio（Gemma-4）、OpenCLI + Chrome 扩展（采集）、FFmpeg、Live2D 模型（路径硬编码在 `config.yaml` 的 `live2d.model_path`，指向 `D:/workspace/Open-LLM-VTuber`）。缺少任一服务时对应步骤会失败，但其余步骤可独立运行/测试——写测试时避免依赖这些外部服务。

## 文档索引

| 文档 | 内容 |
|------|------|
| `docs/codebase.md` | 整体结构、管线 10 步详解、调用关系图、数据格式、设计决策 |
| `docs/pipeline.md` | 传统管线用法、参数、故障排查（含 WSL TTS 踩坑）、定时任务 |
| `docs/CUSTOM_NODES.md` | 自定义节点开发规范（Processor/Trigger/Listener、生命周期、缓存、前后端协议、节点包） |
| `docs/NODE_SYSTEM_RUNTIME.md` | 当前 node runtime 实现状态、缓存语义、已知限制、验证清单 |
| `docs/REVIEW_2026-07-08.md` | node 系统重构的外部评审记录 |
| `skills/custom-node-author/SKILL.md` | 手写节点的工程级 skill（写节点前先读） |

注意：`README.md` 的"快速开始"部分已过时（提到不存在的 `orchestrator.py` 和 `config.example.yaml`），以上表和 `docs/` 为准。根目录的 `PROJECT_STATUS.md`、`implementation_plan.md`、`custom-feature.md`、`Fixing/Resolving Audio ... .md` 是历史过程稿，仅供背景参考。
