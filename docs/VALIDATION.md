# Validation boundaries

The initial local desktop experiment passed a genuine but controlled failure-to-continuation chain. A deliberately unsupported model produced a real Codex HTTP 400. The selected authenticated Claude Desktop Code session was already waiting through MCP; it received the new failure, repaired the isolated toy function, and passed all six unchanged tests. No new user task prompt was sent to Claude after the source failure.

This establishes the transport and continuation path for that controlled setup. It does not establish general outage reliability. It is not evidence of a naturally occurring busy-model incident.

## Separate evidence classes

1. **Core tests:** 70 deterministic assertions, no desktop connection or model call.
2. **Regression tests:** synthetic versioned IPC messages; real local fake subprocesses where relevant; persistent arm cursor, deduplication, request-scoped cancellation, EOF handling, explicit recovery, config backup and directory checks.
3. **Native checks:** 8 menu-state assertions; local build and ad-hoc signature validation.
4. **Observed live experiment:** actual Codex failure → actual Claude Desktop work → fixed independent tests.
5. **Observed packaged UI:** real standby state and menu-triggered pause. Initial deep-link folder mismatch was found and corrected through the native directory selector.

The public repository intentionally contains only source and reproducible offline tests. Raw local transcripts, account information, conversation IDs, live configuration, installation backups and original acceptance logs remain outside version control. The description above is a maintainer-reported result, not independently reproducible evidence of vendor availability.

## Still to validate live

- Real overload, rate limiting and transient transport failures.
- Overnight waiting, timeout re-arm in the real client, sleep/wake and process restarts.
- Multiple independent project writers and an isolated-worktree merge strategy.
- Other Codex/Claude Desktop versions, Intel Macs, remote/cloud tasks.

The bridge's source snapshots describe the current turn. They are not a cross-application lock. Generic completion is agent-reported. An uncertain target execution requires explicit review rather than automatic retry.


## v0.4.0 Windows preview

Windows adds a native WinForms tray, per-user installer and portable archive with pinned embedded CPython. The desktop IPC adapter selects a local named pipe on Windows and the existing Unix socket on macOS. The Windows endpoint was observed in the shipped desktop bundle's cross-platform branch; this is static evidence, not proof that every Windows build exposes the same protocol.

Release CI runs on Windows Server 2025 x64. It exercises real local Win32 named-pipe framing, timeout/cancellation, partial-frame preservation, disconnect and identity-rejection fixtures; cross-process file locks; UTF-8 project paths; MCP startup and restoration; relocated portable startup with no Python/compiler on PATH; and per-user installer/uninstaller behavior with retained user data. The four earlier POSIX standalone CLI process fixtures are skipped on Windows; the desktop MCP tests are not skipped. Legacy CLI execution is not a Windows feature.

**Not established:** real Windows Codex Desktop owner discovery, real Claude Desktop Code folder/deep-link behavior, or an automatic live fault handoff on Windows 10/11. The first installation must establish a real standby connection before use. ARM64, WSL and remote conversations are not validated. Windows binaries have no Authenticode certificate; macOS packages remain ad-hoc signed and not notarized.
