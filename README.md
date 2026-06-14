# AI 自动化短视频生产管线

## 快速开始

```powershell
# 1. 确保 OpenCLI 浏览器扩展已安装
# 从 D:\workspace\opencli\extension\dist\ 加载到 Chrome (开发者模式)

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入你的 API Key

# 4. 运行采集
python -m agents.collector.run

# 5. 运行完整管线
python orchestrator.py
```

## 架构

```
Layer 1: 数据采集 (OpenCLI) → 微博热搜 / 抖音热榜 / AI新闻
Layer 2: 内容理解 (Gemma-4-26B / VibeVoice) → 视频理解 / 音频转录
Layer 3: 编排决策 (Director Agent) → 选题 / 脚本 / 分镜
Layer 4: 视频合成 (FFmpeg + Live2D + VoxCPM2) → 成品视频
```
 

现在还是一个agent跑收集么，你看看这篇文章，https://code.claude.com/docs/en/agent-teams，我们能采用这个架构么，并发采集会不会快很多，另外我把本地lm studio 的模型启动起来，尝试一下作为子agent模型看看效果怎么样，他的上下文长度是262144

生成脚本的时候注意违禁词，具体哪些违禁词需要你去搜一下抖音 视频 违禁词

我突然想起来，是不没有安排下载素材：图片，视频，音频的识别？

抖音有个字段叫url字段，这里的链接浏览器打开可以播放

有些下载的图片很小，很模糊，这种类型的图片，就不要了，识别的提示词写好一些，尽量将素材描述的详细一点

图片识别给个并发调用，并发最大10张


hf token: (see config.yaml)

如果你让大模型生成的卡片里应该还有效果描述

powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 -Date 2026-06-12