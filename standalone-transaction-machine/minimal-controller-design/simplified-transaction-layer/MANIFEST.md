# Simplified Transaction Layer Manifest

This document is the manifest for `standalone-transaction-machine/minimal-controller-design/simplified-transaction-layer/`.

| Path | Type | Purpose |
|---|---|---|
| `README.md` | File | States the purpose of this subfolder as the design and implementation area for a simplified transaction layer. |
| `MANIFEST.md` | File | Lists the files and directories in this subfolder and describes their repository role. |
| `transaction_layer.py` | File | Implements the simplified transaction function, runner creation, caller/script stream relays, in-memory event recording, receipt writing, and receipt verification. |
| `test_transaction_streams.py` | File | Exercises one transaction with 10 stdin events, 10 stdout events, and 10 stderr events and verifies the persisted receipt matches the in-memory receipt. |
| `requirements/` | Directory | Contains the current requirements and implementation-evidence tracking for the simplified transaction layer. |
| `requirements/REQUIREMENTS.md` | File | Maintains requirement IDs, requirement text, status, and exact script/line evidence showing where each requirement is met. |

Update this manifest when files or directories are added, removed, renamed, or their repository role changes.
