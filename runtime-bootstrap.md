# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime, persistent carrier, runner, client, and execution knowledge base.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact runtime commit: `0031ea213d04f8b60b9c3ec02f877320ce5cec2c`
- Controller: `runtime-source/execution_contract_controller.py`
  - Git blob SHA: `6e49e9ee596b927fcb2b7036218068d97ddeb3a5`
  - SHA-256: `27e473f0109290a0e3d4d987498d21b83eb74f9914ded3e0528a372cb626dea6`
- Knowledge base: `runtime-source/execution_knowledge_base.json`
  - Git blob SHA: `c1bc59368b0521aae278c1f955b6fe4f5526c4c8`
  - SHA-256: `cf47a5a292c3663c1d81dfdf744acc86a5ec9de5ab5536a0765ca14647c9c709`
  - Schema/version: `execution-knowledge-base-v1` / `2`
- Persistent carrier: `runtime-source/runtime_carrier.py`
  - Git blob SHA: `b558f492f3511db7ca1e303abc4f5fd7c80ad58a`
  - SHA-256: `f17a54a7e762f465da8c24abce745a9d7c33dd899feb8be86b0261a5fd3c6038`
- Carrier client: `runtime-source/runtime_client.py`
  - Git blob SHA: `58411d2b38090590ddb319e3430a777d9c2d8745`
  - SHA-256: `12a740097cd941c93b514870f7894b84d3c095a87b3af98e9ac0150f8c4ff158`
- Controller runner: `runtime-source/runtime_runner.py`
  - Git blob SHA: `478b4b258a47fad069ab8a840872ca5b344b1c94`
  - SHA-256: `8d4b126081f55c3da59f0a38c38ed68dcbf775e0de75363774b86b7ede8169d1`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Treat all five runtime-source files above as one published runtime unit.
3. Reuse a cached unit only when repository, exact runtime commit, paths, blob SHAs, SHA-256 values, and KB schema/version all match this pointer.
4. Otherwise retrieve each file directly from the exact runtime commit through the GitHub contents API with `Accept: application/vnd.github.raw+json` and authenticated access.
5. Store all five files together in `/mnt/data/execution_runtime/` and verify their identities before invocation.
6. Do not apply controller patches or reconstruct runtime files from Actions artifacts.

## Persistent event-state invariant

The persistent carrier state is the durable source of truth for controller invocation history.

`runtime_state.json` contains an append-only `events` array plus `event_sequence` and `sheet_recorded_through`. Every event node receives a monotonically increasing sequence, a global `parent_event_id`, and a same-turn `turn_parent_event_id`. Event payloads contain sanitized controller input/output snapshots; embedded controller `state`, `transport_history`, and recording sidecars are removed so the event queue cannot recursively contain itself.

Every finalized controller invocation MUST pass through `runtime_runner.py`. The runner synchronously appends that invocation to the carrier with `EVENT_APPEND` before returning the controller payload. Do not invoke `execution_contract_controller.py` directly for governed turns.

The Google Sheet is an append-only projection of the carrier queue, not the primary event store. A missed Sheet append must therefore remain reconstructable from carrier state.

To read the full persistent event history:

```bash
python /mnt/data/execution_runtime/runtime_client.py EVENTS_GET '{"after_sequence":0}'
```

## Carrier startup

Before the first governed invocation in a runtime:

1. Verify the five cached files against this pointer.
2. If `/mnt/data/execution_runtime/runtime_manifest.json` exists, use the verified client to `PING` the carrier.
3. Reuse the carrier only when it responds successfully and is the carrier for the verified runtime. Otherwise stop any stale carrier if possible and start the verified carrier detached:

```bash
nohup python /mnt/data/execution_runtime/runtime_carrier.py \
  >/mnt/data/execution_runtime/runtime_carrier.log 2>&1 &
```

The carrier owns `runtime_state.json`, `kb_overlay.json`, `runtime_manifest.json`, and the Unix socket `/tmp/execution-runtime.sock` across model/tool invocations in that runtime.

## Required invocation

For every new prompt, invoke the verified runner with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Example transport:

```bash
printf '%s\n' '<JSON line>' | python /mnt/data/execution_runtime/runtime_runner.py
```

Follow controller payloads for the remainder of the governed turn, always sending each subsequent controller input through `runtime_runner.py` as well.

A successful runner output carrying controller state also carries a `recording_event` receipt identifying the carrier sequence that was durably appended. A persistence error is not to be silently ignored.

## Sheet projection

When a terminal or protocol-error runner output contains `recording_instruction`:

1. Treat it as mandatory out-of-band observability, not semantic/execution work.
2. Invoke the tool named by `recording_instruction.tool` exactly once using `recording_instruction.api_call` verbatim.
3. Only after the Sheet append succeeds, invoke the local carrier exactly once with `recording_instruction.carrier_ack` (`EVENTS_MARK_RECORDED`).
4. Do not feed the Sheet result, carrier acknowledgement, or recording instruction into the controller semantic chain.
5. If the Sheet append fails, do not advance `sheet_recorded_through`; the unprojected events remain in the carrier queue and will be emitted again on a later terminal output.

This ordering makes the carrier queue recoverable and prevents both recursion and silent event loss.
