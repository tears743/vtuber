# VideoFactory 自定义节点开发规范

VideoFactory 节点体系采用插件化架构，节点可以来自：
1. **内置节点** — 随主项目分发，位于 `server/nodes/builtin/`
2. **本地插件** — 放置在 `plugins/` 目录的独立包
3. **Git 安装** — 通过 `vf plugins install <git-url>` 从 Git 仓库安装
4. **pip 包** — 任何符合入口点规范的 Python 包

## 快速开始

### 创建一个最小节点

```python
# plugins/my_plugin/nodes/hello.py
from server.nodes.base import BaseNode, NodeInput, NodeOutput
from server.nodes.registry import node

@node("hello_world", version="1.0.0", author="you", icon="👋")
class HelloNode(BaseNode):
    """向世界问好的示例节点"""

    # ── 节点元信息 ──
    label = "Hello World"
    category = "示例"
    description = "一个最简单的节点，输出问候语"

    # ── 输入输出声明（前端据此渲染连线桩）──
    inputs = [
        NodeInput(name="name", type="string", label="名字",
                  default="World", description="要问候的名字"),
    ]
    outputs = [
        NodeOutput(name="greeting", type="string", label="问候语"),
    ]

    # ── 生命周期钩子 ──
    async def prepare(self, ctx):
        """执行前准备资源（可选）"""
        ctx.logger.info("准备问好...")

    async def execute(self, ctx, on_progress) -> dict:
        """核心逻辑，返回输出字典"""
        name = self.get_input("name")
        on_progress("正在生成问候...", 0.5)
        greeting = f"Hello, {name}!"
        on_progress("完成", 1.0)
        return {"greeting": greeting}

    async def finalize(self, ctx, success: bool):
        """执行后清理（无论成功失败都调用）"""
        pass
```

### 插件清单文件

每个插件包根目录必须有 `vf-plugin.yaml`：

```yaml
# plugins/my_plugin/vf-plugin.yaml
name: my_plugin
version: 1.0.0
author: Your Name <you@example.com>
description: 我的自定义节点包
homepage: https://github.com/you/my-vf-plugin
license: MIT

# 节点入口（可多个）
nodes:
  - path: nodes/hello.py        # 相对路径
  - path: nodes/goodbye.py

# 依赖声明（可选）
dependencies:
  python:
    - requests>=2.28
  system:
    - ffmpeg

# 前端扩展（可选）
web:
  entry: web/index.js           # 前端 JS 扩展入口
```

## 节点生命周期

节点执行遵循严格的生命周期顺序：

```
prepare(ctx)
    │  资源初始化（连接服务、加载模型、创建临时目录）
    │  失败 → 跳过 execute，直接进入 finalize
    ▼
validate(ctx)
    │  检查上游数据是否就绪
    │  失败 → 跳过 execute（状态 SKIPPED），进入 finalize
    ▼
check_cache(ctx)
    │  检查产出缓存
    │  命中 → restore_cache(ctx)，跳过 execute，进入 finalize
    ▼
execute(ctx, on_progress)
    │  核心逻辑，通过 on_progress 上报进度
    │  返回 dict 作为 outputs
    │  失败 → on_error(ctx, error)，进入 finalize
    ▼
finalize(ctx, success)
    │  清理资源（关闭连接、删除临时文件、释放 GPU）
    │  无论成功失败都调用
    ▼
[完成]
```

### 生命周期钩子说明

| 钩子 | 必需 | 调用时机 | 用途 |
|------|------|---------|------|
| `prepare(ctx)` | 否 | execute 前 | 初始化资源、健康检查、启动外部服务 |
| `validate(ctx)` | 否 | prepare 后 | 校验上游数据，返回错误列表 |
| `check_cache(ctx)` | 否 | validate 后 | 自定义缓存命中逻辑 |
| `restore_cache(ctx)` | 否 | 缓存命中时 | 从磁盘恢复产出 |
| `execute(ctx, on_progress)` | **是** | 核心执行 | 业务逻辑，返回 outputs dict |
| `on_error(ctx, error)` | 否 | execute 抛异常时 | 错误处理、回滚 |
| `finalize(ctx, success)` | 否 | 最后调用 | 资源清理 |

