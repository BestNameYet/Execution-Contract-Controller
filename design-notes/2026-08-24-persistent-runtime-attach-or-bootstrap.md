# Persistent Runtime: Attach-or-Bootstrap Design

Date: 2026-08-24

## Purpose

The transactional machine should preserve two distinct forms of continuity without introducing a second control architecture:

1. **Live persistence** — a detached runtime process remains available across separate script invocations and owns mutable in-memory state while it is alive.
2. **Durable persistence** — every completed transaction writes an immutable timestamped `TransactionOutcome` JSON record that survives runtime death and can be used for recovery, provenance, and historical analysis.

Every script invocation therefore begins with the same operation: **attach to the existing live runtime if one is available; otherwise bootstrap a new persistent runtime and continue.**

The persistence mechanism is infrastructure. It does not decide what semantic action should be taken and does not replace the CREATE / REVISE / EXECUTE transaction model.

---

## Core Runtime Pattern

```text
script invocation
      |
      v
check for live runtime carrier
      |
      +-------------------------+
      |                         |
      v                         v
carrier reachable          carrier absent/unreachable
      |                         |
      v                         v
attach to carrier          remove stale endpoint if needed
      |                         |
      |                         v
      |                    start detached carrier
      |                         |
      +------------+------------+
                   |
                   v
         submit current transaction
                   |
                   v
             receive outcome
                   |
                   v
               script exits
```

A short-lived invocation is only a client. The detached runtime carrier is the live owner of mutable runtime state.

## Authoritative Liveness Test

A PID file by itself is not sufficient evidence that the desired runtime is alive. PIDs can be stale or reused.

The authoritative test should be **successful communication with the runtime endpoint**, preferably a Unix-domain socket in the shared local runtime namespace.

```text
runtime.sock exists?
      |
      +-- no --> bootstrap runtime
      |
      +-- yes --> connect and issue identity/health request
                      |
                      +-- succeeds --> attach
                      |
                      +-- fails ----> stale endpoint; clean up and bootstrap
```

The socket is therefore both the communication path and the operational proof that a carrier can accept work. A PID may still be recorded as diagnostic metadata, but it is not the authoritative liveness predicate.

## Runtime Identity

The carrier should expose a minimal identity object so an invocation can distinguish "a process is listening" from "the correct runtime is listening."

A sibling identity file may contain:

```json
{
  "pid": 12345,
  "socket": "/mnt/data/.../runtime.sock",
  "generation": "<runtime-generation-id>",
  "started_at": "2026-08-24T22:00:00.000000Z",
  "runtime_identity": "<content/version identity>"
}
```

The invocation may compare the available carrier's identity with the runtime identity it expects. If the identities match, it reuses the carrier. If they do not match, it starts the appropriate generation rather than silently attaching to an incompatible process.

Identity comparison is deterministic.

## Invocation Algorithm

Conceptually, every script invocation should reduce to:

```python
def invoke(transaction_request):
    runtime = attach_if_live_and_compatible()
    if runtime is None:
        runtime = bootstrap_detached_runtime()
    return runtime.handle(transaction_request)
```

The bootstrap path should:

1. create or confirm the runtime directory;
2. remove only a stale endpoint that failed the liveness test;
3. start the runtime carrier detached from the invoking process;
4. wait only for the carrier's local endpoint to become usable;
5. verify the carrier identity;
6. submit the transaction through the same interface used for an already-running runtime.

Once bootstrap is complete, the caller should not use a different execution path. Both fresh and resumed invocations converge on the same runtime request interface.

## Detached Runtime Carrier Responsibilities

The persistent carrier may own:

- current in-memory transactional state;
- loaded or cached canonical KB state;
- transaction sequencing;
- local IPC;
- generation/runtime identity;
- creation of completed `TransactionOutcome` records;
- reusable deterministic runtime resources whose identity remains valid.

The carrier should **not** become the semantic decision maker. Semantic decisions remain in the model-facing transaction protocols and generated contracts.

The carrier also should not invent a second checkpoint representation when the transaction outcomes already contain the durable state required for reconstruction.

## Durable Transaction Outcomes

Every successfully completed transaction produces a `TransactionOutcome`:

```json
{
  "result": {},
  "transition": {},
  "receipt": {}
}
```

The transaction function persists that complete object as its final action before returning.

The persistence destination is obtained from the sibling location-reference file:

```text
transaction_outcome_location.json
```

Example:

```json
{
  "location": "."
}
```

Rules:

