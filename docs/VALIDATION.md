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