## 输入输出声明

### NodeInput

```python
NodeInput(
    name="model_name",          # 唯一标识（snake_case）
    type="string",              # 类型：string/int/float/bool/list/dict/model/file/path
    label="模型名称",            # 前端显示名
    default="deepseek-v4-flash",# 默认值
    required=True,              # 是否必填
    description="要使用的LLM模型", # 描述文本
    options=None,               # 枚举选项列表 ["a", "b", "c"]
    min=None,                   # 数值最小值
    max=None,                   # 数值最大值
    step=None,                  # 数值步长
    hidden=False,               # 是否隐藏（不在UI显示，仅内部传递）
    group="basic",              # 参数分组（前端折叠面板）
)
```

### NodeOutput

```python
NodeOutput(
    name="scripts",             # 唯一标识
    type="ScriptsData",         # 类型名（用于连线类型检查）
    label="脚本",               # 前端显示名
    description="生成的视频脚本",
)
```

### 类型系统

连线时前端会检查输出类型与输入类型是否兼容：

| 类型 | 说明 | 示例 |
|------|------|------|
| `string` | 字符串 | 模型名、提示词 |
| `int` / `float` | 数值 | 并发数、温度 |
| `bool` | 布尔 | 开关选项 |
| `list` / `dict` | 集合 | 话题列表、配置 |
| `model` | 模型选择 | deepseek-v4-flash |
| `file` / `path` | 文件路径 | 背景图、参考音频 |
| `CollectedData` | 采集产出 | 管线内置类型 |
| `MediaData` | 媒体产出 | 管线内置类型 |
| `ScriptsData` | 脚本产出 | 管线内置类型 |
| 自定义类型 | 插件定义 | 任何 dataclass 名 |

类型兼容规则：
- 完全匹配：`string` ↔ `string`
- 子类型：`int` 可连接到 `float`
- 通配：`any` 接受任何类型
- 插件可注册自定义类型及其继承关系

## 数据传递

节点间通过 `PipelineContext` 传递数据。每个节点通过 `inputs` 声明从上游读取什么，通过 `execute` 返回值声明写入什么：

```python
@node("my_node")
class MyNode(BaseNode):
    inputs = [
        NodeInput(name="collected", type="CollectedData",
                  label="采集数据", connected=True),  # connected=True 表示来自上游节点
    ]
    outputs = [
        NodeOutput(name="result", type="MyResult", label="结果"),
    ]

    async def execute(self, ctx, on_progress) -> dict:
        # 从 ctx 读取上游产出
        collected = self.get_input("collected")  # 自动从 ctx 解析

        # 也可以直接访问 ctx.data
        all_upstream = ctx.data  # {"upstream_node_id:output_name": value}

        # 返回产出
        return {"result": my_result}
```

## 前后端通信协议

### 节点定义 API

`GET /api/nodes` 返回所有已注册节点的完整定义：

```json
{
  "nodes": [
    {
      "type": "hello_world",
      "label": "Hello World",
      "category": "示例",
      "description": "一个最简单的节点",
      "version": "1.0.0",
      "author": "you",
      "icon": "👋",
      "color": "#4CAF50",
      "inputs": [
        {
          "name": "name",
          "type": "string",
          "label": "名字",
          "default": "World",
          "required": true,
          "description": "要问候的名字",
          "group": "basic",
          "connected": false
        }
      ],
      "outputs": [
        {
          "name": "greeting",
          "type": "string",
          "label": "问候语",
          "description": ""
        }
      ],
      "config_schema": {},
      "deprecated": false,
      "plugin": "my_plugin"
    }
  ],
  "plugins": [
    {
      "name": "my_plugin",
      "version": "1.0.0",
      "author": "you",
      "description": "我的自定义节点包"
    }
  ]
}
```

