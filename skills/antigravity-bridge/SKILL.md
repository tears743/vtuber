---
name: "antigravity-bridge"
description: "通过 opencli 连接和操作 Antigravity IDE（读取聊天、发送消息、提取代码等）。Invoke when user asks to read/write Antigravity IDE chat, extract code from Antigravity, or bridge between Trae and Antigravity."
---

# Antigravity IDE Bridge

通过 `opencli antigravity *` 命令集，在 Trae 内连接和操作 Antigravity IDE 的聊天内容。

## 前置条件

### 1. Antigravity IDE 必须带 CDP 端口启动

Antigravity IDE 是 Electron 应用，opencli 通过 CDP (Chrome DevTools Protocol) 连接它的渲染进程。

启动命令（在非沙箱 PowerShell 中执行）：

```powershell
Start-Process -FilePath "D:\Users\Admin\AppData\Local\Programs\Antigravity IDE\Antigravity IDE.exe" -ArgumentList @("--remote-debugging-port=9234", "--remote-allow-origins=*")
```

**注意**：
- 不要用 `bin\antigravity-ide.cmd`，因为它设了 `ELECTRON_RUN_AS_NODE=1`，会以 CLI 模式启动，不会开 CDP 端口
- 直接用 `.exe` 启动
- 安装路径可能在 `C:\` 或 `D:\` 盘，检查 PATH 环境变量确认

### 2. 验证 CDP 端口

检查 `DevToolsActivePort` 文件：

```powershell
Get-Content "C:\Users\Admin\AppData\Roaming\Antigravity IDE\DevToolsActivePort"
```

如果输出包含端口号（如 `9234`）和 browser ID，说明 CDP 已就绪。

### 3. Sandbox 限制（重要）

Trae 的终端运行在 sandbox 中，有以下限制：
- **文件系统隔离**：看不到 `C:\Users\Admin\AppData\Local\Programs` 下的文件
- **网络隔离**：无法连接 `127.0.0.1:9234`，即使 Antigravity IDE 在运行
- **进程限制**：无法启动非 sandbox 可见路径的 exe

**解决方案**：
- 启动 Antigravity IDE：用户在非沙箱 PowerShell 中执行
- opencli 命令：如果 sandbox 连不上 CDP，需要用户在非沙箱环境执行，把结果存成文件放到 worktree 目录下，Trae 再读取

## 常用命令

| 命令 | 用途 | 示例 |
|------|------|------|
| `read` | 读取当前聊天内容 | `opencli antigravity read -f json` |
| `history` | 列出历史会话 | `opencli antigravity history -f json` |
| `send` | 发送消息给 AI | `opencli antigravity send "你的问题"` |
| `watch` | 实时监听新消息 | `opencli antigravity watch -f json` |
| `extract-code` | 提取代码块 | `opencli antigravity extract-code -f json` |
| `status` | 检查 CDP 连接状态 | `opencli antigravity status` |
| `model` | 读取/切换当前模型 | `opencli antigravity model` |

## 典型流程

### 读取 Antigravity 聊天内容

1. 确认 Antigravity IDE 带 `--remote-debugging-port=9234` 启动
2. 在 Trae 终端执行：
   ```powershell
   opencli antigravity read -f json
   ```
3. 如果 sandbox 连不上，在非沙箱 PowerShell 执行：
   ```powershell
   opencli antigravity read -f json | Out-File -Encoding utf8 d:\workspace\videoFactory-node-opt\antigravity_chat.json
   ```
4. Trae 读取该文件

### 从 Antigravity 提取代码

```powershell
opencli antigravity extract-code -f json
```

### 查找 Antigravity 安装路径

如果安装路径不确定，检查以下位置：
```powershell
# 检查 PATH
$env:PATH -split ";" | Where-Object { $_ -match "ntigravity" }

# 检查常见安装位置
Get-ChildItem "C:\Users\Admin\AppData\Local\Programs" -Filter "*ntigravity*"
Get-ChildItem "D:\Users\Admin\AppData\Local\Programs" -Filter "*ntigravity*"

# 检查运行时数据目录
Get-ChildItem "C:\Users\Admin\AppData\Roaming" -Filter "*ntigravity*"
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `not reachable on CDP port 9234` | IDE 没带调试端口启动 | 用 `--remote-debugging-port=9234` 重启 |
| `CDP not reachable at http://127.0.0.1:9234` | sandbox 网络隔离 | 在非沙箱环境执行 opencli |
| `Test-Path` 返回 False 但进程在跑 | sandbox 文件系统隔离 | 用 PATH 环境变量或 `AppData\Roaming` 下的文件确认路径 |
| `.cmd` 启动后端口不通 | `.cmd` 设了 `ELECTRON_RUN_AS_NODE=1` | 直接用 `.exe` 启动 |
| `DevToolsActivePort` 显示端口但连不上 | 旧进程残留或 sandbox 隔离 | 确认进程在跑，在非沙箱环境执行 opencli |
