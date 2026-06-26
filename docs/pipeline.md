# VideoFactory 管线使用文档

## 概览

管线脚本 `scripts/run_pipeline.ps1` 负责串联整个视频生产流程，从数据采集到最终成片输出。

```
Collect → Download → Recognize → Director → TTS → Align → Overlay → Visual → Live2D → Compose
```

最终输出: `data/{日期}/final/hot_daily.mp4` + `ai_daily.mp4`

---

## 快速使用

```powershell
# 跑今天的完整管线
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1

# 指定日期
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24

# 从某一步开始（跳过前面的步骤）
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From tts

# 跳过 Director（使用已有脚本）
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -SkipDirector
```

---

## 管线步骤详解

| 步骤 | 说明 | 耗时 | 输出 |
|------|------|------|------|
| **collect** | 采集微博热搜、抖音热榜、AI新闻 | 3-5 min | `data/{date}/collected/` |
| **download** | 下载素材视频、图片 | 2-5 min | `data/{date}/media/` |
| **recognize** | 图片/视频内容识别（Gemma-4） | 3-8 min | 写入 collected JSON |
| **director** | LLM 生成脚本（选题+编排） | 2-5 min | `data/{date}/scripts/*.json` |
| **tts** | VoxCPM2 四川话语音合成 | 3-5 min | `data/{date}/audio/` |
| **align** | 时间轴对齐（实际音频时长） | <1 min | `data/{date}/scripts_aligned/*.json` |
| **overlay** | Remotion 渲染透明卡片/弹幕 | 3-8 min | `data/{date}/overlay/*.webm` |
| **visual** | 背景视觉层合成 | 2-5 min | `data/{date}/visual/*.mp4` |
| **live2d** | Live2D 角色动画渲染 | 30-50 min | `data/{date}/live2d/*.webm` |
| **compose** | FFmpeg 最终合成 | 2-3 min | `data/{date}/final/*.mp4` |

总耗时约 50-80 分钟（Live2D 渲染占大头）。

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-Date` | string | 今天 | 处理日期，格式 `yyyy-MM-dd` |
| `-From` | string | `collect` | 从哪一步开始执行 |
| `-SkipDirector` | switch | false | 跳过 Director 步骤 |

**`-From` 可选值：**
`collect`, `download`, `recognize`, `director`, `tts`, `align`, `overlay`, `visual`, `live2d`, `compose`

---

## 常用场景

### 修改脚本后重新渲染
```powershell
# 只需从 TTS 开始（脚本已修改，需要重新合成语音）
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From tts
```

### 只重新合成视频（音频/视觉已就绪）
```powershell
# 只跑最后的合成步骤
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From compose
```

### 重新生成 Live2D 动画
```powershell
# 先删除旧的 live2d 文件
Remove-Item "data/2026-06-24/live2d/hot_daily*" -Force
# 从 live2d 步骤开始
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From live2d
```

### 重新选题+生成脚本
```powershell
# 先清理旧脚本
Remove-Item "data/2026-06-24/scripts/hot_daily*" -Force
# 从 director 开始
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From director
```

---

## 依赖服务

| 服务 | 地址 | 说明 |
|------|------|------|
| VoxCPM2 TTS | `http://127.0.0.1:8808` | WSL 中运行，管线会自动启动 |
| LM Studio | `http://127.0.0.1:1234` | 本地 LLM（子 agent 用） |
| Remotion | Node.js | overlay/live2d 渲染用 |

TTS 服务如果未运行，管线会自动启动（等待最多 90 秒加载模型）。

---

## 输出目录结构

```
data/2026-06-24/
├── collected/          # 采集的原始数据
├── media/              # 下载的素材（视频/图片）
├── scripts/            # Director 生成的脚本
├── scripts_aligned/    # 时间轴对齐后的脚本
├── audio/              # TTS 语音文件
│   ├── hot_daily/      # voice_00.wav ~ voice_56.wav
│   └── ai_daily/
├── overlay/            # 透明卡片 WebM
├── visual/             # 背景视觉层 MP4
├── live2d/             # Live2D 动画 WebM
└── final/              # 最终成片
    ├── hot_daily.mp4   # 热搜集锦（~80MB, 7-8分钟）
    └── ai_daily.mp4    # AI日报（~50MB, 4-5分钟）
```

---

## 故障排查

### TTS 启动失败
```powershell
# 手动启动 TTS 服务
wsl -d Ubuntu -- bash -lc "cd ~ && export TORCH_MATMUL_PRECISION=high && python3 ~/tts_server.py --port 8808 --device cuda --reference-wav ~/baoer.mp3"
```

### 某步骤失败后恢复
管线失败会停在出错的步骤。修复问题后用 `-From` 参数从该步骤继续：
```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From overlay
```

### 视频损坏（moov atom not found）
通常是 compose 被中断。删除损坏文件重新跑：
```powershell
Remove-Item "data/2026-06-24/final/hot_daily.mp4" -Force
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From compose
```

### 清除缓存完全重跑
```powershell
# 删除某个视频的所有中间产物
Remove-Item "data/2026-06-24/scripts/hot_daily*" -Force
Remove-Item "data/2026-06-24/scripts_aligned/hot_daily*" -Force
Remove-Item "data/2026-06-24/audio/hot_daily" -Recurse -Force
Remove-Item "data/2026-06-24/overlay/hot_daily*" -Force
Remove-Item "data/2026-06-24/visual/hot_daily*" -Force
Remove-Item "data/2026-06-24/live2d/hot_daily*" -Force
Remove-Item "data/2026-06-24/final/hot_daily*" -Force

# 从头开始
powershell -ExecutionPolicy Bypass -File scripts/run_pipeline.ps1 -Date 2026-06-24 -From director
```

---

## 定时执行

使用 `scripts/scheduler.ps1` 可以设置定时规则，自动跑全流程。

### 交互式配置
```powershell
# 运行后弹出菜单，选择定时模式
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1
```

### Cron 表达式
```powershell
# 每天 8:00 自动跑
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Cron "0 8 * * *"

# 每天 8:00 和 20:00 跑两次
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Cron "0 8,20 * * *"

# 工作日 9:00 跑
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Cron "0 9 * * 1-5"
```

### 固定间隔
```powershell
# 每 120 分钟跑一次（立即开始第一次）
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Interval 120
```

### 单次定时
```powershell
# 今天 08:00 跑一次
powershell -ExecutionPolicy Bypass -File scripts/scheduler.ps1 -Once "08:00"
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `-Cron` | string | Cron 表达式（分 时 日 月 周） |
| `-Interval` | int | 间隔分钟数 |
| `-Once` | string | 单次执行时间（HH:mm） |
| `-From` | string | Pipeline 起始步骤，默认 `collect` |
| `-DryRun` | switch | 测试模式，不实际执行 |

### 注意事项

- 脚本运行期间终端窗口需要保持打开，Ctrl+C 停止
- 日志自动保存到 `data/{date}/logs/`
- 每小时打印心跳确认脚本在运行
- Cron 格式：`分 时 日 月 周`（标准 5 字段）