### 运行时事件 (WebSocket)

```
run_start     {run_id, workflow_id}
node_start    {node_id, type}
node_progress {node_id, progress, message}
node_complete {node_id, duration_s, outputs_summary}
node_error    {node_id, error}
node_cached   {node_id}
node_skipped  {node_id, reason}
log           {node_id, level, message, timestamp}
run_end       {run_id, status, ...}
run_stopped   {run_id}
```

## 插件安装

### 从本地目录安装

```bash
# 软链接本地开发中的插件
vf plugins link /path/to/my_plugin
```

### 从 Git 安装

```bash
# 安装到 plugins/ 目录
vf plugins install https://github.com/you/my-vf-plugin.git

# 安装指定分支/tag
vf plugins install https://github.com/you/my-vf-plugin.git@v1.2.0
```

### 从 pip 安装

```bash
# 任何符合 vf-node 插件入口点的包
pip install vf-plugin-awesome
vf plugins enable vf-plugin-awesome
```

### 管理插件

```bash
vf plugins list              # 列出已安装插件
vf plugins disable my_plugin # 禁用
vf plugins enable my_plugin  # 启用
vf plugins update my_plugin  # 更新（git pull）
vf plugins remove my_plugin  # 卸载
```

## 目录结构

```
videoFactory/
├── plugins/                     # 用户安装的插件目录
│   ├── my_plugin/
│   │   ├── vf-plugin.yaml       # 插件清单
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   └── hello.py
│   │   ├── web/                 # 前端扩展（可选）
│   │   │   └── index.js
│   │   └── README.md
│   └── another_plugin/
│       └── ...
├── server/
│   ├── nodes/
│   │   ├── builtin/             # 内置节点（从原 nodes/ 迁移）
│   │   │   ├── collect.py
│   │   │   ├── download.py
│   │   │   └── ...
│   │   ├── base.py              # BaseNode + NodeInput + NodeOutput
│   │   ├── registry.py          # @node 装饰器 + 自动发现
│   │   ├── loader.py            # 插件加载器
│   │   └── types.py             # 类型系统注册表
│   └── engine/
│       └── executor.py          # 执行引擎（支持 edges + 并发）
└── ...
```

## 最佳实践

### 1. 幂等性
`execute` 应该是幂等的——相同输入产生相同输出，不依赖外部状态。

### 2. 进度上报
长任务必须调用 `on_progress(message, progress)` 上报进度，让前端能看到实时状态：

```python
async def execute(self, ctx, on_progress):
    items = self.get_input("items")
    for i, item in enumerate(items):
        on_progress(f"处理第 {i+1}/{len(items)} 项", i / len(items))
        await process(item)
    on_progress("完成", 1.0)
```

### 3. 资源清理
所有在 `prepare` 中获取的资源必须在 `finalize` 中释放：

```python
async def prepare(self, ctx):
    self._tmpdir = tempfile.mkdtemp()
    self._client = SomeClient()

async def finalize(self, ctx, success):
    await self._client.close()
    shutil.rmtree(self._tmpdir, ignore_errors=True)
```

### 4. 缓存友好
缓存基于 `node_type + config + upstream_outputs_hash` 自动计算。如果节点产出不依赖外部副作用（时间、随机数），缓存会自动生效。否则重写 `check_cache` 返回 `False`。

### 5. 错误处理
`execute` 抛异常会被引擎捕获并标记节点失败。对于可恢复错误，在 `on_error` 中处理；对于不可恢复错误，直接抛出。

### 6. 日志
使用 `ctx.logger` 而非 `print` 或全局 `logging`，确保日志隔离到当前运行：

```python
async def execute(self, ctx, on_progress):
    ctx.logger.info("开始处理")
    ctx.logger.debug(f"输入参数: {self.config}")
```
