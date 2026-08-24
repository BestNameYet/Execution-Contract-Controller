# Create / Revise / Execute Contract Control Loop

Date: 2026-08-24

## Status

Design note capturing the simplified first implementation of the transactional execution architecture. This note intentionally favors a small deterministic controller, explicit mandatory knowledge-base context, a model-authored well-formed contract, and strict deterministic validation over a large action-by-action semantic control sequence.

## Core design decision

The outer control loop should remain extremely small:

```text
USER PROMPT
    ↓
MODEL ↔ CONTROLLER [CREATE or REVISE]
    ↓
VALID CONTRACT
    ↓
MODEL ↔ CONTROLLER [EXECUTE]
    ↓
EXECUTION RESULT
    ↓
USER
```

The controller does not attempt to semantically plan the whole task itself. It deterministically controls the sequence of semantic requests, supplies mandatory KB guidance, performs KB retrieval, validates response shapes and contract structure, and records state. The model performs the semantic transformations and ultimately executes the validated contract through the machine/tool environment.

The top-level entry menu has three operations:

```text
CREATE
REVISE
EXECUTE
```

Their meanings are:

- **CREATE**: turn a new user prompt into a valid executable contract.
- **REVISE**: take an existing contract plus a revision request, append any additional knowledge needed, and produce a valid successor contract.
- **EXECUTE**: run an existing valid contract through the model and machine/tool environment.

## Mandatory context versus selected context

The KB contains two distinct classes of context.

### Mandatory context

Mandatory context is injected by the controller because it defines how the model must perform the next semantic transformation. The model does not select whether to receive it.

Examples:

- prompt → goal guidance
- goal → KB-query guidance
- KB-item selection guidance
- contract-construction guidance
- contract-revision guidance

Mandatory context is procedural knowledge for the construction stage itself.

### Selected context

Selected context is task-specific knowledge discovered through KB retrieval and chosen by the model from retrieved candidates.

Examples may include procedures, actions, capabilities, heuristics, patterns, or other execution knowledge.

The controller performs retrieval deterministically. The model decides semantic relevance. After the model selects item IDs, the controller resolves those IDs to the full canonical KB records.

The distinction is:

```text
mandatory context = how to perform the current construction transformation
selected context  = task-specific knowledge discovered for the current work
```

## CREATE phase

CREATE begins with a new user prompt and produces a valid contract.

### 1. Acquire prompt

The controller asks for the current user prompt. The prompt is preserved as authoritative source material.

### 2. Prompt → goal

The controller supplies:

- the original prompt
- the mandatory KB entry describing how to turn a prompt into a goal
- an exact response schema

The model returns a goal, for example:

```json
{
  "goal": "Determine which supplied image is AI-enhanced and explain the material differences."
}
```

The controller validates only the required response shape.

### 3. Goal → KB queries

The controller supplies:

- the goal
- the mandatory KB entry describing how to convert a goal into retrieval queries
- an exact response schema

The model returns one or more KB queries:

```json
{
  "queries": [
    "compare supplied images for enhancement",
    "image metadata pixel comparison",
    "explain subtle image enhancement"
  ]
}
```

The model formulates the search language. The controller executes the searches deterministically.

### 4. Retrieve candidate KB items

The controller executes the queries and returns compact candidate projections rather than immediately returning every full record.

A projection can contain:

```json
{
  "id": "procedure.image-metadata-pixel-analysis",
  "type": "procedure",
  "title": "Image Metadata and Pixel Analysis",
  "summary": "Compare aligned images using metadata and deterministic pixel measurements."
}
```

The controller also supplies the mandatory KB entry describing how to select useful retrieved knowledge.

### 5. Select KB items

The model returns only the selected IDs:

```json
{
  "selected": [
    "procedure.image-metadata-pixel-analysis",
    "heuristic.reuse-produced-output"
  ]
}
```

The controller validates that the IDs came from the candidate set and then resolves them to full KB records.

### 6. Construct contract

The controller supplies the model with:

