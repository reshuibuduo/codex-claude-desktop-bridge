## macOS 安装包 / Installers

**无需自己编译，也不用安装 Python、Homebrew 或 Xcode。** Python 3.12.15 已内置。

| 你的 Mac | 下载文件 |
|---|---|
| Apple Silicon / M 系列 | `Codex-Claude-Bridge-0.3.0-macOS-arm64.dmg` |
| Intel | `Codex-Claude-Bridge-0.3.0-macOS-x86_64.dmg` |

1. 下载对应的 **DMG**（不是 GitHub 自动生成的 Source code 压缩包）。
2. 打开 DMG，将 **Codex Claude Bridge.app** 拖入 **Applications**，推出磁盘镜像。
3. 从“应用程序”启动，绑定一个本机 Codex 对话及项目目录。
4. 打开 Claude Desktop Code 待命，在 Environment 中确认同一实际目录，完成 MCP 授权并发送待命提示。

### 首次打开与签名状态

**此预览版采用 ad-hoc 签名，尚未 Apple Developer ID 签名或公证。** Gatekeeper 可能阻止首次打开。确认来源与校验和后，可按照 [Apple 的单应用打开说明](https://support.apple.com/en-us/102445) 在“系统设置 → 隐私与安全性”中确认打开。管理设备可能不允许此操作。不要全局关闭 Gatekeeper。

This preview is **ad-hoc signed, not Developer ID signed or notarized**. macOS may block first launch; follow Apple's per-app confirmation flow only if you trust the download. No compiler, separately installed Python, or Homebrew is required.

### Requirements and validation

- App deployment target: **macOS 13+**. Each architecture is built and package-smoke-tested on a native **macOS 15** GitHub runner. Other OS versions still require installation testing; vendor desktop apps may impose newer requirements.
- Running Codex Desktop and authenticated Claude Desktop **Code** are required for handoff. A plain Claude Chat session is not enough.
- Both DMGs are mounted, copied to a different path containing spaces, and exercised with a temporary HOME and a PATH containing no Python/compiler.
- Tests cover bundled Python, native menu states, window/menu startup, real stdio MCP initialize/list/ping, connector install/restore, missing-runtime failure, and code-signature integrity after execution. No live model requests are made by release CI.
- `SHA256SUMS` and per-architecture `validation-*.json` are attached. The JSON records the exact source commit, embedded runtime, asset hash, and executed checks.
- The previously reported controlled HTTP 400 failover remains a separate experiment; this packaging release does not claim real overload/429 or overnight standby acceptance.

### Upgrade / uninstall

Pause and finish active work, quit the old app, replace it in Applications, then **save the binding again and reopen the Claude standby session** so its MCP command uses the embedded runtime. The update does not delete user config. See the [README](https://github.com/reshuibuduo/codex-claude-desktop-bridge#readme) for configuration, known limits and reversible MCP uninstall.

### Changes

- Embedded, relocatable CPython runtime for Apple Silicon and Intel, pinned to upstream SHA256 digests.
- Native helper and project MCP use the bundled interpreter, not `/usr/bin/python3`; isolated interpreter flags ignore user Python environment overrides.
- Drag-to-Applications DMGs, third-party license notices, checksums and clean-runner validation.
- Reproducible manual release workflow; an existing release is never overwritten automatically.
