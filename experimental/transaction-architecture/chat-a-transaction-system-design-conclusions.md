# Chat A — Transaction System Design Conclusions

> STATUS: EXPERIMENTAL / TEMPORARY / NON-CANONICAL
>
> This document is a detailed, untruncated architecture write-up from Chat A. It is stored under `experimental/transaction-architecture/` for comparison and reconciliation with the independent Chat B candidate. It does not authorize or modify canonical runtime files, `runtime-source/*`, `runtime-bootstrap.md`, or the canonical knowledge-base source.

## Purpose

This document records the conclusions developed for the proposed Transaction architecture and expands the design into an implementation-oriented form. The principal architectural decision is that the **Transaction becomes the fundamental model↔machine interaction unit, the exclusive model-facing machine interface, and the canonical semantic/deterministic record of execution**.

The Transaction sits above the existing execution-contract concept. A transaction may contain multiple instantiated contracts/subcontracts and semantic decision points. It is not merely a rename of the current execution contract.

---

## 1. The Transaction is the fundamental interaction unit

Every consequential model↔machine interaction is mediated by a Transaction.

The model does not directly call machine methods, scripts, state functions, knowledge-base functions, filesystem operations, tool namespaces, validation functions, or other execution capabilities while the transaction runtime is active. All such access is mediated through the Transaction gateway.

Conceptually:

```text
MODEL
  |
  | transaction requests / transaction responses only
  v
TRANSACTION INTERFACE / KERNEL
  |
  +-- state reads and state transitions
  +-- knowledge-base queries
  +-- script and method execution
  +-- filesystem/tool/capability execution
  +-- deterministic validation
  +-- semantic interrogatories
  +-- persistence and event recording
  v
MACHINE / STATE MACHINE / KB / TOOLS
```

The interface is symmetric: machine results return to the model through the same Transaction boundary. Direct side-channel exposure of raw machine state, script return values, or mutable state objects to the model should not be part of the architecture.

---

## 2. The Transaction object is both protocol and record

The Transaction should not be an audit object reconstructed after execution. It is the protocol object through which execution actually occurs.

This yields a strong audit invariant:

> If a machine operation is not represented in the transaction/subcontract history, the model did not perform that operation through the governed machine interface.

The same object family therefore carries both execution requests and the resulting semantic/deterministic history.

A typical transaction lifecycle is:

```text
TRANSACTION OPEN
      |
      v
PRE-EXECUTION SEMANTIC INTERROGATORY
      |
      v
RESOLVE / GENERATE REQUIRED CONTRACTS
      |
      v
EXECUTE ORDERED SUBCONTRACTS
      |
      v
CAPTURE EXACT MACHINE RETURNS
      |
      v
DETERMINISTIC VALIDATION
      |
      v
PRE-EXIT / POST-EXECUTION SEMANTIC INTERROGATORY
      |
      v
DETERMINISTIC TRANSACTION CLOSURE
      |
      v
TRANSACTION CLOSED
      |
      v
CLOSED TRANSACTION EXPOSED TO MODEL
```

---

## 3. Semantic state and deterministic state must both be preserved

A major purpose of the architecture is to preserve two different kinds of truth without allowing one to overwrite the other.

### Semantic truth

The semantic record captures what the model believed, intended, classified, interpreted, and proposed. Examples include:

- purpose of the transaction;
- intended result;
- relationship to the current plan;
- requirements and constraints recognized by the model;
- assumptions actually relied upon;
- diagnostic classifications;
- interpretation of machine evidence;
- failure-mode assessment;
- objective-status assessment;
- suggested fixes or retests;
- proposed next actions;
- statements of intended future execution.

### Deterministic truth

The deterministic record captures what actually happened in the machine. Examples include:

- state identity/version before execution;
- exact subcontract/contract identities;
- exact machine methods invoked;
- exact arguments used;
- execution order and causal/dependency information;
- exact structured machine returns;
- success/failure status;
- mechanical validation results;
- state-transition receipts;
- state identity/version after execution;
- persistence receipts.

The semantic interpretation may reference deterministic evidence, but it must never replace or rewrite that evidence.

A useful top-level conceptual split is:

```json
{
  "semantic": {
    "pre_execution": {},
    "post_execution": {},
    "proposed_next_actions": []
  },
  "deterministic": {
    "state_before": {},
    "subcontracts": {},
    "execution_order": [],
    "validation": {},
    "state_transition": {},
    "state_after": {}
  }
}
```

The exact persistence form remains subject to reconciliation with Chat B's immutable-frame-stream proposal, but the information separation is required regardless of persistence representation.

---

## 4. Pre-execution semantic interrogation is required before materially new execution

Before a materially new model-selected operation executes, the transaction should capture a structured semantic interrogation of the intended operation.

The purpose is not to create procedural delay. The purpose is to record the semantic decision inputs that explain why the machine operation is being requested.

