# VideoFactory Node Runtime 文档

## 文档目的

这份文档记录 `feature/node-opt-v2` 分支已经落地的 node runtime 设计、当前实现状态、验证结论与已知限制。

它不是规划稿，而是当前分支的实现说明。

## 当前目标

本分支的核心目标是把原来的串行、硬编码节点系统，升级为一套可扩展、可分发、可前后端协同的 node runtime：

- 画布连线决定真实执行顺序
- 节点定义统一由后端下发给前端
- 支持 Processor / Trigger / Listener 三类节点
- 支持 node pack 安装、启停、版本检测和更新
- 支持工作流运行日志、状态和停止控制

## 已实现能力

### 1. 统一节点基类

当前 `server/nodes/base.py` 已提供统一基类与元数据声明：

- `BaseNode`
- `TriggerNode`
- `ListenerNode`
- `NodeInput`
- `NodeOutput`

节点元数据包含：

- `type`
- `label`
- `category`
- `description`
- `version`
- `author`
- `icon`
- `color`
- `node_pack`
- `node_kind`

### 2. 配置与连线分离

当前实现已明确分离：

- `config_schema`：右侧属性面板的配置字段
- `inputs` / `outputs`：画布上的连线桩

这解决了旧体系里“前端配置项被误当作连线输入”的问题。

### 3. PipelineContext 仓库模式

`server/models.py` 中的 `PipelineContext` 已切换为产出仓库模式：

- `ctx.data`：按 `{node_id}:{output_name}` 存储所有产出
- `ctx.write()` / `ctx.read()`：节点间显式读写
- `ctx.find_by_type()` / `ctx.find_latest_by_type()`：按类型查找上游产出
- `ctx.emit()` / `ctx.on()`：消息总线
- `ctx.logger`：按运行隔离的独立 logger

同时保留了旧字段兼容层：

- `ctx.collected`
- `ctx.media`
- `ctx.scripts`
- `ctx.audio`
- `ctx.aligned`
- `ctx.overlay`
- `ctx.visual`
- `ctx.live2d`
- `ctx.final`

### 4. 执行引擎

`server/engine/executor.py` 当前支持：

- 基于 `edges` 的拓扑排序
- 同层 `asyncio.gather` 并发执行
- 节点级生命周期调度
- `abort / skip / retry`
- `resume_from_node`
- `dry_run`
- WebSocket 状态推送
- WebSocket 日志推送
- 停止执行时终止子进程

### 5. 三种工作流模式

当前工作流 `mode` 支持：

#### `manual`

一次性执行 DAG，适合普通视频生产工作流。

#### `scheduled`

启动 Trigger 节点长驻监听，到点后只执行下游 Processor 子图。

#### `listener`

启动 Listener 节点长驻监听，收到事件后执行下游 Processor 子图，必要时回写回复。

### 6. 节点包体系

当前分支已经具备 node pack 的基础设施：

- `server/nodes/loader.py`
- `server/nodes/pack_manager.py`
- `server/api/node_packs.py`

支持来源：

- 本地目录
- Git URL
- pip entry point

支持操作：

- 安装
- 列表
- 启用
- 禁用
- 更新
- 删除
- 检查可用更新

### 7. 内置特殊节点

当前已增加以下内置 Trigger / Listener 节点：

- `cron_trigger`
- `wechat_channel`
- `feishu_channel`
- `dingtalk_channel`

### 8. 前端协同

当前前端已与后端节点定义接口对齐，核心点包括：

- 从 `/api/nodes` 获取节点定义
- 使用 `ReactFlowProvider` 解决拖拽坐标和上下文问题
- `screenToFlowPosition` 修复节点放置坐标漂移
- 前端 API 地址改为从当前页面动态推导
- WebSocket 地址改为从当前页面动态推导

### 9. 运行时修复

在本分支验证过程中，已经修复过一批运行时问题：

- 服务启动时端口占用检测
- worktree 下 `config.yaml` 缺失时回退到主仓库配置
- `data_root` 相对路径在 worktree 中无法解析的问题
- Web 端日志丢失
- 停止执行时下载类子进程未退出
- 默认工作流画布空白
- 节点拖拽后位置错误
- 新建工作流弹窗体验过于粗糙

