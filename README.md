# Codex → Claude Desktop Bridge

[![CI](https://github.com/reshuibuduo/codex-claude-desktop-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/reshuibuduo/codex-claude-desktop-bridge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Codex 任务失败后，把任务交给已登录的 Claude 桌面 Code 接着做。支持 macOS 菜单栏和 Windows 系统托盘。**

## 解决什么问题？

你在 Codex 里推进一个项目，遇到模型繁忙、服务过载或符合条件的最终失败时，任务会中断。手动切到 Claude 往往需要：

1. 重新说明“要做什么、已经做了什么、哪里失败了”；
2. 找回正确项目目录，核对文件现状和用户已有修改；
3. 等待、复制上下文、反复确认有没有重复执行。

这个软件把**故障发现 → 有条件的任务交接 → 在同一项目接续**连起来。你先绑定一个本机 Codex 对话、在 Claude Desktop Code 建立待命会话；之后发生新的、可接续的最终故障时，软件通过项目级 MCP 交出最新用户目标和有限可见上下文，Claude 再读磁盘、继续工作并报告结果。复用桌面登录，不要求单独登录 Claude CLI。

**适合：**已经同时使用 Codex 和 Claude Desktop Code、希望减少服务故障导致的手工切换与上下文重述的人。

**它不解决：**让繁忙模型恢复、共享两家订阅额度、迁移模型隐藏状态、保证任意失败都能成功续做。首次绑定/待命/正常工具授权仍需完成；历史失败、普通成功、尚在重试或等待审批的任务不会触发转接。它不是厂商官方集成，使用版本化的私有 Codex IPC；版本变化会停止接续而非盲目执行。

> **验证边界：**macOS 已做过一次真实受控故障接续实验，但不是实际过载 outage。Windows 预览版验证安装/卸载、托盘启动、内置运行时和原生命名管道 fixture；Windows 上真实 Codex → Claude 桌面接续尚待现场验收。详见 [验证记录](docs/VALIDATION.md)。

## How it works

```text
Codex Desktop: selected local thread
    │ fresh owner snapshot, terminal failed turn
    ▼
Local bridge: classify → recheck → deduplicate → persist handoff
    │ MCP await_codex_failure result
    ▼
Claude Desktop Code: read files → continue user goal → report actual results
    │ status files
    ▼
Native menu bar: waiting / handed off / reported complete / paused
```

- Typed terminal service errors only; ordinary success, retries, historical failures and pending approvals do not trigger a handoff.
- Same-runtime owner checks, SQLite deduplication, a bridge-local workspace lease, persistent re-arm cursor and request-scoped cancellation.
- Context contains the latest user goal and bounded visible history. Hidden prompts, reasoning and credentials are not exported.
- No global Codex/Claude settings or installed vendor app binaries are patched.
- Python standard library + native AppKit/Swift (macOS) or WinForms/C# (Windows). No npm dependency, background launch agent or automatic startup registration.

## Download and install / 下载安装

**[下载 v0.4.0 安装包](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/tag/v0.4.0)** — 已内置 Python，使用者无需编译或安装开发环境。

| 系统 | 下载 | 安装方式 |
|---|---|---|
| Windows 10 22H2 / 11，x64 | [Setup.exe](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/download/v0.4.0/Codex-Claude-Bridge-0.4.0-Windows-x64-Setup.exe) | 按用户安装，从开始菜单打开；常驻系统托盘 |
| Windows x64，便携版 | [Portable.zip](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/download/v0.4.0/Codex-Claude-Bridge-0.4.0-Windows-x64-Portable.zip) | 完整解压到固定目录，双击 `CodexClaudeBridge.exe`；保留 Resources |
| macOS，Apple Silicon M 系列 | [arm64.dmg](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/download/v0.4.0/Codex-Claude-Bridge-0.4.0-macOS-arm64.dmg) | 拖入 Applications，推出镜像，再打开 App |
| macOS，Intel | [x86_64.dmg](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/download/v0.4.0/Codex-Claude-Bridge-0.4.0-macOS-x86_64.dmg) | 同上 |

**预览版签名状态：**Windows 尚未 Authenticode 签名；macOS 为 ad-hoc 签名、未 Developer ID 公证。系统可能提示未知发布者或拦截首次启动。请核对 Release 来源及 [SHA256SUMS](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/download/v0.4.0/SHA256SUMS)，遵循组织应用策略，不关闭全局防护。macOS 可参阅 [Apple 的逐应用确认说明](https://support.apple.com/en-us/102445)。[macOS 安装说明](docs/INSTALL.txt) · [Windows 安装说明](docs/INSTALL-WINDOWS.txt)。

CI 在两个原生 macOS 架构及 Windows Server 2025 x64 上构建/测试。Windows 安装包声明最低 Windows 10 22H2；尚不等于 Windows 10/11 上的厂商桌面接续验收。Windows ARM64、WSL 和远端会话未验收。

## Requirements

- macOS 13+，或 Windows 10 22H2 / Windows 11 x64（厂商桌面应用可能要求更新系统）。内置 Python 3.12.15；Windows 使用系统 .NET Framework。
- **仅源码构建：**Python 3.9+；macOS 需要 Xcode Command Line Tools，Windows 需要 .NET Framework C# 编译器与 Inno Setup 6；需要联网下载哈希锁定的运行时。
- Running Codex Desktop and an authenticated Claude Desktop **Code** session.
- Initial live validation: Apple Silicon, Codex Desktop `26.1007.30912`, Claude Desktop `2.37337.1`, embedded Claude Code `2.1.295`.
- Other desktop versions need adapter validation. The observed Codex stream version is `11`; unknown versions stop the adapter.

## Build from source (optional)

```sh
git clone https://github.com/reshuibuduo/codex-claude-desktop-bridge.git
cd codex-claude-desktop-bridge
./menu/build.sh
```

Open `dist/Codex Claude Bridge.app` in Finder. The build is locally ad-hoc signed, not notarized. If your Swift compiler and default SDK do not match, select a compatible installed SDK:

```sh
SDKROOT=/path/to/compatible/MacOSX.sdk ./menu/build.sh
```

Windows 源码构建（PowerShell）：

```powershell
python scripts/package_windows.py
```

## Connect after installation

1. Enter **one local Codex conversation UUID** and its actual project directory; save the binding. The bridge confirms that the live Codex thread belongs to that directory.
2. Click **打开 Claude 待命**. In Claude's **Environment** panel, explicitly confirm the real working directory, then send the prefilled prompt. Windows 若深链接未进入正确会话，在 Claude Code 手动打开同一目录，使用托盘面板的 **复制待命提示**。 A folder chip in the composer alone is not proof of the session's working directory.
3. Use Claude's normal MCP permission flow. The menu must show **等待故障 · Claude 桌面已待命** before failover is armed.
4. Keep that standby session open. When a new eligible terminal failure arrives, Claude receives the handoff and continues automatically.
5. **暂停** stops new handoffs, not a Claude task already executing. Normal menu exit also pauses the binding.

本地配置和运行记录：macOS 位于 `~/Library/Application Support/CodexClaudeBridge/`；Windows 位于 `%LOCALAPPDATA%\CodexClaudeBridge`。 `CODEX_CLAUDE_BRIDGE_DATA` can override this directory for local testing. Project `.mcp.json` edits preserve other connectors and have installation manifests/backups. macOS 保持 App 在 Applications；Windows 保持安装目录或便携版目录固定。 After moving or upgrading it, pause/finish active work first, then save the binding again and reopen the Claude standby session. The MCP entry records the embedded interpreter path.

Windows 关闭窗口仅收起到系统托盘，使用 **退出并暂停** 才结束软件。卸载前先暂停，并用下文安装 manifest 还原项目 MCP；卸载程序删除安装文件、暂停默认绑定，但保留配置和项目文件。

For an existing, correctly bound Claude session, use [the reusable standby prompt](docs/STANDBY_PROMPT.txt).

## Validate locally (no model requests)

```sh
python3 bridge_core.py --self-test
python3 -m unittest discover -s tests -v
python3 scripts/check_public_tree.py
```

核心含 70 项断言；回归测试包括合成 IPC 状态、跨进程锁、中文路径与本地进程 fixture。macOS 构建运行 8 项菜单状态检查，Windows 运行 10 项托盘/参数检查及原生 Win32 命名管道测试。 These tests are **not** live model acceptance.

A local live experiment did establish this narrower chain:

| Stage | Observed result |
|---|---|
| Codex source | A controlled invalid-model request really failed with HTTP 400 |
| Claude target | An authenticated desktop Code session automatically received the MCP handoff |
| Work | Claude repaired a toy `clamp` function without another task prompt after the failure |
| Independent verification | Existing 6 tests changed from 4 failures to 6 passes; test-file hash unchanged |
| Packaged menu | Real standby and pause were observed |

This was **not an actual overload outage**. A thread/model/nonce-bound acceptance override allowed that one non-transient test error. Normal bindings omit it. Private transcripts, machine paths, conversation IDs and original runtime logs are not included in this public repository. See [the evidence boundaries](docs/VALIDATION.md).

## Important limitations

- One local Codex thread per binding. Remote/cloud tasks, live overload/429, overnight standby, sleep/wake and desktop upgrades still need live acceptance.
- The bridge checks source quiescence before delivery and again at completion. **Its SQLite lease is not a Codex filesystem lock.** Do not retry the source while Claude is modifying the same project. Isolated worktree + reviewed merge is future work.
- Unknown/uncertain deliveries are not automatically replayed after a restart. Inspect the target session/files, pause, then explicitly reconcile the record.
- `COMPLETED_REPORTED` is the target agent's report, not independent verification. Only the fixed acceptance verifier independently runs its toy test suite.
- The Claude deep link can show a project label while starting in a scratch directory. The real directory check is essential; the MCP process also rejects a mismatched startup directory.
- Existing Claude model/tool permissions still apply; this app does not suppress approvals.

## CLI administration

The default config matches the menu app; use `--config /absolute/config.json` before the subcommand to override it.

```sh
python3 bridge/desktop_setup.py status
python3 bridge/desktop_setup.py pause
python3 bridge/desktop_setup.py prompt

# Only after inspecting the actual target session and files:
python3 bridge/desktop_setup.py resolve \
  --handoff-id HANDOFF_ID --outcome completed \
  --note 'Describe the inspected changes and actual test results'

# Revert this installation's MCP entry, preserving other connectors:
python3 bridge/desktop_setup.py uninstall --manifest /absolute/mcp-install-record.json
```

Use `--outcome abandoned` when the inspected handoff should not be resumed. Reconciliation is recorded as a user decision, not as a successful test run. For multiple installation records, inspect and restore them from newest to oldest.

## Project structure

```text
bridge_core.py                classification, context package, dedup/lease
bridge/desktop_ipc.py         private Codex Desktop stream adapter
bridge/desktop_mcp.py         Claude Desktop project MCP server
bridge/desktop_setup.py       binding, pause, backup, reconciliation
bridge/live_service.py        earlier CLI experiment + shared helpers (not the app's target)
menu/MenuApp.swift            native status item and control panel
menu/build.sh                standalone app build with pinned embedded Python
windows/TrayApp.cs           native Windows tray and control panel
windows/installer.iss        per-user Windows installer/uninstaller
bridge/windows_pipe.py      bounded Win32 named-pipe transport
bridge/platform_support.py  cross-process locking and data paths
scripts/package_windows.py  installer/portable build and native smoke tests
scripts/package_release.py  DMG creation and relocated-bundle smoke tests
.github/workflows/release.yml macOS + Windows build, verification and preview publication
scripts/check_public_tree.py publication hygiene check (not a universal secret scanner)
tests/                       offline regression tests
docs/                        standby prompt and validation boundaries
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Keep changes small and testable. Do not upload conversation exports, live bindings, credentials, extracted vendor source or machine-specific evidence.

## License and references

MIT — see [LICENSE](LICENSE). Independent community prototype; not affiliated with or endorsed by OpenAI or Anthropic. Vendor apps are not distributed here.

- [Claude Desktop shared configuration](https://code.claude.com/docs/en/desktop#shared-configuration)
- [Claude MCP documentation](https://code.claude.com/docs/en/mcp)
- [MCP cancellation semantics](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/cancellation)

## Release maintainers

Run `python3 scripts/package_release.py` on a native Mac to build and verify a DMG. The manual **Desktop Release** workflow builds and tests macOS arm64, macOS Intel and Windows x64 independently, then creates the version in `VERSION` as a preview release. Existing releases/assets are not overwritten. Runtime archive versions and SHA256 values are pinned in `menu/python-runtime.lock.json`; bundled third-party notices live under `licenses/python-runtime/` and inside the runtime. Apple Developer ID signing and notarization remain a separate publishing step; this workflow explicitly produces ad-hoc-signed previews.

Windows 发布步骤运行 `python scripts/package_windows.py`：产出 Setup.exe 和 Portable.zip，在隔离数据目录、PATH 无 Python/编译器的条件下测试解压迁移、MCP、托盘 UI、安装与卸载。未通过所有平台测试时不发布 Release。Windows 的传输端点来自已有桌面包的跨平台代码分支；原生命名管道 fixture 不是厂商应用端到端验收。
