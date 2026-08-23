# Runtime Bootstrap

This is the fixed pointer for the current Execution Contract Controller runtime, its execution knowledge base, and the tested controller patch.

## Current runtime identity

- Repository: `BestNameYet/Execution-Contract-Controller`
- Exact runtime commit: `f52b30c4b76c05cd3e168572346f3f6f87f4bcf3`
- Base controller path: `runtime-source/execution_contract_controller.py`
- Base controller Git blob SHA: `5fbdba9c3ecb92aaa319f9d2da89e94bbe968a31`
- Base controller SHA-256: `6aafab3cda8152ac81ad42f455c6f3d0ae703b5f991848b55be8f314892a7888`
- Controller patch path: `runtime-source/controller_transport_fix.patch`
- Controller patch Git blob SHA: `a79c409ca7452a1dfe051379dc228dff8381bbcc`
- Controller patch SHA-256: `9994d2e19caf1f5e98e3dbe14b8f76a4d55efa777655dd40e45cd04d8d37efbf`
- Effective patched controller SHA-256: `27e473f0109290a0e3d4d987498d21b83eb74f9914ded3e0528a372cb626dea6`
- Knowledge-base path: `runtime-source/execution_knowledge_base.json`
- Knowledge-base Git blob SHA: `c1bc59368b0521aae278c1f955b6fe4f5526c4c8`
- Knowledge-base SHA-256: `cf47a5a292c3663c1d81dfdf744acc86a5ec9de5ab5536a0765ca14647c9c709`
- Knowledge-base schema/version: `execution-knowledge-base-v1` / `2`

## Retrieval and cache rules

1. Read this pointer from `main`.
2. Treat the base controller, controller patch, and knowledge base as one published runtime unit.
3. Reuse a cached runtime only when repository, exact runtime commit, all three paths, all Git blob SHAs, all published SHA-256 values, the effective patched-controller SHA-256, and KB schema/version match this pointer.
4. Otherwise retrieve the base controller, patch, and KB directly from the exact runtime commit:
   - Base controller endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_contract_controller.py?ref=f52b30c4b76c05cd3e168572346f3f6f87f4bcf3`
   - Patch endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/controller_transport_fix.patch?ref=f52b30c4b76c05cd3e168572346f3f6f87f4bcf3`
   - Knowledge-base endpoint: `https://api.github.com/repos/BestNameYet/Execution-Contract-Controller/contents/runtime-source/execution_knowledge_base.json?ref=f52b30c4b76c05cd3e168572346f3f6f87f4bcf3`
   - Header: `Accept: application/vnd.github.raw+json`
   - Header: `Authorization: Bearer <GitHub token>`
5. Store the base controller and KB in the same runtime directory. Verify the base controller, patch, and KB identities before mutation.
6. Apply the patch to the base controller exactly once using deterministic unified-diff semantics. The resulting controller must hash to `27e473f0109290a0e3d4d987498d21b83eb74f9914ded3e0528a372cb626dea6`. An already-patched or non-applicable base is an integrity failure, not a reason to improvise.
7. When `/mnt/data/execution_runtime/runtime_manifest.json` exists, the effective controller also consumes the live runtime's pending KB overlay on each retrieval. Pending same-ID records override the published base until publication. A present manifest with an unreadable or invalid overlay is a deterministic error.
8. Retry fresh initialization against the verified effective cached controller first. Re-fetch/reconstruct only if published identity changed, required files are missing, or integrity verification fails.

Do not use Actions artifacts or ZIP delivery in the primary runtime path.

## Required initialization

For every new prompt, invoke the verified effective controller with exactly one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Follow controller payloads for the remainder of the governed turn. Perform just-in-time typed knowledge retrieval; do not preload the full KB into model context.
