# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact source commit: `9ab81306810fd8e470ada2892ea44f90f640b4ad`
- Source path: `runtime-source/execution_contract_controller.py`
- Git blob SHA: `7873654ded5dae813a528692d7241e48801edb71`
- SHA-256: `74717e2a98ce3aaa897d88d5234d61409a99434143337cab6bda683b87ff3d56`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Reuse a cached controller only when its repository, exact source commit, source path, Git blob SHA, and SHA-256 all match this pointer.
3. Otherwise retrieve the file directly from the exact commit:
   - Endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=9ab81306810fd8e470ada2892ea44f90f640b4ad`
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
