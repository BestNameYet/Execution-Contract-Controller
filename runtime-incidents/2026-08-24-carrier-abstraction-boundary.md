# Carrier Abstraction Boundary: Model Must Not Manage Persistence Internals

Date: 2026-08-24

## Summary

The current bootstrap leaks the persistent-carrier implementation into the model-facing procedure. It tells the agent to inspect `runtime_manifest.json`, decide whether a carrier is present, `PING` it, start `runtime_carrier.py` when needed, issue `BASE_SET`, and reason about carrier reuse.

That is the wrong abstraction boundary.

The carrier is runtime infrastructure. The model should not know whether persistence is implemented by a manifest, Unix socket, detached child process, client helper, or any other internal mechanism. Exposing those details creates extra branches, extra failure modes, and unnecessary semantic/control work before the model can execute the user's actual task.

## Current leaked path

The present bootstrap effectively requires the agent to perform lifecycle management:

1. Verify the runtime files.
2. Check for `/mnt/data/execution_runtime/runtime_manifest.json`.
3. If a manifest exists, invoke the client and `PING` the carrier.
4. If no carrier responds, start `runtime_carrier.py` detached.
5. Invoke `BASE_SET` through `runtime_client.py`.
6. `PING` again and compare published-base identity.
7. Invoke `runtime_runner.py` for controller work.

This makes the agent the carrier supervisor.

## Correct abstraction

The correct procedure is:

1. The model retrieves and verifies the published runtime unit.
2. The model starts or invokes **one model-facing runtime process/entrypoint**.
3. That process automatically establishes persistence internally.
4. If a persistent carrier does not exist, the process creates/starts it.
5. If a valid carrier already exists, the process attaches/reuses it.
6. Manifest inspection, socket discovery, process startup, `PING`, `BASE_SET`, state recovery, and carrier-client calls are private implementation details performed deterministically inside the runtime.
7. The model communicates only with the single model-facing execution interface and receives only the controller/runtime response required for the governed turn.

The process presented to the model is therefore already the persistent runtime surface. From the model's perspective there is no separate carrier-management protocol.

## Required model-facing contract

The model should have one operation conceptually equivalent to:

```text
runtime(<controller input>) -> <controller/runtime output>
```

The implementation may internally use a daemon, child process, Unix-domain socket, manifest, event queue, or helper client, but none of those mechanisms should become preconditions or decision points in the agent's execution procedure.

A missing manifest must not cause a model-visible branch. A missing manifest is simply internal state meaning the runtime must initialize persistence before processing the request.

Likewise, an existing manifest must not require the model to decide whether it is stale or whether the carrier should be restarted. The model-facing process performs that determination mechanically.

## Current model-facing transport

At the time of this write-up, `runtime_runner.py` is a command-line program. Its `main()` implementation:

- reads exactly one JSON line from **stdin** using `sys.stdin.readline()`;
- parses that line as the controller input;
- calls the controller and synchronously persists the resulting invocation through the carrier client;
- writes exactly one JSON object to **stdout** with `print(json.dumps(...))`;
- uses process exit status to distinguish normal completion, protocol error, and persistence failure.

Thus the current model-facing transport is effectively:

```bash
printf '%s\n' '<JSON input>' | python /mnt/data/execution_runtime/runtime_runner.py
```

with the JSON controller/runtime response returned on stdout.

That stdin/stdout command-line transport is acceptable as a model-facing mechanism. What is not acceptable is requiring the model to separately operate `runtime_client.py`, inspect `runtime_manifest.json`, start `runtime_carrier.py`, issue `PING`, or issue `BASE_SET`.

## Target runtime shape

The desired boundary is:

```text
MODEL
  |
  | one JSON request through one model-facing invocation surface
  v
MODEL-FACING RUNTIME PROCESS
  |
  |-- ensure/attach/start persistence internally
  |-- validate published runtime identity internally
  |-- maintain manifest/socket/carrier internally
  |-- dispatch controller input
  |-- persist invocation before returning
  v
one JSON response to model
```

The carrier is therefore **behind** the model-facing process, not beside it.

## Why this matters

This correction has the same architectural purpose as moving execution policy out of hard-coded model procedure and into deterministic/runtime mechanisms: details that do not require semantic judgment should not be exposed to the semantic agent.

Carrier lifecycle is mechanically decidable. It should therefore be encapsulated deterministically.

Benefits:

- removes unnecessary agent-visible setup steps;
- prevents semantic reasoning about manifest/socket/process state;
- eliminates a class of foot-dragging and bootstrap divergence;
- makes fresh-model startup identical whether persistence already exists or not;
- reduces the external bootstrap contract to retrieval, verification, and one invocation surface;
- permits the carrier implementation to evolve independently without changing agent instructions.

## Required fix

A future runtime revision should introduce or revise the model-facing entrypoint so that carrier establishment is automatic and private. The external bootstrap should no longer instruct an agent to:

- inspect `runtime_manifest.json`;
- invoke `runtime_client.py` directly;
- `PING` the carrier;
- start `runtime_carrier.py` itself;
- send `BASE_SET`;
- reason about carrier reuse or stale carrier processes.

Instead it should instruct the agent only to invoke the verified model-facing runtime entrypoint with the required controller JSON input. That entrypoint is responsible for guaranteeing that persistence is established before the controller operation is finalized.

## Relationship to the bootstrap-entrypoint incident

This issue compounds the separate fresh-model bootstrap problem documented in the prior incident record. A model that has not yet loaded the repository cannot benefit from internal knowledge-base heuristics, so the external introduction mechanism must be explicit. Once that introduction retrieves the runtime, however, the runtime should immediately collapse to a single execution surface. The introduction mechanism should not expose a second layer of carrier-administration instructions.

The intended boundary is therefore:

```text
external introduction -> retrieve/verify runtime -> invoke one runtime surface
                                              |
                                              +-> all carrier mechanics remain private
```

No existing runtime source or bootstrap file was modified by this write-up.
