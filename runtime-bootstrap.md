# Runtime Bootstrap

This is the fixed pointer for the current materialized Execution Contract Controller runtime and its execution knowledge base.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact runtime commit: `7efcda677dac031d6687b904ba982a3ae5039667`
- Controller path: `runtime-source/execution_contract_controller.py`
- Controller Git blob SHA: `6e49e9ee596b927fcb2b7036218068d97ddeb3a5`
- Controller SHA-256: `27e473f0109290a0e3d4d987498d21b83eb74f9914ded3e0528a372cb626dea6`
- Knowledge-base path: `runtime-source/execution_knowledge_base.json`
- Knowledge-base Git blob SHA: `c1bc59368b0521aae278c1f955b6fe4f5526c4c8`
- Knowledge-base SHA-256: `cf47a5a292c3663c1d81dfdf744acc86a5ec9de5ab5536a0765ca14647c9c709`
- Knowledge-base schema/version: `execution-knowledge-base-v1` / `2`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Treat the controller and knowledge base as one published runtime unit.
3. Reuse a cached runtime only when repository, exact runtime commit, both paths, both Git blob SHAs, both SHA-256 values, and KB schema/version match this pointer.
4. Otherwise retrieve the controller and KB directly from the exact runtime commit:
   - Controller endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=7efcda677dac031d6687b904ba982a3ae5039667`
   - Knowledge-base endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_knowledge_base.json?ref=7efcda677dac031d6687b904ba982a3ae5039667`
   - Header: `Accept: application/vnd.github.raw+json`
   - Header: `Authorization: Bearer <GitHub token>`
5. Store the controller and KB in the same runtime directory and verify both identities before invocation.
6. Do not apply any controller patch. The published controller is already the complete materialized runtime.
7. When `/mnt/data/execution_runtime/runtime_manifest.json` exists, the controller also consumes the live runtime's pending KB overlay on each retrieval. Pending same-ID records override the published base until publication. A present manifest with an unreadable or invalid overlay is a deterministic error.
8. Retry fresh initialization against the verified cached controller first. Re-fetch only if published identity changed, required files are missing, or integrity verification fails.

Do not use Actions artifacts, ZIP delivery, or workflow reconstruction in the runtime path.

## Required event recording

The published controller contains the recursion-safe event recorder. Its transport snapshots remove controller state and recording sidecars, recorder serialization omits recursive controller branches, detects object cycles, limits recursion depth, and caps oversized spreadsheet cell payloads.

Whenever a controller output contains a top-level `recording_instruction`:

1. Treat it as mandatory out-of-band observability, not as a semantic or execution-evaluation step.
2. Invoke the tool named by `recording_instruction.tool` exactly once with `recording_instruction.api_call` as the arguments. For the current runtime this is `Google_Drive.batch_update_spreadsheet`.
3. Pass the API call verbatim. Do not reconstruct, summarize, or feed the recording instruction or append result back into the controller.
4. Execute the append before returning a terminal user response or discarding the controller turn state.
5. A recording-tool failure does not alter the task's execution verdict. Report the exact recording failure instead of silently dropping the event record.

Terminal COMPLETE/IMPASSE outputs and controller protocol errors carry the batch recording instruction for all controller invocations accumulated in that turn.

## Required initialization

For every new prompt, invoke the verified controller with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Follow controller payloads for the remainder of the governed turn. Perform just-in-time typed knowledge retrieval; do not preload the full KB into model context.
