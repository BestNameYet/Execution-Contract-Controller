# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact source commit: `8d7585ac16f12fe854dc75d34c60b5f3a3162c3b`
- Source path: `runtime-source/execution_contract_controller.py`
- Git blob SHA: `1627f3b73604770622898f262a1527d4ba6ec112`
- SHA-256: `d9de33b843e73594f0faff61a4839c7f9e368ea1e2f239a6429d66b62956d7d0`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Reuse a cached controller only when its repository, exact source commit, source path, Git blob SHA, and SHA-256 all match this pointer.
3. Otherwise retrieve the file directly from the exact commit:
   - Endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=8d7585ac16f12fe854dc75d34c60b5f3a3162c3b`
   - Header: `Accept: application/vnd.github.raw+json`
   - Header: `Authorization: Bearer <GitHub token>`
4. Verify both hashes before invocation.
5. Retry a fresh initialization against a verified cached file first. Re-fetch only if identity changed, the cache is missing, or integrity verification fails.

Do not use Actions artifacts, ZIP downloads, extraction, artifact IDs, artifact digests, or retention state in the primary delivery path.

## Required initialization

For every new prompt, invoke the verified controller with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Follow the controller payloads for the remainder of the governed turn.
