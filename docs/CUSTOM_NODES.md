# VideoFactory 自定义节点开发规范

> 当前分支统一使用 `node` 概念。
> `plugin` 术语不再用于节点体系，避免和后续插件能力混淆。

## 概览

VideoFactory 当前节点体系支持三类节点：

1. **Processor**：一次性处理节点，如 `collect`、`director`、`tts`
2. **Trigger**：定时或周期性触发节点，如 `cron_trigger`
3. **Listener**：长连接监听节点，如 `wechat_channel`、`feishu_channel`

节点来源支持三种方式：

1. **内置节点**：随主项目分发，位于 `server/nodes/` 与 `server/nodes/builtin/`
2. **本地目录安装**：从本地 node pack 目录安装
3. **Git / pip 安装**：从 Git 仓库或 pip 包加载 node pack

## 快速开始

### 最小 Processor 节点

```python
from server.nodes.base import BaseNode, NodeOutput
from server.nodes.registry import node


@node("hello_world", version="1.0.0", author="you", icon="👋", color="#4CAF50")
class HelloNode(BaseNode):
    label = "Hello World"
    category = "示例"
    description = "输出一段问候语"

    outputs = [
        NodeOutput(name="greeting", type="string", label="问候语"),
    ]

    config_schema = {
        "name": {
            "type": "string",
            "label": "名字",
            "default": "World",
            "description": "要问候的对象",
        }
    }

    async def execute(self, ctx, on_progress) -> dict:
        name = self.get_config("name", "World")
        on_progress("生成问候语...", 0.5)
        return {"greeting": f"Hello, {name}!"}
```

### 最小 Trigger 节点

```python
import asyncio
from datetime import datetime

from server.nodes.base import TriggerNode, NodeOutput
from server.nodes.registry import node


@node("demo_trigger", version="1.0.0", icon="⏰")
class DemoTriggerNode(TriggerNode):
    label = "演示触发器"
    category = "触发器"

    outputs = [
        NodeOutput(name="trigger", type="Trigger", label="触发信号"),
    ]

    config_schema = {
        "interval_s": {"type": "int", "label": "间隔秒数", "default": 60, "min": 1}
    }

    async def listen(self, ctx, emit):
        while True:
            await asyncio.sleep(self.get_config("interval_s", 60))
            await emit({"triggered_at": datetime.now().isoformat()})
```

### 最小 Listener 节点

```python
from server.nodes.base import ListenerNode, NodeInput, NodeOutput
from server.nodes.registry import node


@node("demo_listener", version="1.0.0", icon="📡")
class DemoListenerNode(ListenerNode):
    label = "演示监听器"
    category = "监听器"
    bidirectional = True

    inputs = [
        NodeInput(name="reply", type="Reply", label="回复内容", connected=True),
    ]
    outputs = [
        NodeOutput(name="message", type="Message", label="收到的消息"),
    ]

    async def listen(self, ctx, emit):
        event = {"message": {"text": "hello from listener"}}
        await emit(event)

    async def send_reply(self, ctx, reply_data):
        ctx.logger.info(f"reply => {reply_data}")
```

## 节点包结构

每个 node pack 根目录需要一个 `vf-node.yaml` 清单：

```yaml
name: my_nodes
version: 1.0.0
author: Your Name <you@example.com>
description: 我的自定义节点包
homepage: https://github.com/you/my-vf-nodes
license: MIT

nodes:
  - path: nodes/hello.py
  - path: nodes/demo_trigger.py

dependencies:
  python:
    - requests>=2.28
  system:
    - ffmpeg
  vf: ">=0.1.0"

web:
  entry: web/index.js

changelog:
  1.0.0: "初始版本"
```

## 生命周期

所有 Processor 节点遵循统一生命周期：

```text
prepare(ctx)
  -> validate(ctx)
  -> check_cache(ctx)
  -> restore_cache(ctx)   # 仅缓存命中时
  -> execute(ctx, on_progress)
  -> on_error(ctx, error) # 仅 execute 异常时
  -> finalize(ctx, success)
```

### 生命周期钩子说明

