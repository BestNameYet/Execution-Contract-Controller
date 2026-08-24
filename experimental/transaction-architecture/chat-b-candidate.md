# Experimental Transaction Architecture — Chat B Candidate

> STATUS: EXPERIMENTAL / TEMPORARY / NON-CANONICAL
>
> This file is an independently developed candidate produced during the parallel transaction-architecture phase. It MUST NOT be treated as the active runtime, MUST NOT modify or replace `runtime-source/*`, `runtime-bootstrap.md`, the canonical knowledge-base source, or Chat A's candidate, and MUST NOT be promoted without explicit user authorization after candidate review.

## Parallel-work boundary

- **Chat A:** owns `experimental/transaction-architecture/chat-a-candidate.md`.
- **Chat B (this file):** owns `experimental/transaction-architecture/chat-b-candidate.md`.
- Both candidates may read each other and the shared Events ledger.
- Differences remain explicit; neither candidate silently absorbs the other.
- Canonical integration is a later, separately authorized operation.

## Core architectural position

The **Transaction** is the exclusive model↔machine interface, but the canonical transaction record should **not** be represented as one ever-growing nested object containing every subordinate object inline.

Instead, a transaction is a stable identity over an **immutable ordered stream of typed frames**. The stream is the combined semantic/deterministic execution record. The current transaction view is a deterministic materialization of those frames.

Conceptually:

```text
MODEL
  |
  | transaction requests / transaction responses only
  v
TRANSACTION KERNEL
  |
  +-- append typed frame
  +-- validate frame contract
  +-- execute registered machine operation
  +-- request semantic decision
  +-- read/write state through declared state operations
  +-- query KB through declared KB operation
  +-- persist frame before exposure to next step
  v
APPEND-ONLY TRANSACTION LOG
  |
  +-- deterministic materialized transaction view
  +-- Sheets/event projection
  +-- external artifact references
```

This makes the **append-only frame log** authoritative and makes larger derived transaction objects projections rather than the primary persistence structure.

## Deliberate difference from Chat A

Chat A's candidate describes a canonical transaction containing ordered subcontract instances, exact machine/tool returns, execution-order tables, semantic interrogatories, proposal links, and state transitions as components of the transaction object.

This candidate agrees with the information requirements but changes the persistence form:

- canonical authority = immutable frame sequence;
- transaction object = deterministic projection/materialized view;
- each consequential semantic or deterministic interaction = one or more typed frames;
- large external artifacts are referenced, not copied into the transaction state;
- no frame may recursively embed the transaction log or materialized transaction view.

This is intended to reduce recursion risk, duplication, mutation ambiguity, and state-object growth while retaining complete provenance.

## Exclusive interface invariant

While the transaction runtime is active, the model has no direct machine-facing interfaces other than the transaction gateway.

The model may not directly invoke:

- state reads or writes;
- KB queries;
- scripts;
- controller methods;
- filesystem mutations;
- connected tool/capability operations;
- validation/recovery functions.

Instead the model submits a typed transaction request. The kernel either:

1. resolves it deterministically to a registered operation;
2. emits a semantic request frame when judgment is required; or
3. returns a typed protocol/authorization/availability failure.

Machine results re-enter model context only through transaction response frames.

## Transaction identity

Every transaction has a stable immutable header:

```json
{
  "schema": "execution-transaction-v1",
  "transaction_id": "txn_<id>",
  "turn_id": "turn_<id>",
  "parent_transaction_id": null,
  "objective_ref": "...",
  "created_at": "...",
  "runtime_identity": {
    "repository": "...",
    "runtime_commit": "...",
    "kb_identity": "...",
    "contract_registry_hash": "..."
  }
}
```

The header is written once. All subsequent information is appended as frames keyed to `transaction_id`.

## Frame model

Each frame has a common deterministic envelope:

```json
{
  "frame_schema": "transaction-frame-v1",
  "transaction_id": "txn_<id>",
  "sequence": 17,
  "frame_id": "frm_<id>",
  "parent_frame_id": "frm_<id>",
  "phase": "PRE_EXECUTION|EXECUTION|POST_EXECUTION|CLOSE",
  "kind": "...",
  "contract_id": "...",
  "contract_version": 1,
  "timestamp_started": "...",
  "timestamp_completed": "...",
  "payload": {},
  "validation": {
    "schema_valid": true,
    "complete": true
  }
}
```

`sequence` is assigned mechanically by the kernel and is monotonically increasing within the transaction. The frame is immutable after append.

## Required frame kinds

The initial registry should define at least:

- `TRANSACTION_OPEN`
- `PRE_EXECUTION_SEMANTIC_REQUEST`
- `PRE_EXECUTION_SEMANTIC_RESULT`
- `KB_QUERY_REQUEST`
- `KB_QUERY_RESULT`
- `STATE_READ_REQUEST`
- `STATE_READ_RESULT`
- `STATE_TRANSITION_REQUEST`
- `STATE_TRANSITION_RESULT`
- `MACHINE_OPERATION_REQUEST`
- `MACHINE_OPERATION_RESULT`
- `VALIDATION_RESULT`
- `RECOVERY_DECISION`
- `PROPOSAL_CREATED`
- `PROPOSAL_STATUS_CHANGED`
- `POST_EXECUTION_SEMANTIC_REQUEST`
- `POST_EXECUTION_SEMANTIC_RESULT`
- `NEXT_ACTION_PROPOSAL`
- `TRANSACTION_CLOSE`

