# Runtime Bootstrap

This is the fixed bootstrap for the current Execution Contract Controller runtime, persistent carrier, runner, client, execution knowledge base, and published runtime artifact.

## GitHub access invariant

For every GitHub read, download, lookup, or mutation required by this bootstrap, use the connected GitHub connector only.

Never invoke `git`, `git clone`, `curl`, `wget`, direct unauthenticated GitHub HTTP access, or any shell/network substitute from the execution environment to access GitHub. Local shell commands may operate only on files already materialized in the execution environment.

## Runtime source

- Repository: `BestNameYet/Execution-Contract-Controller`
- Runtime source directory: `runtime-source/`
- Latest runtime-source commit at this bootstrap revision: `5ef5eb01f6759e156f1e232ff8aa76c89029a098`
- Published runtime files:
  - `execution_contract_controller.py`
  - `execution_knowledge_base.json`
  - `runtime_carrier.py`
  - `runtime_client.py`
  - `runtime_runner.py`

The authoritative runtime publication identity is the JSON object written into the `Published runtime artifact` block by the artifact workflow. Do not reconstruct publication identity from legacy per-file bootstrap hashes.

<!-- RUNTIME_PUBLICATION_BEGIN -->
## Published runtime artifact

```json
{
  "artifact_name": "execution-runtime-4d5486304e0d2bbaede754fe4a350a5d368b5c35",
  "files": [
    "execution_contract_controller.py",
    "execution_knowledge_base.json",
    "runtime_carrier.py",
    "runtime_client.py",
    "runtime_runner.py"
  ],
  "publication_date_time_utc": "2026-08-24T22:54:51Z",
  "repository": "BestNameYet/Execution-Contract-Controller",
  "schema": "execution-runtime-publication-v1",
  "source_commit": "4d5486304e0d2bbaede754fe4a350a5d368b5c35",
  "source_commit_author": "BestNameYet <samuel.john.nixon@gmail.com>",
  "source_commit_date_time": "2026-08-24T15:54:31-07:00",
  "source_commit_message": "Trigger runtime artifact publication",
  "workflow_run_attempt": "1",
  "workflow_run_id": "32786887021"
}
```

- Artifact URL: `https://github.com/BestNameYet/Execution-Contract-Controller/actions/runs/32786887021/artifacts/9541767524`
- Artifact ID: `9541767524`

The JSON above is the Git publication pointer. The archive contains the identical JSON as `runtime-publication.json`. The artifact URL and artifact ID are bootstrap-only transport fields and are added after upload; until then no artifact location is published.
<!-- RUNTIME_PUBLICATION_END -->

## Retrieval and cache rules

1. Read this bootstrap from `main` through the connected GitHub connector on every new prompt.
2. Read the JSON object in `Published runtime artifact`; this is the current Git publication pointer for the complete runtime unit.
3. If `/mnt/data/execution_runtime/runtime-publication.json` exists and is exactly equal as parsed JSON to the bootstrap publication JSON, and all five named runtime files are present, reuse the local runtime. Do not hash the extracted files for normal cache reuse.
4. Otherwise, require the bootstrap `Artifact URL` and `Artifact ID`, download that published archive through the connected GitHub connector, and extract it directly into `/mnt/data/execution_runtime/`.
5. Never use `git`, `git clone`, `curl`, `wget`, direct GitHub HTTP access, or shell/network substitutes to retrieve GitHub content. GitHub access for this bootstrap is connector-only.
6. The archive is flat and contains the five runtime files plus `runtime-publication.json` at its root.
7. Parse the extracted `/mnt/data/execution_runtime/runtime-publication.json` and require exact JSON equality with the bootstrap publication JSON. If they differ, do not use that extracted runtime.
8. After a successful match, keep the extracted JSON beside the runtime files as the local publication pointer. No per-file SHA-256 comparison is required to establish cache freshness.
9. If the bootstrap does not yet contain an `Artifact URL` and `Artifact ID`, publication is between its metadata and upload steps; do not use a stale prior artifact location.

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

1. Confirm that all five expected runtime files are present and, when publication metadata exists, that local `runtime-publication.json` exactly matches the bootstrap publication JSON.
2. If `/mnt/data/execution_runtime/runtime_manifest.json` exists, use the cached client to `PING` the carrier only as a liveness check.
3. If no carrier responds, stop any stale process if possible and start the cached carrier detached:

```bash
nohup python /mnt/data/execution_runtime/runtime_carrier.py \
  >/mnt/data/execution_runtime/runtime_carrier.log 2>&1 &
```

4. Do not perform legacy carrier identity validation, `BASE_SET` identity comparison, or carrier-ID gating during bootstrap. Carrier identity reconciliation is outside this bootstrap step.

The carrier owns `runtime_state.json`, `kb_overlay.json`, `runtime_manifest.json`, and the Unix socket `/tmp/execution-runtime.sock` across model/tool invocations in that runtime.

## Required invocation

For every new prompt, invoke the cached runner with exactly one fresh JSON line:

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
