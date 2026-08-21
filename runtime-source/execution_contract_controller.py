#!/usr/bin/env python3
"""Deterministic execution-contract / state-transition controller."""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTROL_VERSION = 1
INITIALIZATION_SCHEMA = "execution-contract-controller-initialization-v1"
PAYLOAD_SCHEMA = "execution-contract-controller-payload-v1"
CONTRACT_SCHEMA = "execution-contract-v1"
INVOCATION_EVENT_SCHEMA = "chatgpt-controller-invocation-event-v1"
RECORDING_DIRECTIVE_SCHEMA = "chatgpt-event-recording-instruction-v1"
RECORDING_SIDECAR_FIELDS = {"recording_event", "recording_instruction"}
PROJECT_NAME = "Execution Contract Persistence"
PROJECT_RECORD_FOLDER_ID = "1uTw38OhZZbZVRryd_EaVgkD4Es2sDlKn"
PROJECT_RECORD_FOLDER_NAME = "Execution Contract Persistence"
PROJECT_RECORD_SPREADSHEET_ID = "19dQDq76evR4c9BeWyzlA-sY5aUVG9iTnBlgUN4dODmI"
PROJECT_RECORD_WORKSHEET = "Events"
PROJECT_RECORD_SHEET_ID = 1930933064

CONTRACT_PROTOCOL = "compile-contract-v1"
REALIZATION_PROTOCOL = "realize-transition-v1"
ADMISSIBILITY_PROTOCOL = "classify-operation-v1"
DEPENDENCY_PROTOCOL = "admit-dependency-v1"
EVIDENCE_PROTOCOL = "classify-evidence-v1"
IMPASSE_PROTOCOL = "classify-impasse-v1"
SEMANTIC_OUTPUT_TYPE = "SEMANTIC_OUTPUT"

SEMANTIC_TRANSPORT_BY_PROTOCOL = {
    CONTRACT_PROTOCOL: ("CONTRACT_RESULT", "source_request", "contract"),
    REALIZATION_PROTOCOL: ("REALIZATION_RESULT", "payload", "result"),
    ADMISSIBILITY_PROTOCOL: ("ADMISSIBILITY_RESULT", "payload", "result"),
    DEPENDENCY_PROTOCOL: ("DEPENDENCY_RESULT", "payload", "result"),
    EVIDENCE_PROTOCOL: ("EVIDENCE_RESULT", "payload", "result"),
    IMPASSE_PROTOCOL: ("IMPASSE_RESULT", "payload", "result"),
}

RELATIONS = {
    "DIRECTLY_REALIZES_TARGET",
    "DIRECTLY_REALIZES_DEPENDENCY",
    "DOES_NOT_REALIZE_SCHEDULED_STATE",
}
VERDICTS = {"SATISFIED", "NOT_SATISFIED", "INDETERMINATE"}
SCOPES = {"TRANSITION_ONLY", "PREDICATE_UNATTAINABLE", "TASK_UNATTAINABLE", "UNKNOWN"}
OP_KINDS = {"READ", "SEARCH", "CALCULATE", "TRANSFORM", "MUTATE", "CREATE", "DELETE", "SEND", "EXECUTE", "WAIT", "OTHER"}

BEHAVIORAL_INSTRUCTIONS = [
    "Treat the accepted execution contract as the authoritative representation of the current user instruction.",
    "Respond to each controller request according to its declared protocol and return only the requested structured result.",
    "For semantic requests, evaluate only the supplied decision context and the definitions in the output schema; do not infer hidden state or substitute an independent plan.",
    "When a predicate is scheduled, identify a concrete operation that directly realizes that predicate whenever one is legitimately available.",
    "Do not introduce support work, prerequisites, checks, planning, inspection, validation, clarification, or other intermediate process unless it is explicitly required by the contract or admitted as a necessary dependency.",
    "Apply counterfactual necessity to indirect work: if omitting a proposed dependency still leaves a legitimate path to the scheduled predicate, classify that dependency as unnecessary.",
    "Prefer direct realization over indirect preparation whenever both can legitimately reach the scheduled predicate.",
    "When an operation is authorized, perform exactly that operation and then report the observable result and resulting state for evidence classification before selecting or performing another material operation.",
    "Classify evidence against the predicate's accepted evidence standard; do not add stronger completion requirements after the contract is accepted.",
    "Treat completion as satisfaction of the contract's terminal predicates. Once they are satisfied, do not invent additional material work.",
    "Treat impasse as a property of the remaining contract state, not of a single failed operation; an impasse exists only when no legitimate continuation path remains.",
    "Preserve contract invariants, authorizations, prohibitions, dependencies, and blocked semantic equivalents throughout execution.",
]

INDIRECT_WORK_DEFINITION = {
    "definition": "Indirect work is any operation whose immediate successful result does not itself establish the currently scheduled predicate, but instead prepares for, enables, investigates, validates, locates, plans, configures, translates for, administers, or increases confidence in a later material operation that could establish it. An operation is indirect when another material operation must still occur after it before the scheduled predicate can become true.",
    "decisive_test": "Ask: if this operation succeeds completely, is the scheduled predicate itself now true? If yes, the operation may be direct. If no and another material operation is still required, the operation is indirect.",
    "categories": [
        {"name": "PREPARATION", "definition": "Setup, staging, formatting, organizing, pre-processing, creating scaffolding, or arranging resources for a later action."},
        {"name": "INSPECTION", "definition": "Reading, checking, reviewing, examining, enumerating, or measuring something when the inspection itself does not satisfy the scheduled predicate."},
        {"name": "SEARCH_OR_DISCOVERY", "definition": "Locating a file, source, record, tool, resource, or candidate when finding it is only a precursor to the requested result."},
        {"name": "PLANNING", "definition": "Deciding, decomposing, outlining, designing a procedure, selecting an approach, or generating next steps rather than performing the realizing operation."},
        {"name": "VERIFICATION_OR_VALIDATION", "definition": "Testing, confirming, rechecking, comparing, auditing, or proving something when that verification is not itself part of the requested terminal result."},
        {"name": "CONFIGURATION_OR_SETUP", "definition": "Installing, configuring, authenticating, initializing, creating temporary infrastructure, or changing environment state solely to enable later work."},
        {"name": "REPRESENTATION_TRANSLATION", "definition": "Converting or packaging information solely so that a later material operation can use it."},
        {"name": "CONFIDENCE_INCREASING", "definition": "Collecting additional evidence, redundancy, cross-checking, or corroboration when sufficient information already exists to perform a legitimate direct realization."},
        {"name": "ADMINISTRATIVE_OR_PROCESS", "definition": "Creating branches, pull requests, tickets, drafts, approvals, checkpoints, backups, or documentation when these are not themselves required by the user or an admitted dependency."},
        {"name": "TOOL_ENABLING", "definition": "Acquiring or preparing a tool, connector, file, runtime, or execution environment solely so another operation can later realize the predicate."},
    ],
    "dependency_exception": "Indirect work is not automatically forbidden. It is legitimate only when the condition it realizes is already an admitted dependency, or when dependency admission establishes that no legitimate path to the scheduled predicate remains without that condition. Indirect work must not be represented as direct realization.",
}

# Every static string literal in this exact controller source receives a compact
# token in carried transport history. Dynamic user/model/tool text stays literal.
TRANSPORT_TOKEN_PREFIX = "~"


def _transport_token_tables() -> tuple[dict[str, int], dict[int, str]]:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=__file__)
    vocabulary = sorted({
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value
    })
    by_text = {text: index + 1 for index, text in enumerate(vocabulary)}
    return by_text, {token: text for text, token in by_text.items()}


TOKEN_BY_TEXT, TEXT_BY_TOKEN = _transport_token_tables()


def _encode_transport_string(value: str) -> str:
    token = TOKEN_BY_TEXT.get(value)
    if token is not None:
        return f"{TRANSPORT_TOKEN_PREFIX}{token}"
    if value.startswith(TRANSPORT_TOKEN_PREFIX):
        return TRANSPORT_TOKEN_PREFIX + value
    return value


def _decode_transport_string(value: str) -> str:
    doubled = TRANSPORT_TOKEN_PREFIX * 2
    if value.startswith(doubled):
        return value[1:]
    if value.startswith(TRANSPORT_TOKEN_PREFIX):
        suffix = value[len(TRANSPORT_TOKEN_PREFIX):]
        if suffix.isdigit():
            token = int(suffix)
            text = TEXT_BY_TOKEN.get(token)
            if text is None:
                raise ValueError(f"unknown transport token {token}")
            return text
    return value