The pre-execution semantic contract should be versioned and schema constrained. It can include:

- immediate purpose;
- intended result;
- governing objective;
- relationship to the current plan;
- explicit requirements;
- constraints/prohibitions;
- assumptions relied upon;
- whether the action is a direct target, required dependency, follow-up, recovery, etc.;
- expected observable effect;
- diagnostic categories;
- decision-tree subquestions when useful for later review.

Example:

```json
{
  "purpose": {
    "question": "What is this transaction intended to accomplish?",
    "answer": "Establish why the rsync peer is unreachable before another transfer attempt."
  },
  "purpose_category": {
    "question": "Which category best describes the immediate purpose?",
    "answer": "DISCOVERY"
  },
  "relationship_to_objective": {
    "question": "How does this operation relate to the governing objective?",
    "answer": "REQUIRED_DEPENDENCY"
  },
  "categorization_basis": {
    "question": "What property of the proposed operation produced that classification?",
    "answer": "The transfer cannot be retried meaningfully until the peer transport path is identified."
  }
}
```

Decision-tree diagnostics should record both answers and the path traversed, not merely the final classification.

Example:

```json
{
  "answers": {
    "D1": false,
    "D2": false
  },
  "decision_path": [
    "D1:false",
    "D2:false"
  ],
  "classification": "REQUIRED_DEPENDENCY"
}
```

The question definitions themselves should be versioned/hashed because changes in wording or category definitions can change semantic outputs over time.

---

## 5. Contracts inside transactions are generated deterministically

Execution contracts should be generated from registered definitions rather than composed ad hoc by the model.

A contract definition should specify, for each field:

- field name;
- description;
- direction (`input`, `output`, or derived metadata);
- type;
- requiredness;
- source/executor binding;
- capture mode;
- validation rule;
- encoder/serializer when needed;
- dependency/order information where applicable.

A deterministic registry entry can look conceptually like:

```python
CONTRACTS = {
    "rsync.sync_test": {
        "version": 1,
        "fields": {
            "hostname": {
                "description": "Hostname of executing machine",
                "type": "string",
                "required": True,
                "executor": {
                    "kind": "script_method",
                    "script": "network_probe",
                    "method": "get_hostname"
                }
            },
            "routes": {
                "description": "Complete routing table visible to machine",
                "type": "array",
                "required": True,
                "executor": {
                    "kind": "script_method",
                    "script": "network_probe",
                    "method": "get_routes"
                }
            },
            "neighbors": {
                "description": "Complete neighbor table",
                "type": "array",
                "required": True,
                "executor": {
                    "kind": "script_method",
                    "script": "network_probe",
                    "method": "get_neighbors"
                }
            },
            "rsync_result": {
                "description": "Complete result of rsync test",
                "type": "object",
                "required": True,
                "executor": {
                    "kind": "script_method",
                    "script": "network_probe",
                    "method": "run_rsync_test"
                }
            }
        }
    }
}
```

A generator should create a concrete executable contract deterministically:

```python
def generate_contract(contract_id):
    definition = CONTRACTS[contract_id]
    return {
        "contract_id": contract_id,
        "contract_version": definition["version"],
        "header": definition["fields"],
        "output_schema": build_output_schema(definition["fields"])
    }
```

The model may select which registered capability/procedure it wants to invoke, but it should not invent the machine return shape or executor bindings.

---

## 6. The machine executor is also the serializer

For deterministic machine execution, the script/method itself should populate and return the contract-shaped JSON object.

The required path is:

```text
machine method return
       |
       v
script/executor
       |
       v
contract-shaped JSON
       |
       v
deterministic validator
```

The model should not receive an arbitrary raw machine object and then reconstruct it into the contract afterward.

A generic executor could resemble:

```python
def execute_contract(contract, inputs):
    result = {}

    for field_name, field in contract["header"].items():
        executor = resolve_executor(field["executor"])
        raw_value = executor(**inputs)
        result[field_name] = to_json_value(raw_value)

    validate_contract_result(contract, result)
    return result
```

Non-JSON-native values require deterministic registered encoders. If no lossless encoder exists for a required value, the contract should fail closed instead of silently dropping or stringifying the value in an uncontrolled way.

Sets or other unordered collections should use a declared canonical ordering rule when the contract requires reproducibility.

---

## 7. Canonical contract returns must be complete

For values governed by the machine-return contract:

- arrays/lists contain every returned member;
- objects contain every returned field/value recursively;
- nested values are preserved recursively;
- no semantic summary substitutes for the machine value;
- no ellipsis substitutes for omitted content;
- no top-N reduction may occur after retrieval unless the contract itself explicitly defines the return as top-N;
- no silent sampling occurs in canonical persistence.

A recursive completeness validator can be implemented along these lines:

```python
def assert_complete_copy(source, output):
    if isinstance(source, dict):
        assert isinstance(output, dict)
        assert set(source.keys()) == set(output.keys())
        for key in source:
            assert_complete_copy(source[key], output[key])

    elif isinstance(source, (list, tuple)):
        assert isinstance(output, list)
        assert len(source) == len(output)
        for source_item, output_item in zip(source, output):
            assert_complete_copy(source_item, output_item)

    else:
        assert source == output
```

This requirement applies to canonical contract returns. It does not imply that every external file referenced by a return must be recursively copied into every transaction object. Files can be represented by immutable content-addressed artifact records when the contract defines the artifact itself, rather than its bytes, as the return.

This distinction is important in reconciliation with Chat B's artifact-reference proposal.

---

## 8. Mutation/non-returning methods require explicit execution receipts

A machine mutation should not produce an empty or semantically reconstructed result.

The deterministic method should return a structured mutation receipt, including a machine-generated narrative where useful.

Example:

```json
{
  "succeeded": true,
  "operation": "CREATE",
  "target": "/home/oai/share/test.json",
  "narrative": "Created /home/oai/share/test.json and wrote the supplied object.",
  "receipt": {
    "bytes_written": 4821,
    "sha256": "..."
  }
}
```

The narrative should be generated from execution evidence, not fabricated by the semantic model after the fact.

---

## 9. Every transaction contains the complete set of subcontracts actually performed

A transaction should retain every instantiated contract/subcontract that actually executed during the transaction.

A clean representation can separate:

```text
subcontracts
    = complete instantiated contract records and returns

execution_order
    = lightweight deterministic order/index/causal ledger
```

This prevents unnecessary copying of large result objects into the ordering table.

A subcontract instance should preserve provenance such as:

```json
{
  "contract_instance_id": "ctr_002",
  "contract_id": "network.rsync_test",
  "contract_version": 3,
  "header": {},
  "inputs": {},
  "executor": {
    "kind": "script_method",
    "component": "network_probe.py",
    "method": "run_rsync_test",
    "component_sha256": "..."
  },
  "return": {},
  "validation": {
    "schema_valid": true,
    "complete_capture_valid": true
  }
}
```

The execution-order ledger should be generated mechanically at dispatch time and should not be reconstructed by the model after completion.

Recommended order/causal metadata includes:

```json
{
  "ordinal": 7,
  "execution_group": 4,
  "contract_instance_id": "ctr_007",
  "phase": "KNOWLEDGE_QUERY",
  "parent_contract_instance_id": "ctr_005",
  "triggered_by": "ctr_005",
  "depends_on": [
    "ctr_004",
    "ctr_005"
  ],
  "started_at": "...",
  "completed_at": "...",
  "status": "COMPLETE"
}
```

Temporal adjacency must not be treated as causality. If parallel execution is permitted, `ordinal` alone is insufficient; `execution_group` and explicit dependencies are needed.

Retries should normally become distinct contract instances linked by `retry_of`, rather than mutating one historical attempt in place.

---

## 10. Knowledge-base access is itself transactional

A KB query is a machine interaction and must use the same contract procedure.

The query transaction/subcontract should preserve:

- exact query text;
- exact requested knowledge-record types;
- retrieval configuration;
- exact KB identity/schema/version/hash;
- complete ordered return from retrieval;
- complete knowledge records actually presented to the model.

Conceptual invocation:

```python
transact(
    "knowledge.query",
    {
        "query": "machine execution contract for an rsync diagnostic transaction",
        "requested_types": ["action", "procedure", "capability"],
        "top_k": 8
    }
)
```

Conceptual contract definition:

```json
{
  "contract_id": "knowledge.query",
  "version": 1,
  "executor": {
    "kind": "script_method",
    "script": "execution_contract_controller",
    "method": "search_knowledge"
  },
  "header": {
    "query": {
      "description": "Exact natural-language query submitted to the execution knowledge base.",
      "direction": "input",
      "type": "string"
    },
    "requested_types": {
      "description": "Knowledge-record classes requested from retrieval.",
      "direction": "input",
      "type": "array"
    },
    "top_k": {
      "description": "Maximum number of primary retrieval results requested.",
      "direction": "input",
      "type": "integer"
    },
    "knowledge_base_identity": {
      "description": "Exact knowledge-base schema, version, and published identity used for retrieval.",
      "direction": "output",
      "type": "object"
    },
    "results": {
      "description": "Complete ordered result returned by the knowledge-base retrieval method.",
      "direction": "output",
      "type": "array"
    }
  }
}
```

The key audit property is that later review can determine exactly what execution knowledge the model requested and exactly what records it received before choosing an action.

---

## 11. The KB is an execution repertoire, not the substantive planner

This was a critical architectural correction.

The deterministic transaction kernel should not choose the next substantive action merely because it can retrieve capabilities or evaluate closure state.

After a transaction closes, the model receives:

- current objective/task state;
- current plan;
- complete result of the last closed transaction;
- currently available/retrieved KB knowledge that remains applicable.

The model then semantically decides what it needs next.

The loop is:

```text
CURRENT OBJECTIVE / MODEL PLAN
          |
          v
model selects what information/action it needs
          |
          v
TRANSACTION N
    pre-execution semantic interrogation
    contract/subcontract execution
    KB query if applicable
    machine execution
    deterministic validation
    pre-exit semantic interrogation
          |
          v
TRANSACTION N CLOSED
          |
          v
complete transaction result exposed to model
          |
          v
MODEL DELIBERATION
    What did this establish?
    What remains unresolved?
    What KB knowledge/capabilities are available?
    Is another KB query needed?
    Which capability/procedure/action should be used next?
          |
          v
model selects NEXT ACTION
          |
          v
deterministic system resolves selected KB record / operation
and generates its contract
          |
          v
TRANSACTION N+1
```

A model next-action selection can be structured as:

```json
{
  "next_action": {
    "selection_type": "PROCEDURE",
    "knowledge_id": "procedure.rsync.peer_diagnostic",
    "purpose": "Determine why the peer cannot be reached before retrying rsync.",
    "arguments": {
      "peer": "172.26.36.59"
    }
  }
}
```

The deterministic system then answers mechanical questions only:

```text
Does the referenced KB record exist?
        |
Is it the referenced capability/procedure type?
        |
Are required arguments present?
        |
Generate the corresponding contract deterministically
        |
Open the next transaction
```

The deterministic system should not substitute another action because it believes another procedure would be strategically better. That remains semantic planning authority.

---

## 12. Transaction closure status must remain narrow

The transaction kernel should determine whether the transaction itself closed validly. It should not use closure status as a hidden next-action planner.

Useful deterministic closure states include:

- `VALID_COMPLETE`;
- `INVALID_RETURN`;
- `EXECUTION_FAILED`;
- `VALIDATION_FAILED`;
- potentially `BLOCKED` / `CANCELLED` where explicitly defined.

For example:

```python
if not mechanical_validation["schema_valid"]:
    transaction_status = "INVALID_RETURN"
elif not execution["succeeded"]:
    transaction_status = "EXECUTION_FAILED"
else:
    transaction_status = "VALID_COMPLETE"
```

Semantic findings such as:

- a fix appears useful;
- a retest appears useful;
- another method may be preferable;
- continuation is indicated;

belong in semantic output/proposal fields. They are not deterministic execution commands unless the model later selects them or a registered closed deterministic procedure explicitly defines that continuation internally.

---

## 13. Pre-exit / post-execution semantic interrogation captures interpretation and proposals

After deterministic execution and validation but before closure, the model can be asked a structured semantic interrogation about what the evidence means.

Candidate fields include:

```json
{
  "outcome": {
    "question": "What happened as a result of the executed transaction?",
    "type": "string"
  },
  "objective_status": {
    "question": "What is the semantic relationship between the result and the transaction's stated purpose?",
    "type": "enum",
    "values": [
      "ACHIEVED",
      "PARTIALLY_ACHIEVED",
      "NOT_ACHIEVED",
      "INDETERMINATE"
    ]
  },
  "interpretation": {
    "question": "What does the returned evidence mean in the context of the current objective?",
    "type": "string"
  },
  "failure": {
    "question": "Did a meaningful failure occur?",
    "type": "object",
    "fields": {
      "occurred": {"type": "boolean"},
      "failure_mode": {
        "type": "enum",
        "values": [
          "NONE",
          "INPUT_FAILURE",
          "METHOD_FAILURE",
          "CONNECTIVITY_FAILURE",
          "PERMISSION_FAILURE",
          "VALIDATION_FAILURE",
          "DEPENDENCY_FAILURE",
          "SEMANTIC_MISMATCH",
          "TARGET_NOT_ACHIEVED",
          "UNKNOWN"
        ]
      },
      "failure_description": {"type": "string"},
      "failure_stage": {
        "type": "enum",
        "values": [
          "PRE_EXECUTION",
          "EXECUTION",
          "VALIDATION",
          "RESULT_INTERPRETATION"
        ]
      }
    }
  }
}
```

The post-execution semantic interrogation should also explicitly capture proposed future work.

---

## 14. Model suggestions, promises, and proposed fixes must be first-class records

A recurring behavior of interest is that a model often says what it intends to do next, e.g.:

> "I'll restart the receiver using IPv4 and then rerun the peer test."

Those statements should not remain buried in prose. They should become explicit structured proposals.

Example:

```json
{
  "proposed_next_actions": [
    {
      "proposal_id": "proposal_001",
      "ordinal": 1,
      "action_type": "FIX",
      "description": "Restart the receiver with explicit IPv4 binding.",
      "purpose": "Restore IPv4 reachability on port 873.",
      "basis": "The completed transaction found an IPv6-only listener.",
      "commitment": "INTENDS_TO_EXECUTE",
      "timing": "NEXT_ACTION"
    },
    {
      "proposal_id": "proposal_002",
      "ordinal": 2,
      "action_type": "RETEST",
      "description": "Repeat peer connectivity test.",
      "depends_on": ["proposal_001"],
      "commitment": "INTENDS_TO_EXECUTE"
    }
  ]
}
```

Later transactions update the proposal lifecycle mechanically:

```text
PROPOSED
   +--> EXECUTED
   +--> SUPERSEDED
   +--> ABANDONED
   +--> BLOCKED
```

Example execution linkage:

```json
{
  "proposal_id": "proposal_001",
  "status": "EXECUTED",
  "executed_by_transaction_id": "txn_0094"
}
```

Example supersession:

```json
{
  "proposal_id": "proposal_001",
  "status": "SUPERSEDED",
  "superseded_by_proposal_id": "proposal_003",
  "reason": "A subsequent KB query exposed a more appropriate procedure."
}
```

This directly exposes **intent-to-execution divergence**. Future analysis can determine whether the model identified a correct fix but failed to execute it, repeatedly promised the same action, changed strategy after new evidence, or followed through immediately.

Three separate sequences should remain distinguishable:

```text
subcontract_execution_order
    = what actually happened inside a transaction

proposed_next_actions
    = what the model said should happen afterward

subsequent_transaction_links
    = what actually happened afterward
```

---

## 15. State-machine access itself is transactional

The model should not hold or mutate the state machine directly.

State reads and state changes are ordinary transaction-mediated operations.

A state read could conceptually return:

```json
{
  "state_version": 193,
  "active_objective": "...",
  "open_transactions": [],
  "pending_proposals": [],
  "known_results": []
}
```

A state transition request might be:

```json
{
  "transaction_type": "STATE_TRANSITION",
  "requested_transition": {
    "type": "SELECT_NEXT_ACTION",
    "knowledge_id": "procedure.rsync.peer_diagnostic",
    "arguments": {
      "peer": "172.26.36.59"
    }
  }
}
```

Every state-changing transaction should record before/after identity:

```json
{
  "state_access": {
    "state_version_before": 193,
    "state_sha256_before": "...",
    "requested_transition": {},
    "transition_applied": true,
    "state_version_after": 194,
    "state_sha256_after": "..."
  }
}
```

This makes the transaction the causal edge between two machine states:

```text
STATE 193
   |
   | transaction txn_0087
   v
STATE 194
```

The transaction stream can therefore reconstruct state evolution.

Chat B proposes taking this farther by making state itself a deterministic materialization of accepted state-transition frames. That is a strong candidate for reconciliation because it removes ambiguity about whether an independently mutable state object or the event stream is authoritative.

---

## 16. Waiting can be an active transaction state rather than an end-of-turn condition

For inter-agent communication, a transaction should be able to execute a blocking wait contract rather than necessarily terminating the model turn.

The critical distinction is:

```text
WAIT != END TURN
WAIT = active blocked transaction state
```

A `coordination.message.wait` contract could look like:

```json
{
  "contract_id": "coordination.message.wait",
  "inputs": {
    "agent_id": "chat_a",
    "after_sequence": 41,
    "sender_filter": "chat_b",
    "correlation_id": "discussion_17"
  },
  "return": {
    "message": {
      "message_id": "msg_42",
      "sequence": 42,
      "sender": "chat_b",
      "recipient": "chat_a",
      "correlation_id": "discussion_17",
      "payload": {}
    }
  }
}
```

The machine implementation can block on a socket/event/condition variable until a matching message arrives, then return the message through the transaction interface.

An open transaction can therefore suspend:

```text
Transaction 81
    subcontract 1: KB query
    subcontract 2: formulate proposal
    subcontract 3: MESSAGE_SEND to Chat B
    subcontract 4: WAIT_FOR_MESSAGE
                         |
                         v
                 TRANSACTION SUSPENDED
                         |
                    B responds
                         |
                         v
                 wait contract returns
                         |
                         v
                 semantic evaluation
                         |
                         v
                 transaction continues
```

A state such as `SUSPENDED_WAITING` is therefore not an execution failure.

If the host imposes maximum tool-call duration, the wait can be renewable by returning a non-failure timeout status and immediately issuing another wait while the turn remains active.

Deadlock should be detectable. If both agents are waiting for each other and there are no deliverable messages, the coordination subsystem can surface `COMMUNICATION_DEADLOCK` rather than silently blocking forever.

---

## 17. Inter-chat messaging fits under the Transaction architecture, but transport is a separate infrastructure problem

Once a cross-runtime transport/shared carrier exists, coordination operations become normal transaction-mediated capabilities such as:

```text
coordination.message.send
coordination.message.wait
coordination.messages.get
coordination.view.get
coordination.view.update
```

