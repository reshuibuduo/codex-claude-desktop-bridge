## Windows 系统托盘版 + 更明确的使用场景

解决 Codex 符合条件的任务故障后，切换到 Claude 时重复说明目标、进度和项目目录的问题。先绑定并建立 Claude Desktop Code 待命，再自动交接新发生的可接续故障。

### 下载安装，不用自己编译
- **Windows x64**：下载 `Windows-x64-Setup.exe` 按用户安装；或完整解压 `Windows-x64-Portable.zip` 后运行 `CodexClaudeBridge.exe`。使用系统托盘；支持复制待命提示。
- **macOS Apple Silicon**：下载 `macOS-arm64.dmg`。
- **macOS Intel**：下载 `macOS-x86_64.dmg`。
- 全部内置 Python 3.12.15；不要求额外 Python、Homebrew 或 Claude CLI 登录。

**自动交接约定：**首次绑定并显示“等待故障”后，符合条件的最终故障会自动交出上下文，Claude 自动接续；故障发生后无需点击转接、复制对话或再发送任务提示。复制待命提示仅用于首次连接/恢复待命。

### 更新
- Windows 本机命名管道适配、同用户/同会话服务器校验、超时与分帧处理。
- 跨平台进程锁、配置目录和 UTF-8 项目路径。
- README 新增“解决什么问题”、使用边界、双平台下载与安装说明。
- 所有构建通过后才发布，附 SHA256SUMS 和平台验证 JSON。

### 证据边界
- Windows CI 验证：原生命名管道 fixture、跨进程锁、MCP、内置运行时、托盘启动、迁移运行、安装/卸载；**Windows 真实 Codex → Claude 桌面故障接续尚待现场验收**。
- 既有 macOS 现场实验是一次受控 HTTP 400 故障交接，不是实际过载 429。
- Windows x64 目标为 Windows 10 22H2/11，CI 主机为 Windows Server 2025；未验收 ARM64、WSL 和远端会话。
- Windows 未 Authenticode 签名；macOS 仅 ad-hoc 签名、未公证。首次启动可能遇到系统提示，核对来源与 SHA256 后遵循系统逐应用确认流程。
- 移动/升级前先暂停并核对正在执行的接续；升级后重新保存绑定并重开 Claude 待命。退出暂停新交接，不终止 Claude 已在执行的工作。

[完整 README](https://github.com/reshuibuduo/codex-claude-desktop-bridge#readme) · [Windows 安装说明](https://github.com/reshuibuduo/codex-claude-desktop-bridge/blob/main/docs/INSTALL-WINDOWS.txt)