- original user prompt
- goal
- full selected KB records
- mandatory contract-construction KB entry
- the required contract schema and verbose field definitions

The contract-construction entry is mandatory. It is not retrieved or selected by the model.

The model returns a complete well-formed contract.

### 7. Validate contract

The controller validates the contract deterministically. If invalid, it returns exact structural errors and allows the model to repair the contract until it passes.

The controller does not semantically decide whether the model's plan is wise. It decides whether the returned object is a valid instance of the execution-contract grammar.

Once valid, CREATE terminates with a stored valid contract.

## REVISE phase

REVISE is intentionally close to CREATE. It does not require a separate planning architecture.

The starting state is:

- existing contract
- complete prior construction context
- revision request

No prior context is removed merely because the controller considers it irrelevant. Relevance, supersession, conflict resolution, and what old knowledge to ignore remain model decisions.

Context accumulation is therefore monotonic:

```text
C1 construction context:
    K1 K2 K3

revision retrieval:
    K4 K5

C2 construction context:
    K1 K2 K3 K4 K5
```

The successor contract may reference only a subset, but all prior context remains available as context and provenance.

### Revision flow

```text
existing contract
+ all prior construction context
+ revision request
        ↓
model describes the revision target
        ↓
mandatory revision-question → query guidance
        ↓
model returns KB query/queries
        ↓
controller runs KB retrieval
        ↓
optional additional topic/candidate selection if needed
        ↓
controller resolves selected items to full records
        ↓
append new records to prior context
        ↓
existing contract
+ revision request
+ all old context
+ all newly selected context
+ mandatory revision-construction context
        ↓
model returns successor contract
        ↓
deterministic validation
        ↓
new valid contract version
```

The revision question is gathered primarily so that the model can formulate a useful KB query from it. The controller does not turn the revision request into its own semantic plan.

A revision creates a successor contract; it does not mutate the historical contract record in place.

## EXECUTE phase

EXECUTE accepts a valid contract and causes the model to perform it through the machine/tool environment.

Conceptually:

```text
validated contract
      ↓
controller execution entry
      ↓
model receives contract as executable instruction
      ↓
model ↔ controller / machine / tools
      ↓
observable execution events and results
      ↓
execution receipt / final result
```

The model performs the semantics of the contract. The controller owns the execution boundary, transport, persistence, and recording.

The intended external behavior is that contract execution can be invoked as one script-level operation, conceptually:

```bash
python runtime.py execute '<contract-json>'
```

The fact that the model may make multiple tool calls or machine operations internally does not require the outer controller to become a large procedural decision engine.

## Contract as the enforcement boundary

This design deliberately moves rigor into the contract definition instead of a long deterministic questionnaire.

The model decides what the contract means. The controller decides what counts as a valid contract.

A useful separation is:

```text
MODEL decides:
- semantic goal
- query formulation
- relevance of KB knowledge
- procedure semantics
- how available context should be used
- substantive contract content

CONTROLLER decides:
- required fields
- allowed types
- schema version
- identity
- reference validity
- cardinality
- graph/connectivity rules
- required bindings
- lineage
- execution readiness
- event persistence
```

The specification presented to the model can be highly verbose while the validator remains generic.

For example, the contract schema can define a field with extensive semantic guidance:

```json
{
  "required_outputs": {
    "type": "array",
    "minItems": 1,
    "description": "Every externally observable result that must exist for the user's request to be considered complete. Do not include preparatory work, verification not requested by the user, implementation details, or intermediate states unless those are themselves explicitly requested results."
  }
}
```

The model receives the full definition. The deterministic implementation may still reduce to ordinary schema validation plus a small number of generic graph/reference checks.

## Contract validity layers

A first version should separate validation into three deterministic gates.

### 1. Shape validity

Questions mechanically answerable from schema:

- Is the returned object valid JSON?
- Is the schema/version accepted?
- Are all required fields present?
- Are field types correct?
- Are enums valid?
- Are cardinality requirements satisfied?

### 2. Referential validity

Questions about internal references:

