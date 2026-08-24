# Contract Builder: Procedure Selection Before Procedure Authoring

## Context

The contract builder is itself a recorded runtime transaction. Its product is a completed execution contract, which is then executed by the runtime as a separate execution transaction. The transactional machinery remains internal; the model-facing interface should expose only contextual information, a bounded semantic request, and an exact return schema.

The model must not be assumed to have a priori knowledge of available procedures, capabilities, outputs, files, scripts, destinations, or runtime methods. Each semantic decision step is preceded by contextual retrieval from the execution knowledge base.

## Core procedural rule

Procedure selection and procedure authoring are different branches.

The builder must first retrieve procedures relevant to the current unresolved goal. If one or more applicable procedures are returned, the model selects among those retrieved procedures. It should not rewrite or restate a valid stored procedure. The contract should instead reference the selected procedure by identity and supply only the required bindings.

If no applicable procedure exists, the builder instantiates a procedure template and walks the model through constructing a new procedure. Before each unresolved procedure field is presented, the builder performs another contextual knowledge-base retrieval so that existing actions, capabilities, procedures, patterns, heuristics, known state, and prior successful compositions can be reused.

## Procedure-selection path

```text
current partial contract
        ↓
script identifies unresolved execution/procedure dimension
        ↓
script builds contextual KB query
        ↓
KB returns applicable procedure candidates
        ↓
script presents only retrieved candidates + context + exact return schema
        ↓
model selects one candidate or returns NONE
        ↓
script validates selection mechanically
        ↓
selected procedure is referenced in the contract
        ↓
script resolves required bindings recursively
```

The model-facing semantic choice should normally be bounded to something equivalent to:

```text
SELECT_PROCEDURE
NO_APPLICABLE_PROCEDURE
```

When several procedures are returned, the runtime supplies the goal, relevant known state, concise applicability context, candidate IDs, and a return schema. The script validates that any selected ID was among the retrieved candidates.

## Stored-procedure representation

When a valid procedure already exists, the contract should preserve it by reference instead of semantic reproduction. Conceptually:

```json
{
  "procedure": {
    "source": "knowledge_base",
    "id": "procedure.example",
    "version": 1,
    "bindings": {
      "required_parameter": "resolved value"
    }
  }
}
```

This preserves the exact procedure, reduces semantic drift, lowers token and reasoning cost, retains provenance, and makes repeated executions mechanically comparable.

## Binding phase

Selecting a procedure does not imply that its required arguments are already known.

Each procedure declares required bindings. For each unresolved binding, the builder follows the same recurring mechanism:

```text
required binding
      ↓
contextual KB retrieval
      ↓
known value available deterministically?
   ├─ yes → bind mechanically
   └─ no  → present retrieved options/context to model
                ↓
             validate returned shape
                ↓
             bind selected or supplied value
```

The model is therefore never expected to supply operational knowledge that the runtime has not first exposed through contextual retrieval.

## No-procedure path

If the model selects NONE because no retrieved procedure is applicable, the script loads a procedure template.

The procedure template defines structure, not content. A representative template contains fields such as:

- objective
- preconditions
- required inputs
- steps
- branch conditions
- produced state
- requested products/outputs
- failure conditions

The builder walks those fields procedurally. Before every unresolved semantic field, it queries the KB using the current objective, accumulated contract state, unresolved field, and any already selected knowledge references.

The model then fills only the semantic gap that remains after retrieval.

## Composition preference

New procedures should be composed from existing knowledge references whenever possible.

Preferred order:

```text
existing deterministic action
        ↓
existing procedure
        ↓
composition of existing action/procedure/capability references
        ↓
newly authored inline operation
```

This ordering is enforced by the builder's procedural search sequence, not by a prose invariant.

A newly constructed procedure can therefore be mostly referential:

```json
{
  "steps": [
    {
      "kind": "action_ref",
      "id": "action.example",
      "bindings": {}
    },
    {
      "kind": "procedure_ref",
      "id": "procedure.example",
      "bindings": {}
    },
    {
      "kind": "operation",
      "definition": {}
    }
  ]
}
```

Only the inline operation requires genuinely new semantic procedure content.

## Recurring KB-guided builder loop

The builder is a deterministic recursive selection machine:

```text
PARTIAL CONTRACT
      ↓
script selects next unresolved dimension
      ↓
script generates KB query from user prompt + goal + current contract + unresolved dimension
      ↓
KB retrieval
      ↓
script constructs model-facing context, options, semantic request, and exact return schema
      ↓
model returns bounded semantic selection/value
      ↓
script validates response shape and allowed selection
      ↓
script mutates partial contract
      ↓
selected records may introduce additional unresolved dimensions
      ↓
repeat
```

The script owns sequencing and state transition. The knowledge base owns discoverable execution knowledge. The model owns bounded semantic selection among what has been retrieved. The accumulated contract owns the resulting execution specification.

## Builder responsibilities

The script should mechanically:

1. Identify the next unresolved contract component.
2. Query the KB for applicable procedures before procedure authoring.
3. Present only retrieved procedures to the model.
4. Validate the selected procedure ID.
5. Determine unresolved procedure bindings.
6. Resolve known bindings mechanically where possible.
7. Query the KB before every unresolved semantic binding.
8. Instantiate the procedure template only when no valid procedure exists.
9. Fill the template recursively using retrieved actions, procedures, capabilities, patterns, heuristics, and known state.
10. Record every retrieval, semantic selection, validation result, and contract mutation as part of the builder transaction.

## Architectural result

The semantic worker is not expected to know the runtime's procedures in advance and is not normally asked to author procedures that already exist. It chooses among execution knowledge discovered just in time and synthesizes only where the knowledge base does not already contain an adequate mechanism.

The builder itself remains fully recorded as a transaction. Once its product—the completed execution contract—is complete, that contract is passed into the runtime for execution as a subsequent recorded transaction.
