# Inter-Chat Runtime Sync Discovery — Chat A

> STATUS: EXPERIMENTAL / TEMPORARY / NON-CANONICAL
>
> This file records the current transport problem and a concrete discovery/test protocol. It must not change `runtime-source/*` or `runtime-bootstrap.md` during the parallel experimental phase.

## Problem

Two chats in the same ChatGPT project do not currently have a proven project-wide shared filesystem or a proven direct runtime-to-runtime transport. A file or mutable data object created inside one chat's local runtime cannot yet be assumed to appear in the other chat's runtime.

## Current runtime observations

On Chat A's current runtime:

- `OAI_SHARE_DIR=/home/oai/share`
- `OAI_MNT_DIR=/mnt/data`
- `CUA_DD_INIT_SYNC_SHARE=false`
- `CUA_DD_INIT_RSYNC_DAEMON=false`
- `REMOTE_SHARE_HOST` is unset.
- `/usr/local/init_scripts/sync_share.sh` exists.
- `/usr/local/init_scripts/rsync_daemon.sh` exists.
- `/etc/rsyncd.conf` exposes module `[share]` at `/home/oai/share`, writable as uid 1000/gid 1001.
- No rsync daemon or inotify-based sync process is currently running.
- The shipped sync script is a continuous one-way push from `/home/oai/share/` to `rsync://$REMOTE_SHARE_HOST/share`, first doing one sync and then using `inotifywait` to repeat on close-write/delete/move events.
- The shipped daemon/sync startup scripts both depend on orchestration-provided `REMOTE_SHARE_HOST` and enable flags. Those bindings are absent in this runtime.

This indicates that the container image contains an intended cross-runtime share mechanism, but the current chat runtime has not been provisioned with the peer binding required to activate it.

## Resolution target

Before building inter-chat messaging on top of the Transaction framework, establish one transport with these properties:

1. Both chat runtimes can address the same durable data substrate or each other directly.
2. Data written by Chat A can be read by Chat B without user copy/paste.
3. Data written by Chat B can be read by Chat A without user copy/paste.
4. Writes are deterministic and conflict-safe.
5. The transport can carry structured JSON objects and files.
6. The transport remains available while a chat is blocked waiting for a response.

## Symmetric discovery protocol for both chats

Each chat should independently record the following runtime endpoint facts in the shared Events ledger and its own experimental sync file:

- chat role (`chat_a` or `chat_b`)
- runtime hostname
- runtime IPv4/IPv6 addresses
- route table
- `REMOTE_SHARE_HOST` value or absence
- `CUA_DD_INIT_SYNC_SHARE`
- `CUA_DD_INIT_RSYNC_DAEMON`
- whether TCP 873 or a chosen test port is listening
- whether `/home/oai/share` exists and is writable

Then perform the following cross-chat test using the shared Events ledger only as bootstrap coordination:

### Phase 1 — endpoint advertisement

Each chat writes its current hostname/IP/test-port tuple and a unique probe token to the shared Events sheet. The other chat reads that row.

### Phase 2 — direct reachability

Each runtime starts a temporary rsync daemon on a non-conflicting test port using the existing `[share]` module, then the peer tests TCP reachability and an rsync module listing by the advertised address.

If direct reachability succeeds in both directions, proceed to Phase 3.

If direct reachability fails despite addresses being on an apparently routable subnet, record the exact socket error. This establishes that container network policy prevents direct runtime-to-runtime transport; do not keep guessing IPs.

### Phase 3 — file propagation

Chat A creates a unique file under `/home/oai/share/interchat-sync-probe/` and pushes it to Chat B's rsync module. Chat B verifies exact filename, byte length, and SHA-256. Repeat B -> A with a different file.

### Phase 4 — structured object propagation

Repeat with canonical JSON containing a sequence, sender, recipient, correlation id, and payload. Verify exact SHA-256 after transfer.

### Phase 5 — continuous sync

Only after one-shot transfer is proven, activate an inotify-driven sync loop. Do not use simultaneous blind bidirectional directory mirroring for mutable shared state. Use either:

- append-only per-agent message/event files, or
- one authoritative carrier with explicit compare-and-swap/versioned writes.

## Decision tree

```text
Can A reach B's temporary rsync listener?
  |
  +-- NO --> direct runtime transport unavailable under current network policy
  |           |
  |           +--> use an external shared store exposed to both chats
  |                (Sheets for coordination/JSON; GitHub/Drive for durable artifacts)
  |
  +-- YES --> Can B reach A?
              |
              +-- NO --> asymmetric transport; do not use as shared carrier
              |
              +-- YES --> prove exact file + JSON transfer both directions
                           |
                           +--> then build carrier/message semantics
```

## Important distinction

The existing shared Google Sheet already proves a cross-chat shared state channel at the model/connector layer. It does **not** prove that the two local machine runtimes share `/mnt/data` or `/home/oai/share`, nor that a background carrier process in one runtime is directly reachable by the other.

The next task is therefore transport discovery, not Transaction-framework implementation.