- If the location-reference file exists and contains a usable location, use it.
- Relative locations resolve from the runtime source directory.
- Absolute locations are permitted.
- If the file is absent, malformed, or does not contain a usable location, initialize/fall back to the runtime source directory.
- Create the destination directory if necessary.
- Write one immutable, timestamped JSON file per completed transaction.
- A `null` semantic result is still a completed transaction and must still produce an outcome file.

Example filename:

```text
transaction-outcome-20260824T221548.131327Z.json
```

The outcome file is the durable checkpoint.

## Live Persistence vs. Durable Persistence

These mechanisms solve different problems:

```text
LIVE PERSISTENCE
Detached runtime process
    -> mutable in-memory state
    -> fast reuse between invocations
    -> avoids repeated reconstruction

DURABLE PERSISTENCE
Timestamped TransactionOutcome files
    -> survives process/runtime death
    -> recovery source
    -> provenance
    -> historical analysis
```

The live runtime is an optimization and continuity carrier. The outcome log is authoritative durable history.

A live runtime may disappear at any time without destroying completed transaction history.

## Recovery After Runtime Death

If the live carrier dies:

```text
next invocation
    |
    v
socket connection fails
    |
    v
bootstrap new carrier
    |
    v
read durable outcomes if reconstruction is required
    |
    v
resume from latest valid completed outcome
```

The recovery layer should use completed outcomes rather than reconstructing history from conversation text.

At minimum, the latest outcome provides:

- the previous semantic `result`;
- the previous `transition`;
- the complete `receipt` describing how that outcome was produced.

If the next transaction requires more history, the carrier can read prior outcomes in order.

## Causal Linkage

Timestamped filenames provide ordering but do not by themselves express causal ancestry. The outcome representation can be strengthened with minimal linkage metadata:

```json
{
  "transaction_id": "...",
  "parent_transaction_id": "...",
  "timestamp": "...",
  "result": {},
  "transition": {},
  "receipt": {}
}
```

Optional integrity linkage:

```json
{
  "outcome_sha256": "...",
  "parent_outcome_sha256": "..."
}
```

This creates an append-only causal chain while leaving each outcome independently readable.

A convenience file such as `latest_transaction.json` may point to the newest known outcome, but it should be treated only as an index. If it is absent or stale, the runtime can reconstruct the latest valid state from the immutable outcome files.

## Concurrency and Bootstrap Races

Two scripts may start at nearly the same time and both observe no live carrier. Bootstrap must therefore have a deterministic single-winner mechanism.

Acceptable approaches include:

- atomic creation of a bootstrap lock file;
- an OS file lock scoped to the runtime directory;
- binding the Unix socket as the ownership operation, with losing processes attaching to the winner after bind failure.

The design requirement is:

> At most one compatible runtime carrier becomes authoritative for a runtime endpoint/generation.

A losing bootstrap attempt should not fail the user transaction merely because another invocation successfully created the carrier first. It should attach to the winner and continue.

## Failure Boundaries

The runtime should distinguish at least these cases mechanically:

### No runtime exists

Bootstrap one and continue.

### Stale socket or stale identity metadata

Remove only the stale local endpoint/metadata and bootstrap.

### Live compatible runtime exists

Attach and continue without reconstructing state.

### Live incompatible runtime exists

Do not submit work to it. Use a generation-specific endpoint or replace/retire it according to the runtime identity policy.

### Runtime dies before transaction completion

No completed outcome should be written for that transaction. A later invocation recovers from the last completed outcome and re-enters the appropriate transaction path.

### Transaction completes but semantic result is `null`

Persist the outcome normally. `null` is a result value, not evidence of transaction failure.

## What This Design Does Not Add

This design intentionally does **not** introduce:

- a second semantic controller;
- a mutable checkpoint database;
- duplicated event logs representing the same transaction;
- a separate persisted state-machine format;
- automatic semantic reconstruction from chat history;
- PID existence as sufficient liveness evidence.

The persistent process and immutable outcomes are enough unless a concrete future requirement demonstrates otherwise.

## Relationship to the Transactional Machine

The resulting architecture is:

```text
short-lived invocation
        |
        v
ATTACH OR BOOTSTRAP
        |
        v
persistent runtime carrier
        |
        v
CREATE / REVISE / EXECUTE transaction
        |
        v
TransactionOutcome
        |
        +--> append immutable outcome JSON
        |
        v
return result to caller
```

The transaction itself remains the unit of semantic work. The runtime carrier preserves live continuity. The outcome files preserve durable continuity.

This keeps persistence orthogonal to transaction semantics while allowing the machine to survive both short-lived script invocations and loss of the live runtime process.