## 当前 API 约定

### `GET /api/nodes`

返回：

- `nodes`
- `node_packs`
- `global_config.models`

其中 `global_config.models` 用于前端的 `type: "model"` 下拉选择。

### `GET /api/node-packs`

返回当前所有 node pack 的基本信息、版本、来源和启用状态。

### `POST /api/run`

启动工作流执行，支持：

- `workflow_id`
- `date`
- `force_no_cache`

### `POST /api/run/stop`

请求停止当前运行，并由执行器尝试终止相关子进程。

### `WS /ws/run`

推送运行状态、节点进度和日志。

## 缓存语义

### 基础规则

- 默认节点不缓存：`cacheable = False`
- 开启缓存的节点需要明确自己的命中语义
- 对于简单节点，可以依赖基类的 `output_dirs` 或 `fingerprint()`
- 对于复杂节点，允许覆写 `check_cache()`

### `collect` 节点的当前语义

`collect` 节点已经补上缓存能力，但不是简单的“目录里有文件就命中”。

当前规则是：

- 先看当前运行日期 `ctx.date`
- 再看当前节点配置中的 `platforms`
- 只有该日期下、所选站点都已经产生过对应采集文件，才命中缓存

例子：

- `platforms = ["weibo", "github"]`
- 若 `data/<date>/collected/` 下同时存在 `YYYY-MM-DD_weibo_*.json` 与 `YYYY-MM-DD_github_*.json`
- 则本次 `collect` 直接走缓存恢复

否则继续执行采集。

## 已知限制

以下能力已经有实现基础，但仍需继续验证或完善：

### 1. 停止行为仍需持续实测

虽然执行器已经增加对子进程的终止逻辑，但下载链路里仍可能存在更深层的阻塞线程或外部子进程，需要更多长任务场景验证。

### 2. Listener / Channel 节点需要真实接入验证

`wechat_channel`、`feishu_channel`、`dingtalk_channel` 已有运行时骨架，但是否完全符合各平台当前 SDK / 长连接行为，还需要接真实机器人配置持续实测。

### 3. Web 日志恢复已修，但要继续验证完整链路

后端已补回 WebSocket 日志推送，仍建议在长链路工作流上确认：

- 节点日志是否全部可见
- `agents.*` 日志是否全部被正确转发
- 停止执行后日志任务是否正确清理

### 4. `run_server.py` 的开发态行为需要进一步收口

当前服务启动验证依赖 `reload=False` 的方式更稳定；开发态 `reload=True` 在当前终端环境里可能带来额外进程退出或重载干扰。

## 建议验证清单

后续继续验收时，建议按下面顺序检查：

1. 服务启动是否正确选择空闲端口
2. 前端访问是否正常加载当前 worktree 的 `web/dist`
3. `/api/nodes` 返回的节点定义是否与画布渲染一致
4. 默认工作流是否正常显示、拖拽、保存
5. `collect` 节点在已有当日站点数据时是否命中缓存
6. Web 日志是否持续显示
7. 停止执行时下载与渲染子进程是否退出

## 相关文件

核心实现主要集中在以下文件：

- `server/nodes/base.py`
- `server/models.py`
- `server/nodes/registry.py`
- `server/nodes/loader.py`
- `server/nodes/pack_manager.py`
- `server/engine/executor.py`
- `server/api/nodes.py`
- `server/api/node_packs.py`
- `server/api/runs.py`
- `server/nodes/collect.py`
- `agents/collector/orchestrator.py`
- `web/src/pages/WorkflowEditor.jsx`
- `web/src/pages/WorkflowList.jsx`
- `web/src/api.js`

## 与其他文档的关系

- `docs/CUSTOM_NODES.md`：面向 node 开发者，讲怎么写节点
- `docs/NODE_SYSTEM_RUNTIME.md`：面向当前分支维护者，讲系统已经实现到哪一步
- `docs/pipeline.md`：面向传统脚本管线的使用者
- `docs/codebase.md`：面向全项目整体结构说明
