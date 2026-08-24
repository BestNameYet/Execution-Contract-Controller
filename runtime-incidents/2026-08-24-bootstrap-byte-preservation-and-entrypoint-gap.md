# Bootstrap byte preservation and fresh-model entrypoint gap

Date: 2026-08-24

## Event

While materializing the published Execution Contract Controller runtime into `/mnt/data/execution_runtime/`, `runtime_runner.py` failed its SHA-256 identity check even though the correct GitHub repository object had been retrieved.

The mismatch was caused by the retrieval/materialization path rather than evidence that the published runner had changed. Repository content had been obtained through a decoded/rendered text representation and then reconstructed as a local file. That path is not guaranteed to preserve exact bytes. Differences such as a final newline, line endings, encoding normalization, or other invisible text transformations are sufficient to change SHA-256 while leaving the source visually and semantically unchanged.

The SHA-256 gate therefore behaved correctly: execution stopped because exact local byte identity could not be established.

## Resolution discovered

The installed GitHub connector exposes a byte-preserving repository-file retrieval mode through `fetch_file` with `encoding="base64"`.

The correct materialization path is:

1. Read `runtime-bootstrap.md` from `main`.
2. Take the exact runtime commit and expected file identities from that pointer.
3. Retrieve each published runtime file from that exact commit using GitHub `fetch_file(..., encoding="base64")`.
4. Base64-decode the returned content locally.
5. Write the decoded bytes directly in binary mode without text reconstruction or normalization.
6. Compute SHA-256 over the resulting local bytes.
7. Compare the result with the SHA-256 published in `runtime-bootstrap.md`.
8. Start or invoke the runtime only after every file in the published unit passes identity verification.

Text-rendered connector output should not be used to reconstruct files whose execution is gated by exact-byte hashes.

## Architectural finding: fresh-model entrypoint gap

The incident exposed a separate bootstrap problem.

The execution knowledge base contains heuristics, procedures, patterns, and capabilities that improve runtime behavior. A model that has already retrieved and invoked the runtime can use those records. A fresh model, however, does not yet have access to the runtime knowledge base and therefore cannot depend on those heuristics to learn how to bootstrap itself.

This creates a circularity risk:

`model needs runtime knowledge -> runtime knowledge requires runtime retrieval -> retrieval procedure is only known after runtime knowledge is available`

The external introduction mechanism must therefore be completely specified outside the runtime knowledge base.

A fresh model needs an authoritative instruction that identifies, without relying on any prior runtime state or heuristics:

- the repository: `BestNameYet/Execution-Contract-Controller`
- the bootstrap file: `runtime-bootstrap.md`
- that the bootstrap must be read from the repository's current `main`
- that the bootstrap's exact runtime commit is authoritative for runtime file retrieval
- that published files must be retrieved byte-preservingly, preferably through GitHub `fetch_file` with `encoding="base64"`, then decoded and written as bytes
- that the published SHA-256 values must be checked before execution
- that the persistent carrier and `runtime_runner.py` are the governed execution path
- that the exact current user prompt must be sent as a fresh `INITIALIZE` message

The key architectural point is that this introduction mechanism must be available to the model **before** the controller and execution knowledge base are loaded. It is therefore part of the external bootstrap contract, not something that can safely be left only as a heuristic inside `execution_knowledge_base.json`.

## Consequence

There are two distinct layers of initialization knowledge:

1. **External introduction knowledge** — the minimum deterministic instructions required for a fresh model to locate, verify, materialize, and invoke the runtime.
2. **Runtime execution knowledge** — the heuristics, procedures, patterns, capabilities, and learned execution policy available only after the runtime is loaded.

The first layer must not depend on the second. Otherwise a model that has not previously loaded the repository cannot reliably enter the system.

This record documents the event and the discovered design requirement only. It does not modify the runtime, bootstrap, controller, knowledge base, carrier, client, or runner.