| 钩子 | 必需 | 调用时机 | 用途 |
|------|------|---------|------|
| `prepare(ctx)` | 否 | 执行前 | 初始化外部资源、做健康检查 |
| `validate(ctx)` | 否 | `prepare` 后 | 校验上游数据与当前配置 |
| `check_cache(ctx)` | 否 | `validate` 后 | 自定义缓存命中逻辑 |
| `restore_cache(ctx)` | 否 | 缓存命中时 | 从磁盘恢复运行产出 |
| `execute(ctx, on_progress)` | 是 | 核心执行 | 返回 outputs dict |
| `on_error(ctx, error)` | 否 | 执行异常时 | 回滚、副作用清理 |
| `finalize(ctx, success)` | 否 | 最后执行 | 释放连接、临时文件、显存 |

Trigger / Listener 节点不走 `execute()` 主路径，而是实现 `listen(ctx, emit)`。

## 输入输出与配置分离

当前体系里，**连线桩** 和 **前端配置项** 是两套定义，必须分开：

- `inputs` / `outputs`：给画布连线用
- `config_schema`：给右侧属性面板用

### 连线桩示例

```python
inputs = [
    NodeInput(
        name="collected",
        type="CollectedData",
        label="采集数据",
        connected=True,
        description="来自上游采集节点",
    )
]

outputs = [
    NodeOutput(name="scripts", type="ScriptsData", label="脚本"),
]
```

### 配置项示例

```python
config_schema = {
    "orchestrator_model": {
        "type": "model",
        "label": "编排模型",
        "default": "deepseek-v4-flash",
    },
    "max_workers": {
        "type": "int",
        "label": "并发数",
        "default": 4,
        "min": 1,
        "max": 8,
    },
}
```

### 字段类型

| type | UI 形态 | 示例 |
|------|---------|------|
| `string` | 文本输入 | token、路径 |
| `int` / `float` | 数字输入 | 并发数、温度 |
| `bool` | 开关 | enable_cache |
| `list` | 列表输入 | platforms |
| `enum` | 下拉框 | codec |
| `model` | 模型下拉框 | deepseek-v4-flash |
| `text` | 大文本编辑器 | prompt |
| `file` / `path` | 路径输入 | 参考音频、素材路径 |
| 自定义类型 | 连线类型 | `CollectedData`、`Reply` |

## 数据传递

### 方式一：声明式连线

```python
from server.nodes.base import BaseNode, NodeInput, NodeOutput


class MyNode(BaseNode):
    inputs = [
        NodeInput(name="collected", type="CollectedData", connected=True),
    ]
    outputs = [
        NodeOutput(name="result", type="MyResult"),
    ]

    async def execute(self, ctx, on_progress) -> dict:
        collected = self.get_input("collected")
        return {"result": process(collected)}
```

### 方式二：直接访问上下文仓库

```python
async def execute(self, ctx, on_progress) -> dict:
    latest_scripts = ctx.find_latest_by_type("ScriptsData")
    raw_value = ctx.read("collect_1", "collected")
    return {"result": raw_value}
```

### 方式三：消息总线

```python
async def execute(self, ctx, on_progress) -> dict:
    ctx.emit("download_progress", {"done": 3, "total": 10})
    return {"result": "ok"}
```

## 缓存语义

### 默认行为

- `cacheable = False`：默认不缓存
- 适用于 LLM 节点、通道节点、外部实时事件节点

### 显式缓存

节点需要缓存时，显式声明：

```python
class DownloadNode(BaseNode):
    cacheable = True

    def fingerprint(self, ctx) -> str:
        collected = self.get_input("collected")
        payload = {
            "config": self.config,
            "files": collected.files,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
```

### 自定义缓存命中

对于不能只靠 `fingerprint()` 的节点，允许覆写 `check_cache()`。

当前内置 `collect` 节点就是这种情况：

- 按 `date + enabled platforms` 判断缓存命中
- 只有当前日期下，所选站点都已经有采集产物时才跳过采集
- 例如只选了 `weibo` 与 `github`，则这两个站点当天都产出过 `YYYY-MM-DD_<platform>_*.json` 才算命中

## 运行模式

工作流 `mode` 支持三种：