The architecture should preserve both:

```text
immutable communication history
        +
current mutable collaborative state
```

The immutable message/event stream answers:

> What exactly did Chat A tell Chat B, and when?

The mutable view answers:

> What do both agents currently understand the shared working state to be?

However, the Transaction abstraction does not itself solve cross-chat filesystem/network transport. That transport must be independently established and then registered as a machine capability behind the Transaction gateway.

---

## 18. Recursion requires an explicit primitive boundary

If literally every contract invocation created another full transaction, the architecture could recurse indefinitely:

```text
transaction
  -> semantic interrogatory contract
       -> transaction
            -> semantic interrogatory contract
                 -> ...
```

Therefore the Transaction should be the outer machine interaction primitive, while multiple contract instances can execute inside the transaction scope without each necessarily becoming another top-level transaction.

A small deterministic bootstrap/core registry is required for primitives such as:

```text
transaction.open
transaction.append/execute
contract.lookup
knowledge.query
state.read/state.transition
event.record
transaction.close
```

Higher-level capabilities can live in the KB/contract registry and be invoked through those root primitives.

This root kernel is analogous to the minimum instruction set needed to bootstrap the self-queryable execution repertoire without requiring a KB query to learn how to perform the KB query itself.

---

## 19. The canonical persistence representation remains an explicit reconciliation question

Chat A originally described the transaction as a complete higher-level object containing semantic sections, subcontracts, order ledger, state transitions, validation, and proposal links.

Chat B proposed a stronger event-sourced representation:

- canonical authority = append-only typed frame stream;
- materialized transaction object = deterministic replay/projection;
- one writer per transaction ID;
- expected-sequence checks on append;
- state as a projection of accepted state-transition frames;
- large external artifacts stored by immutable content-addressed reference;
- Sheets as projection only.

The two positions are compatible at the information-model level but differ at the persistence-authority level.

A likely reconciliation is:

```text
AUTHORITATIVE STORAGE
    immutable ordered transaction frames/events

DETERMINISTIC MATERIALIZED VIEW
    complete transaction object
        semantic pre-execution
        subcontracts
        execution order
        validation
        semantic post-execution
        proposal lifecycle
        state transitions
        closure status
```

This gives Chat A's self-contained reviewable transaction model without requiring the system to rewrite an enormous nested object on every append.

---

## 20. Sheets cannot be the canonical complete transaction store

The current execution controller's recording design includes bounded depth and per-cell size limits. A canonical transaction return cannot silently become a summary merely because the external projection surface has cell limits.

Therefore:

```text
canonical durable transaction/event store
        |
        +-- full content / content-addressed immutable payloads
        |
        v
projection layer
        |
        +-- Google Sheets
        +-- analysis indexes
        +-- summaries / searchable columns
```

If a canonical payload is too large for a Sheet cell, the complete canonical payload must remain in the durable store and the Sheet should contain an immutable hash/reference plus useful bounded indexing fields.

Projection failure must not advance the projection watermark until the row/reference is durably written.

---

## 21. Recovery and idempotency must be first-class deterministic concerns

Externally mutating operations need idempotency identities.

If the process crashes after an external mutation succeeds but before the result is durably recorded, a naïve retry could duplicate the mutation.

Therefore a mutating machine contract should carry an idempotency key derived from transaction/contract-instance identity or a registered operation key.

Recovery should determine whether the mutation already committed before issuing the same operation again.

Recovery records should preserve:

- prior operation identity;
- idempotency key;
- persisted external evidence;
- deterministic recovery classification where possible;
- semantic recovery decision only when deterministic evidence is insufficient.

This is one of the strongest additions in Chat B's candidate and should be incorporated into the reconciled design.

---

## 22. Concurrency requires expected-sequence and expected-state preconditions

If transactions or state operations can execute concurrently, the deterministic kernel needs explicit write-conflict rules.

A good baseline is:

```text
one writer per transaction ID
append(expected_previous_sequence=N)
state mutation(expected_state_version=V, expected_state_hash=H)
```

An append or mutation succeeds only if the expected identity still matches the current authoritative state.

Independent transactions can execute concurrently only when their declared resource/state scopes permit it.

Parallel subcontract execution should retain explicit dependency metadata and execution groups so causal order remains reconstructable.

---

## 23. Recommended script/module decomposition

The repository's experimental transaction folder already contains script/module suggestions. A reconciled implementation can use the following decomposition as a concrete starting point.

### `transaction_kernel.py`

Responsibilities:

- exclusive model-facing machine gateway;
- open/close transaction lifecycle;
- sequence/phase rules;
- contract resolution dispatch;
- authorization boundary;
- expected-sequence enforcement;
- transaction status derivation;
- prevention of direct model bypass to lower-level machine methods.

Representative entry point:

```python
def handle_transaction(message):
    ...
```

