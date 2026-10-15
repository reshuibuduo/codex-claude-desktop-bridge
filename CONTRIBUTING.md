# Contributing

Open a focused issue or pull request. Include expected behavior, actual behavior, desktop versions, and a minimal synthetic reproduction. Do not include real conversations or raw app logs.

Run `python3 bridge_core.py --self-test`, `python3 -m unittest discover -s tests -v` and `python3 scripts/check_public_tree.py`. On macOS also run `./menu/build.sh` with a compatible installed SDK. Unit tests must not submit model requests or touch a real desktop conversation.

Protocol changes should include sanitized fixtures and fail-closed tests. Keep source/target identity checks, unknown-delivery review, historical-failure suppression and request-scoped cancellation explicit. Separate component tests from live model acceptance.

Contributions are licensed under the repository's MIT license. Do not submit extracted vendor bundles/source, credentials or other material you do not have the right to contribute.