def encode_transport(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _encode_transport_string(key) if isinstance(key, str) else key: encode_transport(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [encode_transport(item) for item in value]
    if isinstance(value, tuple):
        return [encode_transport(item) for item in value]
    if isinstance(value, str):
        return _encode_transport_string(value)
    return value


def decode_transport(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _decode_transport_string(key) if isinstance(key, str) else key: decode_transport(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [decode_transport(item) for item in value]
    if isinstance(value, str):
        return _decode_transport_string(value)
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj: Any) -> str:
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def req_dict(v: Any, name: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError(f"{name} must be an object")
    return v


def req_list(v: Any, name: str) -> list[Any]:
    if not isinstance(v, list):
        raise ValueError(f"{name} must be an array")
    return v


def req_text(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} must be non-empty text")
    return v.strip()


def req_bool(v: Any, name: str) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"{name} must be boolean")
    return v


def req_enum(v: Any, allowed: set[str], name: str) -> str:
    if not isinstance(v, str) or v not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return v


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    base = {k: v for k, v in payload.items() if k != "payload_sha256" and k not in RECORDING_SIDECAR_FIELDS}
    payload["payload_sha256"] = digest(base)
    return payload


def verify(payload: dict[str, Any]) -> dict[str, Any]:
    req_dict(payload, "payload")
    if payload.get("schema") != PAYLOAD_SCHEMA:
        raise ValueError("invalid payload schema")
    expected = payload.get("payload_sha256")
    base = {k: v for k, v in payload.items() if k != "payload_sha256" and k not in RECORDING_SIDECAR_FIELDS}
    if not isinstance(expected, str) or digest(base) != expected:
        raise ValueError("payload integrity failure")
    return payload
    return payload


def emit(authority: str, state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = {
        "schema": PAYLOAD_SCHEMA,
        "control_version": CONTROL_VERSION,
        "authority": authority,
        "behavioral_instructions": BEHAVIORAL_INSTRUCTIONS,
        "state": state,
        "issued_at": now(),
    }
    out.update(extra)
    return seal(out)


def record(state: dict[str, Any], typ: str, data: dict[str, Any]) -> None:
    state.setdefault("record", []).append({"id": rid("evt"), "time": now(), "type": typ, "data": deepcopy(data)})


# Semantic schema builders. Every model-returned field carries an operational
# definition. Every predetermined enum value carries its own definition. Boolean
# fields state exactly what true and false assert.
def text_field(definition: str) -> dict[str, Any]:
    return {"type": "string", "definition": definition}


def integer_field(definition: str) -> dict[str, Any]:
    return {"type": "integer", "definition": definition}


def boolean_field(definition: str, true_definition: str, false_definition: str) -> dict[str, Any]:
    return {
        "type": "boolean",
        "definition": definition,
        "true_definition": true_definition,
        "false_definition": false_definition,
    }


def enum_field(definition: str, values: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "enum",
        "definition": definition,
        "values": [{"value": value, "definition": value_definition} for value, value_definition in values.items()],
    }


def array_field(definition: str, items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "definition": definition, "items": items}


def object_field(definition: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "definition": definition, "fields": fields}


def operation_kind_field() -> dict[str, Any]:
    return enum_field("The elementary class of material operation being proposed.", {
        "READ": "Retrieve already-existing information from a known source without modifying that source and without searching for where the source is located.",
        "SEARCH": "Discover or locate information, resources, records, files, entities, or candidate sources when the exact location or identity is not already known.",
        "CALCULATE": "Derive a result through arithmetic, mathematical, statistical, logical, or other deterministic computation from available inputs.",
        "TRANSFORM": "Convert, rewrite, reorganize, summarize, parse, encode, decode, format, or otherwise alter supplied information without changing an external persistent resource.",
        "MUTATE": "Modify the contents, properties, state, or configuration of an existing external or persistent object.",
        "CREATE": "Cause a new persistent object, resource, record, file, draft, branch, task, or other externally represented entity to exist.",
        "DELETE": "Remove, destroy, trash, or otherwise make an existing persistent object or resource cease to exist or cease to be available.",
        "SEND": "Transmit information or an already-prepared object to another person, account, service, destination, or external system.",
        "EXECUTE": "Run a program, command, workflow, script, job, automation, or other executable process whose execution itself is the material operation.",
        "WAIT": "Intentionally defer progress until time passes or an external condition is expected to change rather than performing another presently available operation.",
        "OTHER": "A material operation that does not accurately fit any specifically defined operation class; select only when no other value applies.",
    })


def relationship_field() -> dict[str, Any]:
    return enum_field("The causal relationship between the proposed operation and the currently scheduled state.", {
        "DIRECTLY_REALIZES_TARGET": "Successful execution of this operation itself produces the observable state described by the scheduled terminal target without another material operation being required first.",
        "DIRECTLY_REALIZES_DEPENDENCY": "Successful execution of this operation itself produces the observable state described by the currently scheduled admitted dependency without another material operation being required first.",
        "DOES_NOT_REALIZE_SCHEDULED_STATE": "Successful execution of this operation does not itself produce the currently scheduled target or dependency; this includes preparation, investigation, verification, planning, setup, or work whose result only enables a later material operation.",
    })


def operation_output_schema() -> dict[str, Any]:
    return object_field("A single concrete material operation proposed for execution.", {
        "operation_kind": operation_kind_field(),
        "objective": text_field("The immediate result this operation is intended to accomplish."),
        "target": text_field("The concrete object, resource, state, or subject upon which the operation acts."),
        "command": text_field("The exact operation instruction to execute if the deterministic controller authorizes this proposal."),
        "expected_observable_effect": text_field("The externally observable state change or result expected immediately from successful execution of this operation."),
    })


def realization_output_schema() -> dict[str, Any]:
    return object_field("One realization proposal for the currently scheduled predicate. When kind is OPERATION, operation and classification are both required and classification must describe that exact operation.", {
        "kind": enum_field("Which realization form the response uses.", {
            "OPERATION": "A concrete material operation is available and is proposed together with its complete admissibility classification in this same response.",
            "DEPENDENCY_PROPOSAL": "A currently false condition is claimed to be genuinely necessary before the scheduled predicate can be realized.",
            "IMPASSE_CLAIM": "No legitimate continuation path to the scheduled predicate is claimed to remain.",
        }),
        "operation": {
            **operation_output_schema(),
            "definition": "Required when kind is OPERATION; omit otherwise. " + operation_output_schema()["definition"],
        },
        "classification": {
            **admissibility_output_schema(),
            "definition": "Required when kind is OPERATION; omit otherwise. Classify the exact operation returned in operation against every supplied requirement before the deterministic controller decides whether to authorize it.",
        },
        "dependency": object_field("Required when kind is DEPENDENCY_PROPOSAL; omit otherwise. The proposed necessary condition and evidence basis.", {
            "description": text_field("The condition that is claimed to have to become true before the scheduled predicate can legitimately be realized."),
            "evidence_standard": text_field("The observable evidence sufficient to establish that the proposed dependency has been satisfied."),
            "observed_block": text_field("The specific current observed fact showing why the scheduled predicate cannot legitimately be realized while this condition remains false."),
        }),
        "claim": object_field("Required when kind is IMPASSE_CLAIM; omit otherwise. The concrete factual basis for asserting that no legitimate continuation path remains.", {
            "description": text_field("A concise description of the claimed execution impasse grounded in observed facts."),
        }),
    })

def admissibility_output_schema() -> dict[str, Any]:
    return object_field("Closed semantic classification of the proposed operation. Return every field.", {
        "relationship": relationship_field(),
        "violates_invariant": boolean_field(
            "Whether executing the proposed operation would make one or more supplied invariants false.",
            "At least one supplied invariant would be violated by this operation or its immediate expected effect.",
            "No supplied invariant would be violated by this operation or its immediate expected effect.",
        ),
        "violates_prohibition": boolean_field(
            "Whether the proposed operation or its immediate expected effect falls within a supplied prohibition.",
            "The operation or its immediate expected effect matches at least one supplied prohibition.",
            "The operation and its immediate expected effect do not match any supplied prohibition.",
        ),
        "outside_authorized_objective": boolean_field(
            "Whether the proposed operation pursues an objective outside the supplied authorizations and governing task.",
            "The operation pursues an objective not authorized by the supplied context.",
            "The operation remains within the supplied authorization and task scope.",
        ),
        "introduces_unadmitted_prerequisite": boolean_field(
            "Whether the proposed operation treats additional work or a condition as required even though it has not been admitted as a dependency.",
            "The operation introduces or depends on a prerequisite that is not in the admitted dependency set.",
            "The operation does not introduce or rely on any unadmitted prerequisite.",
        ),
        "repeats_blocked_realization_or_semantic_equivalent": boolean_field(
            "Whether the proposal is the same as, or contextually equivalent to, a realization already blocked for this scheduled predicate.",
            "The proposal repeats a blocked realization or a semantic equivalent of one.",
            "The proposal is materially distinct from all blocked realizations supplied in context.",
        ),
        "requires_additional_material_action_before_it_can_have_stated_effect": boolean_field(
            "Whether successful execution of this operation alone is insufficient to produce its stated expected observable effect.",
            "Another material operation must occur before the stated expected effect can exist.",
            "This operation itself can produce the stated expected observable effect when successful.",
        ),
        "is_indirect_or_support_operation": boolean_field(
            "Whether the proposal is preparation, inspection, planning, verification, setup, or other support work rather than direct realization of the scheduled state.",
            "The proposal is indirect/support work and does not itself realize the scheduled state.",
            "The proposal is not indirect/support work; it is itself a realization attempt for the scheduled state.",
        ),
        "legitimate_path_to_scheduled_predicate_remains_if_operation_is_omitted": boolean_field(
            "Counterfactual necessity test: whether at least one legitimate path to the scheduled predicate remains if this operation is not performed.",
            "At least one legitimate path remains without performing this operation.",
            "No legitimate path remains if this operation is omitted.",
        ),
    })


def dependency_output_schema() -> dict[str, Any]:
    return object_field("Closed classification of whether the proposed dependency may enter the execution graph. Return every field.", {
        "observed_block_is_current_and_concrete": boolean_field(
            "Whether the observed block is a specific fact that exists now rather than a hypothetical or generic concern.",
            "The block is current, concrete, and supported by the supplied context.",
            "The block is hypothetical, generic, stale, unsupported, or not currently present.",
        ),
        "scheduled_predicate_cannot_legitimately_be_realized_while_condition_is_false": boolean_field(
            "Whether the scheduled predicate is genuinely unrealizable while the proposed dependency remains unsatisfied.",
            "No legitimate realization of the scheduled predicate can occur while the condition remains false.",
            "At least one legitimate realization can occur while the condition remains false.",
        ),
        "condition_is_not_merely_prudent_optional_or_confidence_increasing": boolean_field(
            "Whether the condition is necessary rather than merely useful, prudent, conventional, optional, or confidence-increasing.",
            "The condition is genuinely necessary rather than merely beneficial.",
            "The condition is only prudent, useful, conventional, optional, or confidence-increasing.",
        ),
        "dependency_is_within_user_objective_or_governing_requirement": boolean_field(
            "Whether satisfying the proposed dependency stays within the user's objective or a governing requirement supplied in context.",
            "The dependency is within the authorized objective or required by a governing constraint.",
            "The dependency is outside the authorized objective and is not required by a governing constraint.",
        ),
        "simpler_direct_realization_remains_available": boolean_field(
            "Whether a simpler legitimate operation can directly realize the scheduled predicate without satisfying the proposed dependency first.",
            "A simpler direct realization remains available.",
            "No simpler direct realization remains available.",
        ),
        "legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted": boolean_field(
            "Counterfactual necessity test: whether any legitimate path to the scheduled predicate remains if this dependency is omitted from the graph.",
            "At least one legitimate path remains if the dependency is omitted.",
            "No legitimate path remains if the dependency is omitted.",
        ),
    })


def evidence_output_schema() -> dict[str, Any]:
    return object_field("Classification of the action evidence against the scheduled predicate and accepted invariants. Return every field.", {
        "verdict": enum_field("Whether the supplied observable evidence establishes the scheduled predicate under its accepted evidence standard.", {
            "SATISFIED": "The observable evidence is sufficient to establish that the scheduled predicate is true.",
            "NOT_SATISFIED": "The observable evidence establishes that the scheduled predicate is not yet true after the attempted operation.",
            "INDETERMINATE": "The supplied observable evidence is insufficient to determine whether the scheduled predicate is true or false.",
        }),
        "invariant_status": array_field("One classification for every invariant supplied in the decision context.", object_field("Status of one invariant after the action result.", {
            "id": text_field("The exact invariant identifier from the supplied decision context."),
            "status": enum_field("Whether the action evidence establishes preservation or violation of this invariant.", {
                "PRESERVED": "The observable evidence establishes that the invariant remained true.",
                "VIOLATED": "The observable evidence establishes that the invariant became false.",
                "INDETERMINATE": "The observable evidence is insufficient to establish either preservation or violation.",
            }),
        })),
    })


def impasse_output_schema() -> dict[str, Any]:
    return object_field("Closed classification of whether a genuine execution impasse exists. Return every field.", {
        "requested_result_or_required_dependency_is_currently_unattainable": boolean_field(
            "Whether the remaining requested result or currently required dependency cannot presently be attained.",
            "The relevant remaining state is currently unattainable.",
            "The relevant remaining state is not established as currently unattainable.",
        ),
        "materially_different_legitimate_path_remains_available": boolean_field(
            "Whether a materially different legitimate continuation path remains available despite the current block or failed realization.",
            "At least one materially different legitimate continuation path remains.",
            "No materially different legitimate continuation path remains.",
        ),
        "missing_information_is_resolvable_retrievable_calculable_or_safely_assumable": boolean_field(
            "Whether missing information causing the apparent block can legitimately be resolved by retrieval, calculation, or a safe assumption.",
            "The missing information can legitimately be resolved without declaring impasse.",
            "The missing information cannot legitimately be resolved by the available methods.",
        ),
        "remaining_block_is_created_only_by_assistant_process_or_preference": boolean_field(
            "Whether the remaining block exists only because of assistant-added process, preference, convention, or self-imposed requirements.",
            "The block is assistant-created rather than inherent in the user's requested state or governing constraints.",
            "The block is not merely assistant-created process or preference.",
        ),
        "scope": enum_field("The maximum scope of the claimed unattainability.", {
            "TRANSITION_ONLY": "Only the particular attempted transition is blocked; other paths may remain.",
            "PREDICATE_UNATTAINABLE": "The currently scheduled predicate itself has no legitimate attainable path under the supplied context.",
            "TASK_UNATTAINABLE": "The remaining execution contract as a whole has no legitimate attainable completion path.",
            "UNKNOWN": "The available facts do not establish the scope of unattainability.",
        }),
    })


def contract_output_schema() -> dict[str, Any]:
    terminal_item = object_field("One observable end state explicitly requested by the user.", {
        "id": text_field("A unique stable identifier for this terminal predicate within the contract, such as P1."),
        "description": text_field("The observable requested end state, expressed as a condition that can become true or false."),
        "evidence_standard": text_field("The minimum observable evidence sufficient to establish that this terminal predicate is satisfied."),
        "explicit_order": integer_field("The zero-based order explicitly required by the user; use source order when no stronger ordering is stated."),
        "depends_on": array_field("Identifiers of dependencies explicitly required before this terminal predicate; use an empty array when none are explicit.", text_field("An exact dependency identifier declared in explicit_dependencies.")),
    })
    invariant_item = object_field("One condition that must remain true throughout execution.", {
        "id": text_field("A unique stable identifier for this invariant, such as I1."),
        "description": text_field("The condition that must remain true throughout execution."),
    })
    authorization_item = object_field("One user-authorized objective or operation class.", {
        "id": text_field("A unique stable identifier for this authorization, such as A1."),
        "description": text_field("The objective, scope, target, or operation class the user has authorized."),
    })
    prohibition_item = object_field("One explicitly prohibited operation, target, or outcome.", {
        "id": text_field("A unique stable identifier for this prohibition, such as X1."),
        "description": text_field("The operation, target, outcome, or scope that must not occur."),
    })
    dependency_item = object_field("One prerequisite condition explicitly required by the user or governing instruction.", {
        "id": text_field("A unique stable identifier for this explicit dependency, such as D1."),
        "description": text_field("The prerequisite condition that must become true before the listed terminal predicates can legitimately be realized."),
        "required_for": array_field("Terminal predicate identifiers for which this dependency is explicitly required.", text_field("An exact terminal predicate identifier declared in terminal_predicates.")),
        "evidence_standard": text_field("The minimum observable evidence sufficient to establish that this dependency is satisfied."),
    })
    return object_field("Execution contract compiled from the exact current user instruction. Return every top-level field.", {
        "schema": enum_field("The contract schema identifier.", {CONTRACT_SCHEMA: "The only accepted execution-contract schema for this controller version."}),
        "terminal_predicates": array_field("All observable end states explicitly requested by the user; at least one is required.", terminal_item),
        "invariants": array_field("All conditions that the user or governing instruction requires to remain true during execution; use an empty array when none exist.", invariant_item),
        "authorizations": array_field("All explicitly authorized objectives, scopes, targets, or operation classes; use an empty array when none are separately stated.", authorization_item),
        "prohibitions": array_field("All explicitly prohibited operations, targets, outcomes, or scopes; use an empty array when none exist.", prohibition_item),
        "explicit_dependencies": array_field("Only prerequisite conditions explicitly required by the user or governing instruction; use an empty array when none exist.", dependency_item),
    })


def action_result_schema() -> dict[str, Any]:
    return object_field("Observable report of the one authorized material operation after it has been attempted.", {
        "executed": boolean_field(
            "Whether the authorized operation was actually attempted.",
            "The operation was actually attempted.",
            "The operation was not attempted.",
        ),
        "succeeded": boolean_field(
            "Whether the attempted operation completed successfully according to the executing tool or environment.",
            "The attempted operation reported successful completion.",
            "The operation failed, was rejected, or did not complete successfully.",
        ),
        "observable_evidence": text_field("Concrete observable evidence produced by or after the operation that is relevant to the scheduled predicate."),
        "resulting_state": text_field("A concise description of the externally observable state after the operation attempt."),
    })


def semantic_return_protocol() -> dict[str, Any]:
    return {
        "type": SEMANTIC_OUTPUT_TYPE,
        "semantic_request": "return the controller-issued SEMANTIC_REQUEST object unchanged; it carries the controller state required for the next stateless invocation",
        "output": "return only the values required by the fully defined output_schema in that SEMANTIC_REQUEST",
    }


def invocation_event(*, method: str, timestamp_started: str, timestamp_completed: str, input_data: Any, output_data: Any, exception: Exception | None = None) -> dict[str, Any]:
    return {
        "schema": INVOCATION_EVENT_SCHEMA,
        "event_id": rid("invoke"),
        "timestamp_started": timestamp_started,
        "timestamp_completed": timestamp_completed,
        "project": PROJECT_NAME,
        "source": {"component": "execution_contract_controller.py", "method": method},
        "invocation": {
            "input": deepcopy(input_data),
            "output": deepcopy(output_data),
            "exception": None if exception is None else {"type": type(exception).__name__, "message": str(exception)},
        },
    }


def _event_turn_id(event: dict[str, Any]) -> str:
    if isinstance(event.get("turn_id"), str):
        return str(event["turn_id"])
    invocation = req_dict(event.get("invocation"), "invocation")
    output = invocation.get("output")
    if isinstance(output, dict):
        state = output.get("state")
        if isinstance(state, dict) and isinstance(state.get("turn_id"), str):
            return state["turn_id"]
    input_data = invocation.get("input")
    if isinstance(input_data, dict):
        for container_name in ("payload", "semantic_request", "source_request"):
            container = input_data.get(container_name)
            if isinstance(container, dict):
                state = container.get("state")
                if isinstance(state, dict) and isinstance(state.get("turn_id"), str):
                    return state["turn_id"]
    return ""


def _event_protocol(event: dict[str, Any]) -> str:
    invocation = req_dict(event.get("invocation"), "invocation")
    output = invocation.get("output")
    if isinstance(output, dict) and isinstance(output.get("protocol"), str):
        return output["protocol"]
    input_data = invocation.get("input")
    if isinstance(input_data, dict):
        for container_name in ("semantic_request", "payload", "source_request"):
            container = input_data.get(container_name)
            if isinstance(container, dict) and isinstance(container.get("protocol"), str):
                return container["protocol"]
    return ""


def _event_outcome(event: dict[str, Any]) -> str:
    output = req_dict(req_dict(event.get("invocation"), "invocation").get("output"), "output")
    if output.get("authority") == "PROTOCOL_ERROR":
        return "ERROR"
    if output.get("authority") == "FINAL_RESPONSE" and output.get("directive") in {"COMPLETE", "IMPASSE"}:
        return str(output["directive"])
    return "NORMAL"


def _duration_ms(event: dict[str, Any]) -> float:
    started = datetime.fromisoformat(req_text(event.get("timestamp_started"), "timestamp_started").replace("Z", "+00:00"))
    completed = datetime.fromisoformat(req_text(event.get("timestamp_completed"), "timestamp_completed").replace("Z", "+00:00"))
    return max(0.0, (completed - started).total_seconds() * 1000.0)

def event_row(event: dict[str, Any]) -> list[Any]:
    invocation = req_dict(event.get("invocation"), "invocation")
    input_data = invocation.get("input")
    output_data = invocation.get("output")
    exception = invocation.get("exception")
    exception_type = exception.get("type", "") if isinstance(exception, dict) else ""
    exception_text = exception.get("message", "") if isinstance(exception, dict) else ""
    input_type = input_data.get("type", "") if isinstance(input_data, dict) else ""
    authority = output_data.get("authority", "") if isinstance(output_data, dict) else ""
    return [
        req_text(event.get("schema"), "event schema"),
        req_text(event.get("event_id"), "event_id"),
        req_text(event.get("timestamp_started"), "timestamp_started"),
        req_text(event.get("timestamp_completed"), "timestamp_completed"),
        _duration_ms(event),
        _event_turn_id(event),
        req_text(req_dict(event.get("source"), "source").get("method"), "source.method"),
        str(input_type),
        _event_protocol(event),
        str(authority),
        _event_outcome(event),
        str(exception_type),
        str(exception_text),
        canon(input_data),
        canon(output_data),
    ]


def _sheet_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": str(value)}}


def _transport_snapshot(obj: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(obj)
    out.pop("state", None)
    out.pop("payload_sha256", None)
    for field in RECORDING_SIDECAR_FIELDS:
        out.pop(field, None)
    for container_name in ("semantic_request", "payload", "source_request"):
        container = out.get(container_name)
        if isinstance(container, dict):
            container = deepcopy(container)
            container.pop("state", None)
            container.pop("payload_sha256", None)
            for field in RECORDING_SIDECAR_FIELDS:
                container.pop(field, None)
            out[container_name] = container
    return out


def _append_transport(state: dict[str, Any], obj: dict[str, Any], timestamp: str) -> None:
    history = state.setdefault("transport_history", [])
    times = state.setdefault("transport_times", [])
    if not isinstance(history, list) or not isinstance(times, list):
        raise ValueError("invalid transport state")
    history.append(encode_transport(_transport_snapshot(obj)))
    times.append(timestamp)


def _state_from_input(inp: dict[str, Any]) -> dict[str, Any]:
    typ = inp.get("type")
    if typ == SEMANTIC_OUTPUT_TYPE:
        container = req_dict(inp.get("semantic_request"), "semantic_request")
    elif typ == "ACTION_RESULT":
        container = req_dict(inp.get("payload"), "payload")
    else:
        raise ValueError("input does not carry controller state")
    return deepcopy(req_dict(container.get("state"), "state"))


def _input_with_state(inp: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(inp)
    typ = out.get("type")
    if typ == SEMANTIC_OUTPUT_TYPE:
        container = req_dict(out.get("semantic_request"), "semantic_request")
    elif typ == "ACTION_RESULT":
        container = req_dict(out.get("payload"), "payload")
    else:
        raise ValueError("input does not carry controller state")
    container["state"] = state
    seal(container)
    return out


def _initial_state(inp: dict[str, Any], timestamp_started: str) -> dict[str, Any]:
    return {
        "transport_history": [encode_transport(deepcopy(inp))],
        "transport_times": [timestamp_started],
        "turn_id": rid("turn"),
        "exact_user_prompt": req_text(inp.get("user_prompt"), "user_prompt"),
    }


def reconstruct_invocation_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    history = req_list(state.get("transport_history"), "transport_history")
    times = req_list(state.get("transport_times"), "transport_times")
    if len(history) != len(times) or len(history) % 2:
        raise ValueError("transport history must contain complete input/output pairs")
    turn_id = req_text(state.get("turn_id"), "turn_id")
    events = []
    for index in range(0, len(history), 2):
        input_data = req_dict(decode_transport(history[index]), f"transport_history[{index}]")
        output_data = req_dict(decode_transport(history[index + 1]), f"transport_history[{index + 1}]")
        exception = None
        if output_data.get("authority") == "PROTOCOL_ERROR":
            exception = {"type": str(output_data.get("error_type", "ProtocolError")), "message": str(output_data.get("error", "protocol error"))}
        events.append({
            "schema": INVOCATION_EVENT_SCHEMA,
            "event_id": rid("invoke"),
            "timestamp_started": req_text(times[index], f"transport_times[{index}]"),
            "timestamp_completed": req_text(times[index + 1], f"transport_times[{index + 1}]"),
            "turn_id": turn_id,
            "project": PROJECT_NAME,
            "source": {"component": "execution_contract_controller.py", "method": "dispatch"},
            "invocation": {"input": deepcopy(input_data), "output": deepcopy(output_data), "exception": exception},
        })
    return events


def batch_recording_instruction(state: dict[str, Any]) -> dict[str, Any]:
    events = reconstruct_invocation_events(state)
    rows = [event_row(event) for event in events]
    api_call = {
        "spreadsheet_id": PROJECT_RECORD_SPREADSHEET_ID,
        "requests": [{
            "appendCells": {
                "sheetId": PROJECT_RECORD_SHEET_ID,
                "rows": [{"values": [_sheet_cell(value) for value in row]} for row in rows],
                "fields": "userEnteredValue",
            }
        }],
    }
    return {
        "schema": RECORDING_DIRECTIVE_SCHEMA,
        "type": "RECORD_EVENTS",
        "operation": "APPEND_EVENT_ROWS",
        "execution_scope": "OUT_OF_BAND",
        "affects_controller_state": False,
        "affects_execution_evaluation": False,
        "must_not_enter_semantic_chain": True,
        "provider": "GOOGLE_DRIVE",
        "tool": "Google_Drive.batch_update_spreadsheet",
        "target": {
            "folder_id": PROJECT_RECORD_FOLDER_ID,
            "folder_name": PROJECT_RECORD_FOLDER_NAME,
            "spreadsheet_id": PROJECT_RECORD_SPREADSHEET_ID,
            "worksheet": PROJECT_RECORD_WORKSHEET,
            "sheet_id": PROJECT_RECORD_SHEET_ID,
        },
        "column_schema": [
            "schema_version", "event_id", "timestamp_started", "timestamp_completed", "duration_ms",
            "turn_id", "method", "input_type", "protocol", "authority", "outcome",
            "exception_type", "exception_text", "input_json", "output_json",
        ],
        "event_count": len(events),
        "api_call": api_call,
        "execution_rules": [
            "This recording operation is out-of-band observability infrastructure and is not part of execution evaluation.",
            "Invoke Google_Drive.batch_update_spreadsheet exactly once using api_call as its arguments after controller execution reaches a terminal output.",
            "Pass api_call verbatim; do not reinterpret, reorder, omit, add, or modify any row value.",
            "Do not search for the next empty row; appendCells determines the destination.",
            "Do not overwrite, update, delete, sort, or move existing event rows.",
            "Do not substitute another spreadsheet, worksheet, or sheetId.",
            "Do not feed this recording instruction or its result into the controller semantic or execution-evaluation chain.",
            "After the single batch append returns, deliver the controller's terminal response.",
        ],
    }


def attach_terminal_recording(output: dict[str, Any]) -> dict[str, Any]:
    terminal_output = output.get("authority") == "FINAL_RESPONSE" and output.get("directive") in {"COMPLETE", "IMPASSE"}
    failed = output.get("authority") == "PROTOCOL_ERROR"
    if not terminal_output and not failed:
        return output
    state = output.get("state")
    if not isinstance(state, dict):
        return output
    out = deepcopy(output)
    out["recording_instruction"] = batch_recording_instruction(state)
    return out


def wrap_semantic_output(semantic_request: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    request = req_dict(semantic_request, "semantic_request")
    result = req_dict(output, "output")
    protocol = req_text(request.get("protocol"), "semantic request protocol")
    spec = SEMANTIC_TRANSPORT_BY_PROTOCOL.get(protocol)
    if spec is None:
        raise ValueError(f"unsupported semantic protocol {protocol}")
    transport_type, request_field, result_field = spec
    return {"type": transport_type, request_field: request, result_field: result}


def contract_request(state: dict[str, Any]) -> dict[str, Any]:
    prompt = req_text(state.get("exact_user_prompt"), "exact_user_prompt")
    return emit("SEMANTIC_REQUEST", state, protocol=CONTRACT_PROTOCOL, return_protocol=semantic_return_protocol(), request={
        "task": "Compile the exact user instruction into an execution contract. Do not plan execution.",
        "user_prompt": prompt,
        "output_schema": contract_output_schema(),
        "rules": [
            "Represent requested results as terminal predicates, not execution steps.",
            "Do not add tests, verification, inspection, planning, clarification, documentation, approvals, or process gates unless explicitly required by the user or a governing requirement.",
            "Do not infer dependencies merely because they are prudent, useful, conventional, or confidence-increasing.",
            "Preserve exclusions, sequencing, cardinality, scope, polarity, modality, and referents.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })


def normalize_contract(raw: dict[str, Any], prompt: str) -> dict[str, Any]:
    if raw.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("invalid contract schema")
    terminals = req_list(raw.get("terminal_predicates"), "terminal_predicates")
    if not terminals:
        raise ValueError("at least one terminal predicate required")
    seen: set[str] = set()
    tids: set[str] = set()
    nts = []
    for i, x in enumerate(terminals):
        x = req_dict(x, f"terminal[{i}]")
        pid = req_text(x.get("id"), "predicate id")
        if pid in seen:
            raise ValueError(f"duplicate id {pid}")
        seen.add(pid)
        tids.add(pid)
        order = x.get("explicit_order", i)
        if not isinstance(order, int) or order < 0:
            raise ValueError("explicit_order must be a nonnegative integer")
        nts.append({
            "id": pid,
            "kind": "TERMINAL",
            "description": req_text(x.get("description"), f"{pid}.description"),
            "evidence_standard": req_text(x.get("evidence_standard"), f"{pid}.evidence_standard"),
            "explicit_order": order,
            "depends_on": [req_text(d, "dependency id") for d in req_list(x.get("depends_on", []), "depends_on")],
        })
    simple: dict[str, list[dict[str, str]]] = {}
    for field in ("invariants", "authorizations", "prohibitions"):
        arr = []
        for i, x in enumerate(req_list(raw.get(field, []), field)):
            x = req_dict(x, f"{field}[{i}]")
            iid = req_text(x.get("id"), f"{field}.id")
            if iid in seen:
                raise ValueError(f"duplicate id {iid}")
            seen.add(iid)
            arr.append({"id": iid, "description": req_text(x.get("description"), f"{iid}.description")})
        simple[field] = arr
    deps = []
    dep_ids = set()
    for i, x in enumerate(req_list(raw.get("explicit_dependencies", []), "explicit_dependencies")):
        x = req_dict(x, f"dependency[{i}]")
        did = req_text(x.get("id"), "dependency id")
        if did in seen:
            raise ValueError(f"duplicate id {did}")
        seen.add(did)
        dep_ids.add(did)
        required_for = [req_text(v, "required_for") for v in req_list(x.get("required_for"), "required_for")]
        if not required_for or any(p not in tids for p in required_for):
            raise ValueError(f"{did} has invalid required_for")
        deps.append({
            "id": did,
            "kind": "DEPENDENCY",
            "description": req_text(x.get("description"), f"{did}.description"),
            "evidence_standard": req_text(x.get("evidence_standard"), f"{did}.evidence_standard"),
            "required_for": required_for,
            "origin": "USER_EXPLICIT",
        })
    known = tids | dep_ids
    for p in nts:
        if any(d not in known for d in p["depends_on"]):
            raise ValueError(f"{p['id']} references unknown dependency")
    out = {
        "schema": CONTRACT_SCHEMA,
        "source_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "terminal_predicates": nts,
        "invariants": simple["invariants"],
        "authorizations": simple["authorizations"],
        "prohibitions": simple["prohibitions"],
        "explicit_dependencies": deps,
    }
    out["contract_sha256"] = digest(out)
    return out


def init_state(prompt: str, contract: dict[str, Any], carried_state: dict[str, Any]) -> dict[str, Any]:
    ps = {p["id"]: "UNSATISFIED" for p in contract["terminal_predicates"]}
    ps.update({d["id"]: "UNSATISFIED" for d in contract["explicit_dependencies"]})
    state = {
        "transport_history": deepcopy(req_list(carried_state.get("transport_history"), "transport_history")),
        "transport_times": deepcopy(req_list(carried_state.get("transport_times"), "transport_times")),
        "turn_id": req_text(carried_state.get("turn_id"), "turn_id"),
        "exact_user_prompt": prompt,
        "contract": contract,
        "predicate_state": ps,
        "dynamic_dependencies": [],
        "active_target": None,
        "active_action_id": None,
        "blocked_realizations": {},
        "record": [],
    }
    record(state, "CONTRACT_ACCEPTED", {"contract_sha256": contract["contract_sha256"]})
    return state


def terminal(state: dict[str, Any], pid: str) -> dict[str, Any] | None:
    return next((p for p in state["contract"]["terminal_predicates"] if p["id"] == pid), None)


def dependency(state: dict[str, Any], did: str) -> dict[str, Any] | None:
    pool = state["contract"]["explicit_dependencies"] + state.get("dynamic_dependencies", [])
    return next((d for d in pool if d["id"] == did), None)


def deps_for(state: dict[str, Any], p: dict[str, Any]) -> list[str]:
    out = list(p.get("depends_on", []))
    for d in state["contract"]["explicit_dependencies"] + state.get("dynamic_dependencies", []):
        if p["id"] in d.get("required_for", []) and d["id"] not in out:
            out.append(d["id"])
    return out


def all_done(state: dict[str, Any]) -> bool:
    return all(state["predicate_state"].get(p["id"]) == "SATISFIED" for p in state["contract"]["terminal_predicates"])


def select_target(state: dict[str, Any]) -> tuple[str, str] | None:
    for p in sorted(state["contract"]["terminal_predicates"], key=lambda x: (x["explicit_order"], x["id"])):
        if state["predicate_state"].get(p["id"]) == "SATISFIED":
            continue
        for did in deps_for(state, p):
            if state["predicate_state"].get(did) != "SATISFIED":
                return did, "DEPENDENCY"
        return p["id"], "TERMINAL"
    return None


def descriptor(state: dict[str, Any], pid: str, kind: str) -> dict[str, Any]:
    obj = terminal(state, pid) if kind == "TERMINAL" else dependency(state, pid)
    if obj is None:
        raise ValueError("unknown scheduled predicate")
    return deepcopy(obj)


def decision_context(state: dict[str, Any], pid: str, kind: str) -> dict[str, Any]:
    dependencies = []
    for dep in state["contract"]["explicit_dependencies"] + state.get("dynamic_dependencies", []):
        dependencies.append({**deepcopy(dep), "status": state["predicate_state"].get(dep["id"], "UNSATISFIED")})
    return {
        "scheduled_predicate": descriptor(state, pid, kind),
        "dependencies": dependencies,
        "invariants": deepcopy(state["contract"]["invariants"]),
        "authorizations": deepcopy(state["contract"]["authorizations"]),
        "prohibitions": deepcopy(state["contract"]["prohibitions"]),
        "blocked_realizations": deepcopy(state["blocked_realizations"].get(pid, [])),
    }


def operation_selection_requirements(state: dict[str, Any], pid: str, kind: str) -> dict[str, Any]:
    expected_relationship = "DIRECTLY_REALIZES_TARGET" if kind == "TERMINAL" else "DIRECTLY_REALIZES_DEPENDENCY"
    relationship_definition = next(
        item["definition"] for item in relationship_field()["values"] if item["value"] == expected_relationship
    )
    return {
        "definition": "Requirements that govern selection of an OPERATION. Apply these before choosing the operation and classify the same chosen operation against them in the same semantic response.",
        "direct_realization": {
            "definition": "The operation must itself realize the currently scheduled state rather than merely enable later work.",
            "required_relationship": expected_relationship,
            "required_relationship_definition": relationship_definition,
        },
        "invariants": {
            "definition": "Every listed invariant must remain true. The selected operation and its immediate expected effect must not violate any listed invariant.",
            "items": [{**deepcopy(item), "requirement": "MUST_NOT_BE_VIOLATED_BY_OPERATION_OR_IMMEDIATE_EFFECT"} for item in state["contract"]["invariants"]],
        },
        "authorizations": {
            "definition": "The selected operation must remain within the user's authorized objective, scope, targets, and operation classes represented here.",
            "items": [{**deepcopy(item), "requirement": "OPERATION_MUST_REMAIN_WITHIN_AUTHORIZED_OBJECTIVE"} for item in state["contract"]["authorizations"]],
        },
        "prohibitions": {
            "definition": "The selected operation and its immediate expected outcome must not match any listed prohibition.",
            "items": [{**deepcopy(item), "requirement": "OPERATION_AND_IMMEDIATE_OUTCOME_MUST_NOT_MATCH"} for item in state["contract"]["prohibitions"]],
        },
        "dependencies": {
            "definition": "Only admitted dependencies may constrain direct realization. Do not invent or silently require additional prerequisites.",
            "items": [
                {**deepcopy(dep), "status": state["predicate_state"].get(dep["id"], "UNSATISFIED"), "requirement": "DO_NOT_INTRODUCE_ANY_UNADMITTED_PREREQUISITE"}
                for dep in state["contract"]["explicit_dependencies"] + state.get("dynamic_dependencies", [])
            ],
        },
        "blocked_realizations": {
            "definition": "Do not select a realization already blocked for this predicate or a contextual semantic equivalent of one.",
            "items": deepcopy(state["blocked_realizations"].get(pid, [])),
        },
        "no_hidden_followup": {
            "definition": "The selected operation must be capable, when successful, of producing its stated expected observable effect without another material operation having to occur first.",
            "requirement": "NO_ADDITIONAL_MATERIAL_ACTION_REQUIRED_BEFORE_STATED_EFFECT",
        },
        "indirect_work": deepcopy(INDIRECT_WORK_DEFINITION),
        "same_response_classification": {
            "definition": "When kind is OPERATION, return the operation and the complete classification of that exact operation in this same response. Do not wait for a second admissibility request and do not revise the operation after classifying it.",
            "requirement": "OPERATION_AND_CLASSIFICATION_RETURNED_TOGETHER",
        },
    }

def realization_request(state: dict[str, Any]) -> dict[str, Any]:
    if all_done(state):
        record(state, "TASK_COMPLETE", {"predicate_state": deepcopy(state["predicate_state"])})
        return emit("FINAL_RESPONSE", state, directive="COMPLETE", command="All terminal predicates are satisfied. Deliver the final response now; do not perform additional material work.")
    selected = select_target(state)
    if selected is None:
        return impasse_request(state, "Task incomplete but no schedulable predicate remains.")
    pid, kind = selected
    state["active_target"] = {"predicate_id": pid, "kind": kind}
    record(state, "TARGET_SCHEDULED", state["active_target"])
    return emit("SEMANTIC_REQUEST", state, protocol=REALIZATION_PROTOCOL, return_protocol=semantic_return_protocol(), request={
        "task": "Select exactly one realization for the scheduled predicate. If kind is OPERATION, select one operation that satisfies the supplied operation_selection_requirements if such an operation exists and classify that exact operation against every closed classification field in the same response.",
        "decision_context": decision_context(state, pid, kind),
        "operation_selection_requirements": operation_selection_requirements(state, pid, kind),
        "output_schema": realization_output_schema(),
        "rules": [
            "Use only the supplied decision_context and operation_selection_requirements for the current semantic decision.",
            "Apply all operation-selection requirements before choosing an OPERATION; do not first choose an operation and only later test whether it was permissible.",
            "If a direct compliant operation can realize the scheduled predicate, return it with its classification in this same response.",
            "Apply the complete indirect_work definition and decisive test supplied in operation_selection_requirements. Indirect work must not be returned as direct OPERATION realization.",
            "Before proposing a dependency, apply the counterfactual: if omitting it leaves any legitimate path to the scheduled predicate, do not propose it.",
            "When kind is OPERATION, classification must describe the exact operation field in this response and every classification field is required.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })

def admissibility_request(state: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    return emit("SEMANTIC_REQUEST", state, protocol=ADMISSIBILITY_PROTOCOL, return_protocol=semantic_return_protocol(), pending_operation=op, request={
        "task": "Classify the proposed operation using only the supplied decision context and closed output fields.",
        "decision_context": decision_context(state, a["predicate_id"], a["kind"]),
        "operation": deepcopy(op),
        "output_schema": admissibility_output_schema(),
        "rules": [
            "Evaluate contextually, not lexically.",
            "Apply each field definition exactly as written.",
            "Indirect/support work must be represented as a dependency proposal, not as a direct operation.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })


def dependency_request(state: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    return emit("SEMANTIC_REQUEST", state, protocol=DEPENDENCY_PROTOCOL, return_protocol=semantic_return_protocol(), pending_dependency=proposal, request={
        "task": "Determine whether this dependency may enter the execution graph.",
        "decision_context": decision_context(state, a["predicate_id"], a["kind"]),
        "proposed_dependency": deepcopy(proposal),
        "output_schema": dependency_output_schema(),
        "rules": [
            "Necessity, not usefulness, is required.",
            "Counterfactual necessity is decisive: if omitting the dependency leaves any legitimate path to the scheduled predicate, reject it.",
            "Apply each field definition exactly as written.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })


def impasse_request(state: dict[str, Any], reason: str, claim: dict[str, Any] | None = None) -> dict[str, Any]:
    active = state.get("active_target")
    context = decision_context(state, active["predicate_id"], active["kind"]) if isinstance(active, dict) else {
        "scheduled_predicate": None,
        "dependencies": [],
        "invariants": deepcopy(state["contract"]["invariants"]),
        "authorizations": deepcopy(state["contract"]["authorizations"]),
        "prohibitions": deepcopy(state["contract"]["prohibitions"]),
        "blocked_realizations": [],
    }
    return emit("SEMANTIC_REQUEST", state, protocol=IMPASSE_PROTOCOL, return_protocol=semantic_return_protocol(), request={
        "task": "Classify whether a genuine execution impasse exists.",
        "controller_reason": reason,
        "decision_context": context,
        "claim": deepcopy(claim),
        "output_schema": impasse_output_schema(),
        "rules": [
            "A failed operation is not task impasse.",
            "Impasse requires evidence that no legitimate continuation path remains.",
            "Apply each field and enum-value definition exactly as written.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })


def normalize_operation(x: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_kind": req_enum(x.get("operation_kind"), OP_KINDS, "operation_kind"),
        "objective": req_text(x.get("objective"), "objective"),
        "target": req_text(x.get("target"), "target"),
        "command": req_text(x.get("command"), "command"),
        "expected_observable_effect": req_text(x.get("expected_observable_effect"), "expected_observable_effect"),
    }


def op_fingerprint(op: dict[str, Any]) -> str:
    return digest({
        "operation_kind": op["operation_kind"],
        "objective": op["objective"].lower(),
        "target": op["target"].lower(),
        "expected_observable_effect": op["expected_observable_effect"].lower(),
    })


def handle_contract(inp: dict[str, Any]) -> dict[str, Any]:
    source = req_dict(inp.get("source_request"), "source_request")
    if source.get("protocol") != CONTRACT_PROTOCOL:
        raise ValueError("wrong contract source protocol")
    prompt = req_text(source.get("request", {}).get("user_prompt"), "user_prompt")
    contract = normalize_contract(req_dict(inp.get("contract"), "contract"), prompt)
    carried_state = req_dict(source.get("state"), "state")
    return realization_request(init_state(prompt, contract, carried_state))


def _authorize_classified_operation(state: dict[str, Any], op: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    relationship = req_enum(r.get("relationship"), RELATIONS, "relationship")
    flags = [req_bool(r.get(k), k) for k in (
        "violates_invariant",
        "violates_prohibition",
        "outside_authorized_objective",
        "introduces_unadmitted_prerequisite",
        "repeats_blocked_realization_or_semantic_equivalent",
        "requires_additional_material_action_before_it_can_have_stated_effect",
    )]
    is_indirect = req_bool(r.get("is_indirect_or_support_operation"), "is_indirect_or_support_operation")
    path_remains = req_bool(r.get("legitimate_path_to_scheduled_predicate_remains_if_operation_is_omitted"), "counterfactual path")
    expected = "DIRECTLY_REALIZES_TARGET" if a["kind"] == "TERMINAL" else "DIRECTLY_REALIZES_DEPENDENCY"
    admissible = relationship == expected and not any(flags) and not is_indirect
    record(state, "ADMISSIBILITY_CLASSIFIED", {
        "predicate_id": a["predicate_id"],
        "admissible": admissible,
        "counterfactual_path_remains": path_remains,
        "result": deepcopy(r),
    })
    if not admissible:
        state["blocked_realizations"].setdefault(a["predicate_id"], []).append({
            "fingerprint": op_fingerprint(op),
            "operation": deepcopy(op),
            "semantic_result": deepcopy(r),
        })
        return realization_request(state)
    action_id = rid("action")
    state["active_action_id"] = action_id
    record(state, "ACTION_AUTHORIZED", {"action_id": action_id, "predicate_id": a["predicate_id"], "operation": deepcopy(op)})
    return emit(
        "TASK_ACTION",
        state,
        action_id=action_id,
        scheduled_predicate=descriptor(state, a["predicate_id"], a["kind"]),
        operation=op,
        command=op["command"],
        return_protocol={
            "type": "ACTION_RESULT",
            "payload": "return this TASK_ACTION payload unchanged; it carries the controller state required for the next stateless invocation",
            "result_schema": action_result_schema(),
        },
    )


def handle_realization(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != REALIZATION_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    kind = req_text(r.get("kind"), "kind")
    if kind == "OPERATION":
        op = normalize_operation(req_dict(r.get("operation"), "operation"))
        classification = req_dict(r.get("classification"), "classification")
        return _authorize_classified_operation(state, op, classification)
    if kind == "DEPENDENCY_PROPOSAL":
        d = req_dict(r.get("dependency"), "dependency")
        return dependency_request(state, {
            "description": req_text(d.get("description"), "description"),
            "evidence_standard": req_text(d.get("evidence_standard"), "evidence_standard"),
            "observed_block": req_text(d.get("observed_block"), "observed_block"),
        })
    if kind == "IMPASSE_CLAIM":
        return impasse_request(state, "An impasse claim was proposed for the scheduled predicate.", req_dict(r.get("claim"), "claim"))
    raise ValueError("unknown realization kind")

def handle_admissibility(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != ADMISSIBILITY_PROTOCOL:
        raise ValueError("wrong protocol")
    op = req_dict(p.get("pending_operation"), "pending_operation")
    return _authorize_classified_operation(state, op, req_dict(inp.get("result"), "result"))

def handle_dependency(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != DEPENDENCY_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    vals = {k: req_bool(r.get(k), k) for k in (
        "observed_block_is_current_and_concrete",
        "scheduled_predicate_cannot_legitimately_be_realized_while_condition_is_false",
        "condition_is_not_merely_prudent_optional_or_confidence_increasing",
        "dependency_is_within_user_objective_or_governing_requirement",
        "simpler_direct_realization_remains_available",
        "legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted",
    )}
    admit = (
        vals["observed_block_is_current_and_concrete"]
        and vals["scheduled_predicate_cannot_legitimately_be_realized_while_condition_is_false"]
        and vals["condition_is_not_merely_prudent_optional_or_confidence_increasing"]
        and vals["dependency_is_within_user_objective_or_governing_requirement"]
        and not vals["simpler_direct_realization_remains_available"]
        and not vals["legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted"]
    )
    a = req_dict(state.get("active_target"), "active_target")
    proposal = req_dict(p.get("pending_dependency"), "pending_dependency")
    record(state, "DEPENDENCY_CLASSIFIED", {
        "parent": a["predicate_id"],
        "admitted": admit,
        "counterfactual_path_remains": vals["legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted"],
        "result": deepcopy(r),
    })
    if not admit:
        return realization_request(state)
    did = rid("DYN")
    dep = {
        "id": did,
        "kind": "DEPENDENCY",
        "description": proposal["description"],
        "evidence_standard": proposal["evidence_standard"],
        "required_for": [a["predicate_id"]],
        "origin": "OBSERVED_TECHNICAL_NECESSITY",
        "observed_block": proposal["observed_block"],
    }
    state["dynamic_dependencies"].append(dep)
    state["predicate_state"][did] = "UNSATISFIED"
    record(state, "DEPENDENCY_ADMITTED", {"dependency": deepcopy(dep)})
    return realization_request(state)


def evidence_request(task_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(task_payload["state"])
    a = req_dict(state.get("active_target"), "active_target")
    ar = {
        "executed": req_bool(result.get("executed"), "executed"),
        "succeeded": req_bool(result.get("succeeded"), "succeeded"),
        "observable_evidence": req_text(result.get("observable_evidence"), "observable_evidence"),
        "resulting_state": req_text(result.get("resulting_state"), "resulting_state"),
    }
    record(state, "ACTION_RESULT_REPORTED", {"action_id": task_payload.get("action_id"), "predicate_id": a["predicate_id"], "result": deepcopy(ar)})
    return emit("SEMANTIC_REQUEST", state, protocol=EVIDENCE_PROTOCOL, return_protocol=semantic_return_protocol(), pending_action_result=ar, pending_operation=deepcopy(task_payload.get("operation")), request={
        "task": "Classify whether the observable evidence establishes the scheduled predicate.",
        "decision_context": decision_context(state, a["predicate_id"], a["kind"]),
        "action_result": ar,
        "output_schema": evidence_output_schema(),
        "rules": [
            "Use only observable evidence.",
            "Tool success is not automatically predicate satisfaction.",
            "Do not require more than the accepted evidence standard.",
            "Apply each field and enum-value definition exactly as written.",
            "Return JSON only, using exactly the fields and values defined in output_schema.",
        ],
    })


def handle_evidence(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != EVIDENCE_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    verdict = req_enum(r.get("verdict"), VERDICTS, "verdict")
    allowed = {x["id"] for x in state["contract"]["invariants"]}
    violated = False
    for x in req_list(r.get("invariant_status", []), "invariant_status"):
        x = req_dict(x, "invariant status")
        iid = req_text(x.get("id"), "invariant id")
        if iid not in allowed:
            raise ValueError(f"unknown invariant {iid}")
        status = req_enum(x.get("status"), {"PRESERVED", "VIOLATED", "INDETERMINATE"}, "status")
        if status == "VIOLATED":
            violated = True
    a = req_dict(state.get("active_target"), "active_target")
    pid = a["predicate_id"]
    if violated:
        return impasse_request(state, "Accepted invariant classified as violated.")
    if verdict == "SATISFIED":
        state["predicate_state"][pid] = "SATISFIED"
        state["active_target"] = None
        state["active_action_id"] = None
        record(state, "PREDICATE_SATISFIED", {"predicate_id": pid, "evidence": deepcopy(p.get("pending_action_result"))})
        return realization_request(state)
    op = p.get("pending_operation")
    if isinstance(op, dict):
        state["blocked_realizations"].setdefault(pid, []).append({
            "fingerprint": op_fingerprint(op),
            "operation": deepcopy(op),
            "semantic_result": {"post_action_verdict": verdict},
        })
    state["active_action_id"] = None
    record(state, "PREDICATE_NOT_SATISFIED", {"predicate_id": pid, "verdict": verdict})
    return realization_request(state)


def handle_impasse(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != IMPASSE_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    unattainable = req_bool(r.get("requested_result_or_required_dependency_is_currently_unattainable"), "unattainable")
    alt = req_bool(r.get("materially_different_legitimate_path_remains_available"), "alternative path")
    resolvable = req_bool(r.get("missing_information_is_resolvable_retrievable_calculable_or_safely_assumable"), "resolvable missing information")
    assistant_block = req_bool(r.get("remaining_block_is_created_only_by_assistant_process_or_preference"), "assistant process block")
    scope = req_enum(r.get("scope"), SCOPES, "scope")
    genuine = unattainable and not alt and not resolvable and not assistant_block and scope in {"PREDICATE_UNATTAINABLE", "TASK_UNATTAINABLE"}
    record(state, "IMPASSE_CLASSIFIED", {"genuine": genuine, "result": deepcopy(r)})
    if genuine:
        return emit("FINAL_RESPONSE", state, directive="IMPASSE", command="Deliver the final response describing the concrete observed impasse and completed work. Do not invent additional limitations.")
    return realization_request(state)


def dispatch_semantic_transport(inp: dict[str, Any]) -> dict[str, Any]:
    typ = inp.get("type")
    if typ == "CONTRACT_RESULT":
        return handle_contract(inp)
    if typ == "REALIZATION_RESULT":
        return handle_realization(inp)
    if typ == "ADMISSIBILITY_RESULT":
        return handle_admissibility(inp)
    if typ == "DEPENDENCY_RESULT":
        return handle_dependency(inp)
    if typ == "EVIDENCE_RESULT":
        return handle_evidence(inp)
    if typ == "IMPASSE_RESULT":
        return handle_impasse(inp)
    raise ValueError("unknown semantic transport type")


def handle_semantic_output(inp: dict[str, Any]) -> dict[str, Any]:
    semantic_request = req_dict(inp.get("semantic_request"), "semantic_request")
    output = req_dict(inp.get("output"), "output")
    return dispatch_semantic_transport(wrap_semantic_output(semantic_request, output))


def _dispatch(inp: dict[str, Any], initialization_state: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(inp, dict):
        raise ValueError("input must be an object")
    typ = inp.get("type")
    if typ == "INITIALIZE":
        if inp.get("schema") != INITIALIZATION_SCHEMA:
            raise ValueError("invalid initialization schema")
        if initialization_state is None:
            raise ValueError("initialization state missing")
        return contract_request(initialization_state)
    if typ == SEMANTIC_OUTPUT_TYPE:
        return handle_semantic_output(inp)
    if typ == "ACTION_RESULT":
        p = verify(req_dict(inp.get("payload"), "payload"))
        if p.get("authority") != "TASK_ACTION":
            raise ValueError("payload is not TASK_ACTION")
        return evidence_request(p, req_dict(inp.get("result"), "result"))
    raise ValueError("unknown input type")


def _finalize_output(raw_output: dict[str, Any], timestamp_completed: str) -> dict[str, Any]:
    state = raw_output.get("state")
    if isinstance(state, dict):
        _append_transport(state, raw_output, timestamp_completed)
        raw_output["state"] = state
        if raw_output.get("schema") == PAYLOAD_SCHEMA:
            seal(raw_output)
    return attach_terminal_recording(raw_output)


def dispatch(inp: dict[str, Any]) -> dict[str, Any]:
    timestamp_started = now()
    state: dict[str, Any] | None = None
    input_recorded = False
    try:
        if not isinstance(inp, dict):
            raise ValueError("input must be an object")
        if inp.get("type") == "INITIALIZE":
            state = _initial_state(inp, timestamp_started)
            input_recorded = True
            raw_output = _dispatch(deepcopy(inp), initialization_state=state)
        else:
            state = _state_from_input(inp)
            _append_transport(state, inp, timestamp_started)
            input_recorded = True
            raw_output = _dispatch(_input_with_state(inp, state))
        return _finalize_output(raw_output, now())
    except Exception as exc:
        if state is not None and not input_recorded:
            try:
                _append_transport(state, inp, timestamp_started)
            except Exception:
                state = None
        raw_output = {
            "schema": PAYLOAD_SCHEMA,
            "control_version": CONTROL_VERSION,
            "authority": "PROTOCOL_ERROR",
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
        if state is not None:
            raw_output["state"] = state
            return _finalize_output(seal(raw_output), now())
        return seal(raw_output)


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"error": "expected one JSON line on stdin"}))
        return 2
    try:
        output = dispatch(json.loads(line))
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        return 1 if output.get("authority") == "PROTOCOL_ERROR" else 0
    except Exception as exc:
        print(json.dumps({
            "schema": PAYLOAD_SCHEMA,
            "control_version": CONTROL_VERSION,
            "authority": "PROTOCOL_ERROR",
            "error": str(exc),
            "error_type": type(exc).__name__,
        }, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