or a lower-level internal primitive:

```python
def transact(contract_id, inputs, *, transaction_id=None):
    ...
```

### `transaction_contract_registry.json`

Pinned bootstrap-critical definitions for:

- transaction frame/section schemas;
- semantic interrogatory contracts;
- machine-operation contracts;
- KB query contracts;
- state read/transition contracts;
- proposal lifecycle contracts;
- close-status definitions;
- executor/producer bindings;
- validation/capture policies.

The registry should have a stable schema/version and content hash.

### `transaction_store.py`

Responsibilities:

- authoritative append-only transaction/frame persistence;
- atomic append;
- sequence allocation/checking;
- transaction replay;
- deterministic materialization of complete transaction views;
- transaction-history queries;
- persistence receipts.

A practical initial canonical format could be JSONL or SQLite/event-table storage, one immutable frame/event per row.

### `transaction_executor.py`

Responsibilities:

- resolve registered deterministic executor bindings;
- execute scripts/methods/tools;
- apply idempotency keys;
- capture exact contract-shaped machine returns;
- produce mutation receipts;
- propagate structured execution failures;
- never delegate return serialization to the semantic model.

### `transaction_semantic.py`

Responsibilities:

- construct schema-constrained semantic requests;
- invoke the semantic model through the registered semantic contract path;
- validate semantic result shapes;
- maintain version/hash identity for interrogatory definitions;
- produce pre-execution and post-execution semantic records;
- extract and structure proposed next actions/commitments.

### `transaction_state.py`

Recommended addition beyond Chat B's original module list.

Responsibilities:

- state read contracts;
- state-transition validation;
- expected version/hash preconditions;
- deterministic transition application;
- materialization/replay of current state from accepted transition events if event-sourced authority is adopted;
- state transition receipts.

### `transaction_knowledge.py`

Recommended addition for explicit KB separation.

Responsibilities:

- transactional KB query execution;
- record exact query and requested types/configuration;
- bind exact KB identity/version/hash;
- return complete ordered retrieval results;
- preserve immutable knowledge-record identity/provenance.

### `transaction_proposals.py`

Recommended addition because model commitments are analytically important.

Responsibilities:

- proposal ID creation;
- structured proposal schema validation;
- proposal ordering/dependencies;
- proposal lifecycle (`PROPOSED`, `EXECUTED`, `SUPERSEDED`, `ABANDONED`, `BLOCKED`);
- linkage to subsequent transaction IDs/contract instances;
- queries for intent-to-execution divergence.

### `transaction_artifacts.py`

Responsibilities:

- immutable artifact identities;
- SHA-256/size/MIME metadata;
- content-addressed references;
- policy determining when payload bytes are inline versus referenced;
- integrity verification when artifacts are later resolved.

### `transaction_coordination.py`

Recommended future module once inter-chat transport is proven.

Responsibilities:

- coordination mailbox/message contracts;
- persistent mutable shared-view operations;
- blocking `WAIT_FOR_MESSAGE` semantics;
- message sequence/cursor/acknowledgement;
- broadcast/topic subscriptions;
- deadlock detection;
- transport abstraction so the transaction layer does not depend on whether the substrate is rsync, socket, external service, or another platform primitive.

### `transaction_projection.py`

Responsibilities:

- project canonical transaction events to Google Sheets and other external analysis surfaces;
- bounded cells/rows;
- content hash/reference for oversized payloads;
- searchable summary/index columns that never replace canonical source;
- projection watermark/acknowledgement only after successful durable projection.

### Existing controller adapter

During migration, the current Execution Contract Controller can remain intact behind a registered transaction machine contract rather than being immediately rewritten.

For example:

```text
MODEL
  -> transaction_kernel
      -> registered current-controller adapter contract
          -> existing execution_contract_controller
```

This allows the Transaction interface and persistence model to be proven independently before deciding which existing controller/carrier abstractions should be collapsed or retired.

---

## 24. Suggested transaction runner flow

A high-level runner can be expressed as:

```python
def run_transaction(contract_id, arguments):
    transaction = open_transaction(contract_id, arguments)

    pre = run_pre_execution_interrogatory(
        transaction=transaction,
        arguments=arguments,
    )

    execution_contract = resolve_execution_contract(
        transaction=transaction,
        pre_execution=pre,
    )

    raw_results = execute_bound_methods(
        contract=execution_contract,
        arguments=arguments,
    )

    return_object = populate_return_object(
        contract=execution_contract,
        raw_results=raw_results,
    )

    validate_schema(
        execution_contract["output_schema"],
        return_object,
    )

    validate_complete_capture(
        raw_results,
        return_object,
    )

    post = run_post_execution_interrogatory(
        transaction=transaction,
        pre_execution=pre,
        execution_result=return_object,
    )

    transaction_status = derive_transaction_status(
        transaction=transaction,
        execution_result=return_object,
        post_execution=post,
    )

    closed = close_and_persist_transaction(
        transaction=transaction,
        pre_execution=pre,
        execution_contract=execution_contract,
        execution_result=return_object,
        post_execution=post,
        transaction_status=transaction_status,
    )

    return closed
```