- Are IDs unique?
- Do all referenced inputs, outputs, steps, dependencies, and KB records exist?
- Were referenced KB items actually available in construction context?
- Do completion references identify declared outputs?
- Are bindings supplied for required parameters?

### 3. Execution validity

Questions mechanically answerable from the declared execution structure:

- Is every required output reachable?
- Is every required input bound or supplied?
- Does each declared produced value have a producer?
- Do steps reference only values available before use?
- Is the dependency graph acyclic where acyclicity is required?
- Is there a mechanically complete path from available inputs to all required completion outputs?

Only after all applicable gates pass is the contract eligible for EXECUTE.

## Validation repair loop

Invalid contracts should receive deterministic error reports rather than semantic criticism from another model pass.

Example:

```json
{
  "valid": false,
  "errors": [
    {
      "path": "$.procedure[2].uses[0]",
      "code": "UNRESOLVED_REFERENCE",
      "message": "Reference 'O7' does not identify a declared input or produced output."
    }
  ]
}
```

The controller returns the exact errors to the model, the model repairs the contract, and the same validator runs again.

```text
model returns contract
      ↓
deterministic validation
   ┌──┴──┐
 valid  invalid
   │      ↓
execute  exact validation errors
          ↓
        model repairs
          ↓
        validate again
```

A semantic validator should be added only if empirical failures demonstrate a class of invalidity that cannot be encoded structurally or referentially.

## Script-owned envelope and model-authored body

The model should author the semantic contract body. The controller should add machine-owned metadata after validation.

Controller-owned envelope fields can include:

```json
{
  "contract_id": "contract_...",
  "version": 2,
  "parent_contract_id": "contract_...",
  "created_at": "...",
  "source_prompt_hash": "...",
  "construction_context_ids": ["K1", "K2", "K3", "K7"],
  "body": {}
}
```

This prevents the model from rewriting identity, version lineage, timestamps, provenance, or historical relationships.

A revision therefore naturally produces:

```text
Contract C1
    ↓ revised
Contract C2
    ↓ revised
Contract C3
```

Executions remain separate records:

```text
Contract C3
   ├─ Execution E1
   └─ Execution E2
```

Execution does not mutate the contract itself.

## Minimal controller state machine

The important result is that the high-level controller remains small despite rich contract requirements.

Conceptually:

```python
while True:
    request = get_user_request()
    mode = get_entry_mode()   # CREATE / REVISE / EXECUTE

    if mode == "CREATE":
        contract = create_contract_with_model(request)

    elif mode == "REVISE":
        contract = revise_contract_with_model(request)

    elif mode == "EXECUTE":
        contract = load_existing_contract(request)

    validate_contract(contract)
    result = execute_contract_with_model(contract)
    return_result_to_user(result)
```

The internal CREATE and REVISE routines are bounded semantic-selection loops driven by mandatory KB entries and deterministic retrieval. EXECUTE is a separate phase that receives only a valid contract.

The outer protocol is therefore:

```text
USER
  ↓
MODEL ↔ CONTROLLER [CREATE / REVISE]
  ↓
VALID CONTRACT
  ↓
MODEL ↔ CONTROLLER [EXECUTE]
  ↓
USER
```

## Why this is preferable for the first implementation

This design avoids prematurely encoding a large ontology of atomic actions, procedures, dependencies, and semantic admissibility tests into deterministic controller topology.

Instead it provides:

1. a small deterministic orchestration loop;
2. explicit KB-guided semantic transformations;
3. deterministic KB retrieval;
4. model selection of task-relevant knowledge;
5. a model-authored but machine-validatable contract;
6. strict execution admission at the contract boundary;
7. complete construction and execution event records from which richer procedure/contract abstractions can later be derived empirically.

The specification can become extremely precise without making the runtime sequence correspondingly long. Verbosity belongs in declarative KB entries and contract field definitions; enforcement belongs in generic validators; semantic judgment belongs in the model.

This produces the desired controlling architecture:

```text
user prompt
→ model ↔ controller [create/revise phase]
→ validated contract
→ model ↔ controller [execute phase]
→ result back to user
```
