# Experimental Transaction Architecture — Chat A Candidate

> STATUS: EXPERIMENTAL / TEMPORARY / NON-CANONICAL
>
> This file is a candidate design produced by one of multiple chats working in parallel. It MUST NOT be treated as a published runtime revision, MUST NOT replace files under `runtime-source/`, and MUST NOT update `runtime-bootstrap.md`. Canonical integration occurs only after the competing/parallel experimental revisions are reviewed and deliberately reconciled.

## Parallel-work protocol

Two chats are working on this architecture in parallel.

- **Chat A (this file):** develop and refine one candidate transaction architecture. Write revisions only under `experimental/transaction-architecture/` while parallel work is active.
- **Chat B (handoff recipient):** independently review the shared event record and current architecture, then develop its own candidate. It must write only to a separate file under `experimental/transaction-architecture/` (recommended: `chat-b-candidate.md`). It must not modify Chat A's candidate, `runtime-source/*`, `runtime-bootstrap.md`, the knowledge-base canonical source, or other published runtime files unless the user later explicitly authorizes canonical integration.
- Each chat may read the other candidate for comparison, but experimental differences should remain visible rather than being silently merged.
- Git commits containing only files under this experimental folder are expected during this parallel phase. They are review artifacts, not runtime publication.

## Fundamental architecture

The **Transaction** is the fundamental model↔machine interaction unit and simultaneously the semantic/deterministic execution record.

When the machine/state machine is running, the model has **one machine-facing interface only: the transaction gateway**. The model does not directly call scripts, machine methods, state methods, knowledge-base methods, or machine capabilities. Likewise, machine results return to the model through the transaction interface rather than side-channel stdout or direct mutable state objects.

Conceptually:

```text
MODEL
  |
  | transaction protocol only
  v
TRANSACTION GATEWAY
  |
  +-- state reads/transitions
  +-- knowledge-base queries
  +-- script/method execution
  +-- machine/tool capabilities
  +-- validation
  +-- persistence
  v
MACHINE / STATE MACHINE
```

## Transaction contents

A transaction should contain at minimum:

1. **Pre-execution semantic interrogatory** — purpose, intended result, requirements, constraints, assumptions, relationship to current plan, and diagnostic subquestions including enumerated classifications and decision-tree paths useful to future review.
2. **Ordered subcontract instances** — every consequential operation performed during the transaction, including semantic requests, KB queries, machine/script calls, tool/namespace calls, validation/recovery operations where applicable.
3. **Execution-order table** — mechanically generated order/phase/status/timestamps plus causal/dependency links where useful. Full subcontract data is stored once; the order table indexes it by contract-instance ID.
4. **Exact machine/tool returns** — scripts/methods populate contract-shaped JSON directly. The model does not reconstruct machine output into the contract after execution.
5. **Mechanical validation** — schema/type/required-field validation and recursive completeness checking. Canonical arrays/lists contain every returned element; canonical objects contain every returned field/value recursively. No truncation, sampling, top-N substitution, ellipsis, or semantic summarization in the canonical return/event record.
6. **Pre-exit semantic interrogatory** — semantic outcome, interpretation, objective status, failure mode/stage if any, fixes/retests/additional work indicated, plus proposed next actions.
7. **State transition record** — where applicable, state identity/version/hash before and after and the mechanically applied transition/status.
8. **Proposal lifecycle links** — model suggestions/commitments such as “I will fix X and retest Y” are captured as proposals and later linked to execution, supersession, abandonment, etc.

## Contracts inside transactions

Contracts are deterministically generated from registered definitions. A contract definition specifies field descriptions, direction, type, requiredness, source/executor binding, capture mode, validation, and exact return shape.

For machine execution, the script/method is both executor and serializer: it produces the complete schema-valid contract return JSON itself. The transaction framework validates but does not semantically reconstruct the result.

The existing `execution-contract-v1` task contract remains conceptually distinct from the higher-level transaction envelope. Transactions contain instantiated contracts/subcontracts; the new transaction concept should not merely rename the existing contract schema.

## Knowledge-base access is transactional

Knowledge-base queries use the same transaction mechanism. A KB-query subcontract records:

- exact query submitted,
- requested knowledge types/configuration,
- exact KB identity/schema/version/hash,
- complete ordered retrieval return,
- every returned knowledge record and nested value.

This provides a reviewable record of what knowledge the model asked for and what information was available when it chose its next action.

A small pinned bootstrap registry is likely required for core operations such as transaction execution, contract lookup, KB query, and event recording so KB querying does not recursively require querying the KB to learn how to query it.

## Model planning and next-action selection

The deterministic transaction machinery does **not** become the substantive planner. After a transaction closes, the model receives the closed transaction and uses its current task/plan plus available KB procedures/capabilities/heuristics/patterns to choose the next action. The model may choose to execute known knowledge, compose an operation, or query the KB again.

Thus the loop is:

```text
model plan / objective
      -> transaction
      -> closed semantic + deterministic record
      -> model interprets result
      -> model chooses next action or KB query
      -> next transaction
```

## Candidate implementation decomposition

The candidate implementation should likely introduce:

- `execution-transaction-v1` schema;
- a single model-facing `handle_transaction(...)` / transaction gateway;
- deterministic contract registry + generator;
- subcontract executor and execution-order ledger;
- recursive completeness validator;
- KB-query contract and executor;
- pre-execution semantic interrogatory contract;
- pre-exit semantic interrogatory contract;
- model proposal/commitment capture and lifecycle linkage;
- state version/hash transition capture;
- complete canonical transaction persistence;
- lossless external projection strategy for transports such as Sheets that have per-cell limits.

## Review goal

The purpose of parallel candidates is to expose alternative designs before canonical integration. Review should compare the candidates for correctness, minimality, deterministic enforceability, recursion boundaries, state-machine coupling, provenance fidelity, and migration cost. Do not publish a winner merely because one chat wrote first.
