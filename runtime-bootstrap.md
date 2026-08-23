# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime and its execution knowledge base.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact runtime commit: `871c0c808aa9f5ae5b2889be398bcb7bac8df10d`
- Controller path: `runtime-source/execution_contract_controller.py`
- Controller Git blob SHA: `65ada594db71bc9dfdb4c21dad3e838d1b31cbd2`
- Controller SHA-256: `b5a920426046db63c456db53b43c8c8dc2d0ff4293c21990573bbf4d870eca00`
- Knowledge-base path: `runtime-source/execution_knowledge_base.json`
- Knowledge-base Git blob SHA: `97734aec10329f5a6788001383d7c8be8aa8459b`
- Knowledge-base SHA-256: `fc82218417d59560b916ef910d59907f62e8e2d4d91d2a78bf6e72bfa9297636`
- Knowledge-base schema/version: `execution-knowledge-base-v1` / `1`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Treat the controller and knowledge base as one runtime unit. Reuse a cached runtime only when the repository, exact runtime commit, both paths, both Git blob SHAs, both SHA-256 values, and the knowledge-base schema/version all match this pointer.
3. Otherwise retrieve both files directly from the exact runtime commit:
   - Controller endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=871c0c808aa9f5ae5b2889be398bcb7bac8df10d`
   - Knowledge-base endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_knowledge_base.json?ref=871c0c808aa9f5ae5b2889be398bcb7bac8df10d`
   - Header: `Accept: application/vnd.github.raw+json`
   - Header: `Authorization: Bearer <GitHub token>`
4. Store both files in the same runtime directory so the controller can resolve `execution_knowledge_base.json` beside `execution_contract_controller.py`.
5. Verify both Git blob SHAs and both SHA-256 values before invocation.
6. Retry a fresh initialization against the verified cached runtime first. Re-fetch only if identity changed, either file is missing, or integrity verification fails.

Do not use Actions artifacts, ZIP downloads, extraction, artifact IDs, artifact digests, or retention state in the primary delivery path.

## Required initialization

For every new prompt, invoke the verified controller with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Follow the controller payloads for the remainder of the governed turn. The controller performs just-in-time typed knowledge retrieval before materially new action selection; do not preload the full knowledge base into model context.
