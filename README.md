# Codex → Claude Desktop Bridge

[![CI](https://github.com/reshuibuduo/codex-claude-desktop-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/reshuibuduo/codex-claude-desktop-bridge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Experimental macOS menu-bar app that continues a failed Codex Desktop task in an already authenticated Claude Desktop Code session.**

复用已登录的 **Claude 桌面 Code**，无需另配独立 CLI 登录。监听一个选定的本机 Codex 对话，在符合条件的最终失败后，通过项目级 MCP 交接最新用户目标、有限可见上下文和同一项目目录。

> Prototype, not a vendor-supported integration. The Codex adapter uses a private, versioned desktop IPC protocol. Initial Claude standby setup requires a working-directory check and sending the standby prompt. It does not silently operate the desktop UI or migrate hidden model state.

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
- Source is Python standard library + native AppKit/Swift. No npm dependency or background launch agent.

## Download and install / 下载安装

**[Download v0.3.0 macOS installers](https://github.com/reshuibuduo/codex-claude-desktop-bridge/releases/tag/v0.3.0)** — choose `arm64.dmg` for Apple Silicon (M-series), or `x86_64.dmg` for Intel. Open the DMG, drag the app to Applications, eject the image, then launch the installed app. **Python is embedded: no compiler, Homebrew or separate Python installation is needed.**

**未公证预览版 / Not notarized:** the downloads are ad-hoc signed, not Apple Developer ID signed or notarized. Gatekeeper may block first launch. After checking the source and checksum, follow [Apple's per-app confirmation instructions](https://support.apple.com/en-us/102445) if you trust the download; managed Macs may not permit it. Do not disable Gatekeeper globally. See [installation notes](docs/INSTALL.txt).

Release CI verifies both native architectures on macOS 15 with an isolated HOME, no Python/compiler on PATH, and an app copied out of the DMG to a different path. The deployment target is macOS 13; this is not a claim that every OS/vendor-app combination has been tested.

## Requirements

- macOS 13+ (or newer if required by your Codex/Claude desktop version). The release app includes Python 3.12.15.
- **Source builds only:** Python 3.9+, Xcode Command Line Tools and network access to download the hash-pinned runtime.
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

## Connect after installation

1. Enter **one local Codex conversation UUID** and its actual project directory; save the binding. The bridge confirms that the live Codex thread belongs to that directory.
2. Click **打开 Claude 待命**. In Claude's **Environment** panel, explicitly confirm the real working directory, then send the prefilled prompt. A folder chip in the composer alone is not proof of the session's working directory.
3. Use Claude's normal MCP permission flow. The menu must show **等待故障 · Claude 桌面已待命** before failover is armed.
4. Keep that standby session open. When a new eligible terminal failure arrives, Claude receives the handoff and continues automatically.
5. **暂停** stops new handoffs, not a Claude task already executing. Normal menu exit also pauses the binding.

The app stores its local config and runtime state in `~/Library/Application Support/CodexClaudeBridge/`. `CODEX_CLAUDE_BRIDGE_DATA` can override this directory for local testing. Project `.mcp.json` edits preserve other connectors and have installation manifests/backups. Keep the app in Applications. After moving or upgrading it, pause/finish active work first, then save the binding again and reopen the Claude standby session. The MCP entry records the embedded interpreter path.

For an existing, correctly bound Claude session, use [the reusable standby prompt](docs/STANDBY_PROMPT.txt).

## Validate locally (no model requests)

```sh
python3 bridge_core.py --self-test
python3 -m unittest discover -s tests -v
python3 scripts/check_public_tree.py
```

The core has 70 assertions; the bridge's regression tests use synthetic IPC views and local subprocess fixtures. The build also runs 8 native menu-state checks. These tests are **not** live model acceptance.

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
scripts/package_release.py   DMG creation and relocated-bundle smoke tests
.github/workflows/release.yml native arm64/Intel build and preview publication
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

Run `python3 scripts/package_release.py` on a native Mac to build and verify a DMG. The manual **macOS Release** workflow builds and tests arm64 and Intel independently, then creates the version in `VERSION` as a preview release. Existing releases/assets are not overwritten. Runtime archive versions and SHA256 values are pinned in `menu/python-runtime.lock.json`; bundled third-party notices live under `licenses/python-runtime/` and inside the runtime. Apple Developer ID signing and notarization remain a separate publishing step; this workflow explicitly produces ad-hoc-signed previews.
