# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact source commit: `f386ecc18bf06e1bbca218dddc4edc6e9d518713`
- Source path: `runtime-source/execution_contract_controller.py`
- Git blob SHA: `240b64aee1e6c2548c2fd9a97cab6756c0aa226e`
- SHA-256: `45619c8072ed536c67c8867f208d541854c9f56f4f7bef43edee06026b765f04`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Reuse a cached controller only when its repository, exact source commit, source path, Git blob SHA, and SHA-256 all match this pointer.
3. Otherwise retrieve the file directly from the exact commit:
   - Endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=f386ecc18bf06e1bbca218dddc4edc6e9d518713`
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
