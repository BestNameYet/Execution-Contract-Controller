# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact source commit: `9432146f61286690f3ee7b2d60d7108706c73ba7`
- Source path: `runtime-source/execution_contract_controller.py`
- Git blob SHA: `3e91fbed91a9a8e434cafbac5188f7b3ecad4461`
- SHA-256: `573fb2085ca6738c68751e62cdd7d02f2d013f58dbf10582e01de0f3edb74eec`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Reuse a cached controller only when its repository, exact source commit, source path, Git blob SHA, and SHA-256 all match this pointer.
3. Otherwise retrieve the file directly from the exact commit:
   - Endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=9432146f61286690f3ee7b2d60d7108706c73ba7`
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