| mode | 说明 | 典型入口 |
|------|------|----------|
| `manual` | 用户点击运行，一次性执行 DAG | 普通生产工作流 |
| `scheduled` | Trigger 节点长驻，到点触发下游子图 | `cron_trigger` |
| `listener` | Listener 节点常驻，收到事件触发下游 | `wechat_channel` |

## 前后端协议

### `GET /api/nodes`

后端返回当前节点定义、节点包和全局配置：

```json
{
  "nodes": [
    {
      "type": "collect",
      "label": "数据采集",
      "category": "数据采集",
      "version": "1.0.0",
      "node_kind": "processor",
      "node_pack": "builtin",
      "inputs": [],
      "outputs": [
        {"name": "collected", "type": "CollectedData", "label": "采集数据"}
      ],
      "config_schema": {
        "platforms": {
          "type": "list",
          "label": "启用平台",
          "default": ["weibo", "douyin", "github", "huggingface"]
        }
      }
    }
  ],
  "node_packs": [],
  "global_config": {
    "models": ["deepseek-v4-flash", "gemma-local", "mimo-v2.5"]
  }
}
```

### WebSocket 运行时事件

```text
run_start     {run_id, mode}
node_start    {node_id, type}
node_progress {node_id, progress, message}
node_complete {node_id, duration_s}
node_error    {node_id, error}
node_cached   {node_id}
node_skipped  {node_id, reason}
log           {node_id, level, message, logger, timestamp}
run_end       {run_id, status, node_states, ...}
run_stopped   {run_id}
```

## 节点包安装与管理

当前分支的节点包管理入口是后端 API，不再使用旧 `vf plugins` 命令。

### 安装来源

```text
POST /api/node-packs/install
{
  "source": "https://github.com/you/my-vf-nodes.git"
}
```

也可以传本地路径或 pip 包名：

```text
POST /api/node-packs/install
{
  "source": "D:/workspace/my-vf-nodes"
}
```

### 管理接口

```text
GET    /api/node-packs
GET    /api/node-packs/updates
POST   /api/node-packs/install
POST   /api/node-packs/{name}/update
POST   /api/node-packs/{name}/enable
POST   /api/node-packs/{name}/disable
DELETE /api/node-packs/{name}
```

## 版本与迁移

- **节点包级版本**：`vf-node.yaml` 中的 `version`
- **节点级版本**：`@node(..., version="1.0.0")`
- **配置迁移入口**：`migrate_config(old_version, config)`

```python
@node("my_node", version="2.0.0")
class MyNode(BaseNode):
    @classmethod
    def migrate_config(cls, old_version: str, config: dict) -> dict:
        if old_version < "2.0.0" and "old_param" in config:
            config["new_param"] = config.pop("old_param")
        return config
```

## 目录结构

```text
videoFactory-node-opt/
├── server/
│   ├── api/
│   │   ├── nodes.py
│   │   ├── node_packs.py
│   │   └── runs.py
│   ├── engine/
│   │   └── executor.py
│   ├── nodes/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── loader.py
│   │   ├── pack_manager.py
│   │   ├── builtin/
│   │   └── community/
│   └── models.py
├── web/
│   └── src/
├── workflows/
└── docs/
```

## 最佳实践

### 1. 配置和连线分离

- 不要把前端配置项写进 `inputs`
- 不要依赖旧的“自动把 `config_schema` 转输入桩”思路

### 2. 只用 `ctx.logger`

```python
async def execute(self, ctx, on_progress):
    ctx.logger.info("开始处理")
    ctx.logger.debug(f"config={self.config}")
```

### 3. 长任务必须上报进度

```python
async def execute(self, ctx, on_progress):
    for i, item in enumerate(items):
        on_progress(f"处理第 {i + 1}/{len(items)} 项", i / len(items))
```

### 4. 在 `finalize` 里清理资源

```python
async def finalize(self, ctx, success):
    if self._client:
        await self._client.close()
```

### 5. 非幂等节点默认别缓存

- LLM 节点默认 `cacheable = False`
- 只有缓存语义足够明确时才打开缓存
- 需要精细命中条件时，优先覆写 `check_cache()`