Additional frame kinds are registered rather than improvised.

## Deterministic contract registry

Each frame kind is bound to a deterministic contract definition stored in a pinned registry. A contract definition contains:

- exact schema/version;
- required and optional fields;
- field types;
- semantic meaning of fields and enum values;
- producer binding;
- consumer binding;
- validation rule;
- capture rule;
- artifact policy;
- allowed next frame classes;
- terminal/continuation semantics.

The kernel generates concrete request/response contracts from this registry. The model does not invent transport shapes.

The registry is bootstrap-critical and therefore must be retrievable without a KB lookup.

## Semantic frames

Semantic judgment remains explicit and bounded.

A semantic request frame must include:

- the exact semantic question;
- the closed output schema;
- all definitions required to classify/select correctly;
- only the state/KB/context needed for that judgment;
- references to governing objective/constraints;
- no hidden machine state.

The semantic result frame contains exactly the returned structured result plus deterministic validation metadata.

Semantic output never directly mutates state. It can only propose/select a transition that a later deterministic operation frame validates and executes.

## Pre-execution semantic interrogation

Before a materially new operation, the transaction may require a pre-execution semantic frame set describing:

- intended objective;
- selected action;
- relationship to current plan;
- relevant requirements/prohibitions;
- whether the operation is direct or support work;
- assumptions actually relied upon;
- expected observable effect;
- failure/recovery branches that require semantic judgment.

This should be a registered contract, not free-form prose.

For already closed deterministic procedures, the kernel should not recursively demand semantic interrogation for each internal deterministic step unless the procedure definition marks a semantic decision point.

## Machine-operation frames

Every machine action passes through a registered machine contract.

The machine executor must produce the response payload directly in contract shape. The model does not reserialize the result after execution.

A machine result frame records:

- operation identity;
- arguments actually used;
- authorization scope/reference;
- success/failure status;
- exact structured return needed for future reconstruction;
- resulting machine/state identity where applicable;
- bounded stdout/stderr only when stdout/stderr are themselves semantically relevant outputs;
- artifact references for external files.

## Artifact policy: references, not file warehousing

The transaction log records **events and machine facts**, not copies of every file created during execution.

If an operation creates or reads a file, the canonical frame may contain:

```json
{
  "artifact": {
    "artifact_id": "art_<id>",
    "role": "diagnostic_snapshot",
    "path_or_uri": "/home/oai/share/example.json",
    "sha256": "...",
    "size_bytes": 1234,
    "mime_type": "application/json"
  }
}
```

It MUST NOT automatically inline the complete file contents.

Inline payload content is allowed only when the content itself is the direct machine return required by the registered contract and remains within a declared bounded size. Otherwise the frame stores a content-addressed reference.

Creating four diagnostic files does not necessarily create four transaction events. Events correspond to consequential operations; artifact references are evidence attached to those operation results.

## Lossless completeness without uncontrolled embedding

"Complete" means the canonical record contains all information required by the registered contract, not that every reachable external byte is recursively embedded.

Completeness validation therefore distinguishes:

1. **contract completeness** — every required field/value in the frame is present;
2. **collection completeness** — returned arrays/objects governed by the contract are not silently truncated;
3. **artifact completeness** — external artifact references include required identity/hash/size/location metadata;
4. **transaction completeness** — required frame classes and phase transitions are present before close.

No ellipsis, top-N substitution, or semantic summary may replace a canonical collection when the contract requires the full collection.

## State model

State is only accessed through transaction state operations.

State transitions are event-sourced:

```text
state version N
  + validated STATE_TRANSITION_RESULT frame
  -> state version N+1
```

A state transition result records:

- prior version/hash;
- transition operation;
- exact delta or deterministic transition parameters;
- resulting version/hash;
- transition status.

The current state object is a projection/materialization of accepted state-transition frames, not an independently authoritative mutable record.

Large external artifacts are never absorbed into state merely because a path references them.

## Knowledge-base access

KB access is exclusively transactional.

A KB query request records:

- exact query text;
- requested types;
- retrieval parameters;
- current KB identity/schema/version/hash;
- caller objective/predicate reference where relevant.

The KB result records the complete ordered records actually returned by retrieval, because those records are the information presented to the model for decision-making.

This is different from file artifacts: KB records are semantic machine output and therefore belong in the transaction record unless the KB contract explicitly uses content-addressed record references with guaranteed immutable resolution.

## Proposal lifecycle

Model statements that imply future work are represented as explicit proposal frames rather than inferred later from prose.

Example lifecycle:

```text
PROPOSAL_CREATED
      |
      +--> EXECUTED
      +--> SUPERSEDED
      +--> ABANDONED
      +--> BLOCKED
```

A later status frame references the proposal ID and the transaction/frame that resolved it. This allows later analysis of whether proposed fixes/retests actually occurred.

