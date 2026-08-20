# Runtime Bootstrap

This pointer is migrating from the legacy Actions artifact delivery path to the canonical source file.

- Repository: `BestNameYet/Execution-Contract-Controller`
- Source path: `runtime-source/execution_contract_controller.py`
- Current known source commit: `8d7585ac16f12fe854dc75d34c60b5f3a3162c3b`
- Current known Git blob SHA: `1627f3b73604770622898f262a1527d4ba6ec112`

The workflow will replace this migration seed with the authoritative SHA-256-populated pointer. The canonical controller remains unchanged.

For every new prompt, invoke the verified controller with one fresh JSON line:

```json
{"schema":"execution-contract-controller-initialization-v1","type":"INITIALIZE","user_prompt":"<exact current user prompt>"}
```

Reuse a verified cached controller when its published identity matches. Retry fresh initialization against that cache first. Re-fetch only when identity changed, the cache is missing, or integrity verification fails.

Do not use Actions artifacts, ZIP downloads, extraction, artifact IDs, artifact digests, or retention state in the primary delivery path.
