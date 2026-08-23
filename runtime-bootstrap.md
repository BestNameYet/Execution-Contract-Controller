# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime and its execution knowledge base.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact runtime commit: `59c031a57e0d7689e8e6e4a34fa1be4692bedd66`
- Controller path: `runtime-source/execution_contract_controller.py`
- Controller Git blob SHA: `5fbdba9c3ecb92aaa319f9d2da89e94bbe968a31`
- Controller SHA-256: `6aafab3cda8152ac81ad42f455c6f3d0ae703b5f991848b55be8f314892a7888`
- Knowledge-base path: `runtime-source/execution_knowledge_base.json`
- Knowledge-base Git blob SHA: `c1bc59368b0521aae278c1f955b6fe4f5526c4c8`
- Knowledge-base SHA-256: `cf47a5a292c3663c1d81dfdf744acc86a5ec9de5ab5536a0765ca14647c9c709`
- Knowledge-base schema/version: `execution-knowledge-base-v1` / `2`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Treat the controller and knowledge base as one published runtime unit. Reuse a cached published runtime only when the repository, exact runtime commit, both paths, both Git blob SHAs, both SHA-256 values, and the knowledge-base schema/version all match this pointer.
3. Otherwise retrieve both files directly from the exact runtime commit:
   - Controller endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=59c031a57e0d7689e8e6e4a34fa1be4692bedd66`
   - Knowledge-base endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_knowledge_base.json?ref=59c031a57e0d7689e8e6e4a34fa1be4692bedd66`
   - Header: `Accept: application/vnd.github.raw+json`
   - Header: `Authorization: Bearer <GitHub token>`
4. Store both files in the same runtime directory so the controller can resolve `execution_knowledge_base.json` beside `execution_contract_controller.py`.
5. Verify both Git blob SHAs and both SHA-256 values before invocation.
6. When `/mnt/data/execution_runtime/runtime_manifest.json` exists, the controller also consumes that live runtime's pending KB overlay on each retrieval. Pending same-ID records override the published base until publication. A present manifest with an unreadable or invalid overlay is a deterministic error; do not silently discard pending runtime-only knowledge.
7. Retry a fresh initialization against the verified cached/runtime-attached controller first. Re-fetch only if published identity changed, required files are missing, or integrity verification fails.

Do not use Actions artifacts, ZIP downloads, extraction, artifact IDs, artifact digests, or retention state in the primary delivery path.

## Required initialization

For every new prompt, invoke the verified controller with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Follow the controller payloads for the remainder of the governed turn. The controller performs just-in-time typed knowledge retrieval before materially new action selection; do not preload the full knowledge base into model context.