## Post-execution semantic interrogation

Before close, when semantic interpretation is needed, a post-execution semantic contract may classify:

- whether the transaction objective was achieved;
- semantic meaning of machine evidence;
- failure mode/stage;
- unresolved requirements;
- whether recovery is indicated;
- candidate next actions.

The deterministic kernel does not itself choose substantive next work unless a registered closed procedure already determines the next step.

## Model agency between transactions

After `TRANSACTION_CLOSE`, the model receives the closed transaction projection and may:

- choose the next direct operation;
- invoke a known KB procedure/capability through another transaction;
- request another KB query;
- stop when the governing objective is satisfied.

Thus the transaction kernel governs the interface and record, while the model retains semantic planning authority where judgment is required.

## Transaction close conditions

A transaction may close only when deterministic validation proves:

- sequence continuity;
- required phase frames present;
- all required contracts schema-valid;
- no unresolved in-transaction machine operation;
- state transition receipts complete where state changed;
- artifact references valid under their declared policy;
- semantic result frames validated where semantic frames were required;
- close status explicitly one of `COMPLETE`, `FAILED`, `BLOCKED`, `CANCELLED`.

Closure does not require that the user's overall task be complete. It only closes that model↔machine interaction unit.

## Recovery and idempotency

Every externally mutating operation must carry an idempotency key derived from transaction/frame identity or a registered operation key.

If the process crashes after the external mutation but before recording its result, recovery must first determine whether the operation already committed before issuing a duplicate mutation.

Recovery frames record:

- observed persisted state;
- prior operation/idempotency identity;
- deterministic recovery classification where possible;
- semantic recovery decision only when deterministic evidence is insufficient.

## Concurrency

The kernel should reject ambiguous concurrent mutation of one transaction stream.

Recommended rule:

- one writer per transaction ID;
- optimistic expected-sequence check on append;
- append succeeds only if `expected_previous_sequence == current_sequence`;
- independent transactions may execute concurrently when their registered state/resource scopes permit it.

State mutations additionally use expected state version/hash preconditions.

## Persistence

Canonical persistence should be an append-only JSONL or equivalent row/object event store, one frame per record.

The materialized transaction view is regenerable by replaying frames for `transaction_id` in sequence order.

This removes the need for an enormous nested state object whose historical contents are recopied on every append.

## Sheets projection

Google Sheets is a projection/analysis surface, not the sole authority.

A frame projects to one or more bounded Sheets rows. If a canonical payload exceeds per-cell limits:

- store the complete canonical payload in the durable event/artifact store;
- place immutable content hash/reference in Sheets;
- optionally store structured summary/index columns for analysis;
- never truncate the canonical source merely to fit Sheets.

The Sheets projection cursor is acknowledged only after the projection succeeds.

## Minimal bootstrap surface

The bootstrap-critical deterministic kernel should expose only a small fixed set of primitives:

- `OPEN_TRANSACTION`
- `APPEND_FRAME`
- `GET_TRANSACTION`
- `GET_STATE`
- `EXECUTE_REGISTERED_CONTRACT`
- `QUERY_KB`
- `CLOSE_TRANSACTION`
- `PROJECT_EVENTS`

Higher-level capabilities are registered contracts invoked through these primitives.

## Candidate implementation decomposition

A later canonical implementation could separate:

- `transaction_kernel.py` — exclusive gateway, sequence, lifecycle, append/close rules;
- `transaction_contract_registry.json` — pinned contract definitions;
- `transaction_store.py` — append-only frame persistence + materialization;
- `transaction_executor.py` — registered deterministic operation execution;
- `transaction_semantic.py` — construction/validation of semantic request/result frames;
- `transaction_artifacts.py` — immutable artifact identity/reference policy;
- `transaction_projection.py` — Sheets/external projections;
- existing controller logic — initially adapted behind registered transaction contracts rather than immediately rewritten.

This decomposition is conceptual only during the parallel phase; this candidate does not authorize creation or modification of canonical runtime files.

## Migration approach

A low-risk migration can preserve the current execution controller while placing it behind the transaction gateway:

1. introduce experimental transaction schemas/store/kernel;
2. wrap current controller invocation as a registered machine contract;
3. route KB retrieval through a KB-query frame contract;
4. route existing carrier event persistence into transaction frames;
5. make state access transactional;
6. move Sheets recording to frame projection;
7. only then decide whether current controller/carrier abstractions should be collapsed or replaced.

This avoids requiring a simultaneous rewrite of the existing execution-contract controller and the new machine interface.

## Review questions for reconciliation

The candidate comparison should explicitly resolve:

- canonical persistence form: self-contained transaction object vs immutable frame stream;
- whether full machine returns live inline or use bounded payload + immutable artifact reference;
- whether state is independently authoritative or a projection of state-transition frames;
- transaction nesting/subtransaction semantics;
- exact semantic interrogation boundaries;
- recovery/idempotency contract;
- concurrency rules;
- projection strategy for Sheets limits;
- migration boundary around the existing execution controller.

The final architecture may combine ideas from both candidates, but those choices should be explicit during reconciliation rather than silently merged during parallel development.
