# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact source commit: `3f263c80ae230aa06fdacf447de1bf2ca1f1ff86`
- Source path: `runtime-source/execution_contract_controller.py`
- Git blob SHA: `c79cc063426d856b9aa6c40b5b165c6a1a05f962`
- SHA-256: `993af01ac1b58be0006cacdfa1dbe15156b55ed752e6e93a647356d9763d0067`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Reuse a cached controller only when its repository, exact source commit, source path, Git blob SHA, and SHA-256 all match this pointer.
3. Otherwise retrieve the file directly from the exact commit:
   - Endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=3f263c80ae230aa06fdacf447de1bf2ca1f1ff86`
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