Then, outside transaction closure, substantive planning returns to the model:

```python
closed = run_transaction(...)

next_action = model_deliberate(
    task_state=current_plan,
    last_transaction=closed,
    available_execution_knowledge=current_kb_context,
)

next_transaction_request = resolve_model_action(next_action)
```

If model deliberation itself is represented as a semantic transaction frame, the recursion boundary must remain explicit: semantic decision frames occur inside the transaction kernel primitive rather than recursively opening an unbounded hierarchy of full transactions.

---

## 25. Migration strategy

A low-risk migration should avoid replacing the entire existing controller in one operation.

Suggested sequence:

1. Implement experimental transaction schemas and durable append-only transaction store.
2. Implement the exclusive transaction gateway/kernel.
3. Wrap the existing execution controller behind a registered machine-operation contract.
4. Route KB retrieval through a registered KB-query transaction contract.
5. Route semantic pre-execution and post-execution interrogatories through registered semantic contracts.
6. Add structured model proposal capture and lifecycle linkage.
7. Make state access exclusively transactional.
8. Add state version/hash preconditions and receipts.
9. Move Sheets from canonical-looking event payload storage to a projection/index surface over the durable transaction store.
10. Add content-addressed artifact support for payloads/files that should not be recursively embedded.
11. Add recovery/idempotency semantics for external mutations.
12. Add concurrency/expected-sequence rules.
13. Only after the new transaction boundary is proven should the project decide whether the existing controller, carrier, and legacy event abstractions should be collapsed, replaced, or retained internally.

This separates architectural validation from wholesale controller replacement.

---

## 26. Fundamental final separation of responsibility

The system should preserve this division:

```text
SEMANTIC MODEL / PLANNER
    = interpretation
      strategy
      categorization
      diagnosis
      KB query formulation
      capability/procedure selection
      proposed next actions
      substantive next-action choice

DETERMINISTIC TRANSACTION KERNEL
    = schema enforcement
      exclusive interface mediation
      contract resolution
      sequencing
      machine execution
      state-transition application
      idempotency/concurrency rules
      exact return capture
      validation
      persistence
      proposal lifecycle linkage
      closure status
      projection

MACHINE / STATE / KB / TOOLS
    = actual external deterministic capabilities
```

The transaction framework should not eliminate semantic agency. It should make semantic agency **observable, bounded, typed, and causally linked to deterministic execution**.

That distinction is the principal architectural conclusion.

---

## 27. Reconciliation points with Chat B

The two experimental candidates now largely agree on the semantic/deterministic information model. The remaining architectural choices that should be deliberately reconciled before canonical implementation are:

- authoritative persistence form: mutable/self-contained transaction object versus immutable frame stream with materialized view;
- state authority: independent mutable state object versus event-sourced projection of accepted state-transition frames;
- artifact completeness: when exact bytes belong inline versus when immutable content-addressed references are the correct contract return;
- exact recursion boundary for semantic frames and internal deterministic subcontracts;
- recovery/idempotency rules;
- concurrent append/state mutation rules;
- exact transaction/open/close status taxonomy;
- Sheets projection mechanics;
- migration boundary around the current execution controller;
- how future inter-chat coordination contracts plug in once a reliable cross-runtime transport is proven.

A likely reconciled architecture is an **append-only authoritative transaction event/frame stream plus a deterministic complete materialized transaction view**, with the model using only the transaction gateway to reach all machine capabilities.

---

## Summary conclusion

The Transaction is not merely another controller wrapper. It is intended to become the **sole machine capability boundary available to the model** and the **complete semantic/deterministic causal record of every governed interaction**.

The model remains responsible for semantic interpretation and substantive planning. The deterministic kernel is responsible for making every machine interaction typed, contract-mediated, validated, completely recorded, state-consistent, replayable, and auditable.

This makes it possible to answer, from the historical record, all of the following without reconstructing intent from prose alone:

- What did the model believe it was trying to accomplish?
- What requirements and constraints did it recognize?
- What machine capability did it select?
- What exact contract governed the operation?
- What method actually executed?
- What inputs did it receive?
- What exact machine result did it produce?
- Was the result complete and schema-valid?
- What state transition actually occurred?
- What did the model think the result meant?
- What fix/retest/next action did the model propose?
- Did the model actually perform that proposed action later?
- If not, was it superseded, abandoned, blocked, or simply never executed?
- What KB knowledge was available to the model when it chose the next action?
- What exact sequence and causal dependencies connected the machine operations?
- Can the state and transaction history be replayed deterministically?

That is the intended outcome of the transactional redesign.
