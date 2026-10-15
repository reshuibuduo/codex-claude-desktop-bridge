# Security and data handling

This experimental tool reads a selected local coding conversation and hands bounded visible task context to another model provider. Bind only a project intended for both providers. Existing Claude permissions remain in effect; no credentials are copied by this bridge.

Runtime state, MCP configuration, transcripts and installation backups must remain local. `.gitignore` excludes common runtime outputs. The publication check catches a limited set of obvious accidental disclosures; it is not a comprehensive secret detector.

The Codex adapter is private/versioned and may break after vendor updates. The bridge's SQLite lease does not lock Codex writers. Unknown/uncertain deliveries stop for review instead of replaying automatically.

Report suspected issues with a minimal sanitized reproduction. Do not put credentials, account identifiers or conversation contents in public issues. For a vulnerability involving sensitive details, use GitHub's private vulnerability reporting when available, or first open an issue requesting a private contact channel without disclosing the exploit details.
