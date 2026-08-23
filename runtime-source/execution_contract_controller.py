#!/usr/bin/env python3
"""Deterministic execution-contract controller with just-in-time execution knowledge retrieval."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTROL_VERSION = 2
INITIALIZATION_SCHEMA = "execution-contract-controller-initialization-v1"
PAYLOAD_SCHEMA = "execution-contract-controller-payload-v1"
CONTRACT_SCHEMA = "execution-contract-v1"
KNOWLEDGE_SCHEMA = "execution-knowledge-base-v1"
INVOCATION_EVENT_SCHEMA = "chatgpt-controller-invocation-event-v1"
RECORDING_DIRECTIVE_SCHEMA = "chatgpt-event-recording-instruction-v1"
RECORDING_SIDECAR_FIELDS = {"recording_event", "recording_instruction"}

PROJECT_NAME = "Execution Contract Persistence"
PROJECT_RECORD_FOLDER_ID = "1uTw38OhZZbZVRryd_EaVgkD4Es2sDlKn"
PROJECT_RECORD_FOLDER_NAME = "Execution Contract Persistence"
PROJECT_RECORD_SPREADSHEET_ID = "19dQDq76evR4c9BeWyzlA-sY5aUVG9iTnBlgUN4dODmI"
PROJECT_RECORD_WORKSHEET = "Events"
PROJECT_RECORD_SHEET_ID = 1930933064

KNOWLEDGE_BASE_PATH = Path(__file__).with_name("execution_knowledge_base.json")
RUNTIME_MANIFEST_PATH = Path("/mnt/data/execution_runtime/runtime_manifest.json")
RECORDER_MAX_DEPTH = 18
RECORDER_MAX_CELL_CHARS = 45000
RECORDER_OMIT_KEYS = {"state", "transport_history", "recording_event", "recording_instruction"}
KNOWLEDGE_TYPES = {"invariant", "action", "procedure", "heuristic", "pattern", "capability"}

CONTRACT_PROTOCOL = "compile-contract-v1"
KNOWLEDGE_QUERY_PROTOCOL = "select-execution-knowledge-query-v1"
REALIZATION_PROTOCOL = "realize-transition-v2"
EVIDENCE_PROTOCOL = "classify-evidence-v1"
IMPASSE_PROTOCOL = "classify-impasse-v1"
SEMANTIC_OUTPUT_TYPE = "SEMANTIC_OUTPUT"

SEMANTIC_TRANSPORT_BY_PROTOCOL = {
    CONTRACT_PROTOCOL: ("CONTRACT_RESULT", "source_request", "contract"),
    KNOWLEDGE_QUERY_PROTOCOL: ("KNOWLEDGE_QUERY_RESULT", "payload", "result"),
    REALIZATION_PROTOCOL: ("REALIZATION_RESULT", "payload", "result"),
    EVIDENCE_PROTOCOL: ("EVIDENCE_RESULT", "payload", "result"),
    IMPASSE_PROTOCOL: ("IMPASSE_RESULT", "payload", "result"),
}

VERDICTS = {"SATISFIED", "NOT_SATISFIED", "INDETERMINATE"}
SCOPES = {"TRANSITION_ONLY", "PREDICATE_UNATTAINABLE", "TASK_UNATTAINABLE", "UNKNOWN"}
OP_KINDS = {"READ", "SEARCH", "CALCULATE", "TRANSFORM", "MUTATE", "CREATE", "DELETE", "SEND", "EXECUTE", "WAIT", "OTHER"}
ACTION_ROLES = {"TARGET", "DEPENDENCY"}

BEHAVIORAL_INSTRUCTIONS = [
    "Treat the accepted execution contract as the authoritative representation of the current user instruction.",
    "Before each materially new action, use the execution knowledge base unless the action is already inside a selected deterministic action or closed procedure.",
    "Retrieve context just in time; do not preload or reconstruct the entire execution knowledge base.",
    "Interpret knowledge records by type: invariants govern; deterministic actions and procedures define known execution paths; heuristics narrow strategy; patterns suggest compositions; capabilities describe demonstrated primitives.",
    "Prefer a directly applicable deterministic action or established procedure when it satisfies the scheduled state.",
    "When no complete action or procedure applies, use retrieved heuristics to narrow the strategy and retrieved capabilities or patterns to compose the next operation.",
    "Do not add verification, inspection, planning, setup, or confidence-increasing work merely by convention. Perform it when the user requires it, a governing condition requires it, or the current state makes it genuinely necessary.",
    "Once a deterministic action or closed procedure is selected, execute its defined steps without recursively reopening semantic search inside each step; reopen only on an explicit branch, failure, missing required input, objective change, or inability of the procedure to satisfy the target.",
    "Use known identifiers, paths, receipts, and state rather than rediscovering them.",
    "Hard invariants, explicit prohibitions, and authorized objective boundaries always govern retrieved guidance.",
    "When an action is authorized, perform it and report observable evidence before selecting another material action.",
    "Once all accepted terminal predicates are satisfied, do not invent additional material work.",
]

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

def text_field(definition: str) -> dict[str, Any]:
    return {"type": "string", "definition": definition}

def integer_field(definition: str) -> dict[str, Any]:
    return {"type": "integer", "definition": definition}

def boolean_field(definition: str, true_definition: str, false_definition: str) -> dict[str, Any]:
    return {"type": "boolean", "definition": definition, "true_definition": true_definition, "false_definition": false_definition}

def enum_field(definition: str, values: dict[str, str]) -> dict[str, Any]:
    return {"type": "enum", "definition": definition, "values": [{"value": k, "definition": v} for k, v in values.items()]}

def array_field(definition: str, items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "definition": definition, "items": items}

def object_field(definition: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "definition": definition, "fields": fields}

def contract_output_schema() -> dict[str, Any]:
    terminal_item = object_field("One observable end state explicitly requested by the user.", {
        "id": text_field("Unique stable identifier within the contract, such as P1."),
        "description": text_field("Observable requested end state as a condition that can become true or false."),
        "evidence_standard": text_field("Minimum observable evidence sufficient to establish satisfaction."),
        "explicit_order": integer_field("Zero-based explicit order; use source order when no stronger order is stated."),
        "depends_on": array_field("Identifiers of explicit dependencies required before this terminal predicate.", text_field("Dependency identifier.")),
    })
    simple_item = object_field("One governing item.", {
        "id": text_field("Unique stable identifier."),
        "description": text_field("The governing condition or scope."),
    })
    dependency_item = object_field("One prerequisite explicitly required by the user or governing instruction.", {
        "id": text_field("Unique stable identifier."),
        "description": text_field("Condition that must become true."),
        "required_for": array_field("Terminal predicate identifiers requiring this dependency.", text_field("Terminal identifier.")),
        "evidence_standard": text_field("Minimum observable evidence sufficient to establish this dependency."),
    })
    return {
        "type": "object",
        "definition": "Execution contract containing only user-requested terminal states and governing requirements.",
        "fields": {
            "schema": {"type": "const", "value": CONTRACT_SCHEMA},
            "terminal_predicates": array_field("Requested observable end states.", terminal_item),
            "invariants": array_field("Conditions that must remain true throughout execution.", simple_item),
            "authorizations": array_field("Authorized objectives, targets, scopes, or operation classes.", simple_item),
            "prohibitions": array_field("Explicitly prohibited operations, targets, or outcomes.", simple_item),
            "explicit_dependencies": array_field("Only prerequisites explicitly required by user or governing instruction.", dependency_item),
        },
    }

def knowledge_query_output_schema() -> dict[str, Any]:
    return object_field("A just-in-time retrieval query for execution knowledge relevant to the next action decision.", {
        "query": text_field("Natural-language description of the intended next-action outcome and current situation. Describe what must be accomplished; include known state that changes applicability."),
        "types": array_field("Knowledge record types worth retrieving. Include action/procedure when an established path may exist; include heuristic when strategy choice matters; include capability/pattern when implementation is not already grounded.", enum_field("Knowledge type.", {
            "invariant": "Hard execution rule.",
            "action": "Deterministic executable operation.",
            "procedure": "Established multi-step workflow.",
            "heuristic": "Preferred strategy or decision rule.",
            "pattern": "Known useful composition.",
            "capability": "Demonstrated primitive operation.",
        })),
        "reason": text_field("Why these knowledge classes are relevant to selecting the next material action."),
    })

def operation_kind_field() -> dict[str, Any]:
    return enum_field("Elementary class of material operation.", {
        "READ": "Retrieve existing information from a known source.",
        "SEARCH": "Discover or locate information or resources whose exact identity/location is unknown.",
        "CALCULATE": "Derive a deterministic result from available inputs.",
        "TRANSFORM": "Rewrite, parse, convert, summarize, or reorganize supplied information.",
        "MUTATE": "Modify an existing persistent or external object.",
        "CREATE": "Create a new persistent or external object.",
        "DELETE": "Remove an existing persistent or external object.",
        "SEND": "Transmit information or an object externally.",
        "EXECUTE": "Run a program, workflow, script, or job.",
        "WAIT": "Defer progress pending time or external change.",
        "OTHER": "Material operation not accurately described by another class.",
    })

def operation_output_schema() -> dict[str, Any]:
    return object_field("One concrete material operation.", {
        "operation_kind": operation_kind_field(),
        "objective": text_field("Immediate result this operation is intended to accomplish."),
        "target": text_field("Concrete object, resource, state, or subject acted on."),
        "command": text_field("Exact instruction to execute."),
        "expected_observable_effect": text_field("Observable effect expected immediately from success."),
    })

def hard_conflict_schema() -> dict[str, Any]:
    return object_field("Minimal hard-boundary classification of the exact selected action or operation.", {
        "violates_invariant": boolean_field("Would the action violate an accepted invariant?", "At least one invariant would be violated.", "No accepted invariant would be violated."),
        "violates_prohibition": boolean_field("Would the action violate an explicit prohibition?", "At least one prohibition would be violated.", "No explicit prohibition would be violated."),
        "outside_authorized_objective": boolean_field("Would the action pursue an objective outside the accepted user task/authorization?", "The action is outside the authorized objective.", "The action remains within the authorized objective."),
        "conflicting_ids": array_field("Identifiers of governing items that conflict with the action; empty when none.", text_field("Exact governing identifier.")),
    })

def realization_output_schema() -> dict[str, Any]:
    return object_field("Select the next action after consuming retrieved execution knowledge.", {
        "kind": enum_field("Realization form.", {
            "KNOWLEDGE_ACTION": "Select a retrieved deterministic action or procedure and bind its arguments.",
            "OPERATION": "Compose a concrete operation using retrieved heuristics, patterns, capabilities, and current state.",
            "IMPASSE_CLAIM": "Claim that no legitimate continuation path remains.",
        }),
        "role": enum_field("Whether the selected action itself targets the scheduled predicate or realizes a necessary intermediate condition.", {
            "TARGET": "The action is intended to establish the currently scheduled predicate.",
            "DEPENDENCY": "The action realizes a genuinely necessary intermediate condition; after it completes, the same scheduled predicate remains active.",
        }),
        "knowledge_id": text_field("Required for KNOWLEDGE_ACTION: exact id of the retrieved action or procedure. For OPERATION use NONE."),
        "arguments": {"type": "object", "definition": "Argument bindings for KNOWLEDGE_ACTION. Keys must match the selected record's required inputs. For OPERATION return an empty object.", "additional_properties": True},
        "operation": {**operation_output_schema(), "definition": "Required for OPERATION; for KNOWLEDGE_ACTION omit or return null according to transport support."},
        "knowledge_used": array_field("Ids of retrieved records materially used to select or compose this realization.", text_field("Exact retrieved knowledge id.")),
        "necessity_basis": text_field("For DEPENDENCY role, state the current concrete reason this intermediate action is necessary. For TARGET role use DIRECT_TARGET."),
        "hard_conflict": hard_conflict_schema(),
        "claim": object_field("For IMPASSE_CLAIM, concrete observed basis; otherwise use an empty object.", {
            "description": text_field("Concrete factual basis for claiming no legitimate continuation path remains."),
        }),
    })

def evidence_output_schema() -> dict[str, Any]:
    return object_field("Classification of action evidence against the scheduled predicate.", {
        "verdict": enum_field("Whether observable evidence establishes the scheduled predicate.", {
            "SATISFIED": "Evidence is sufficient to establish the scheduled predicate.",
            "NOT_SATISFIED": "Evidence establishes the scheduled predicate is not yet true.",
            "INDETERMINATE": "Evidence is insufficient to decide.",
        }),
        "invariant_status": array_field("Status for each accepted invariant.", object_field("One invariant status.", {
            "id": text_field("Exact invariant id."),
            "status": enum_field("Invariant status after the action.", {
                "PRESERVED": "Evidence establishes preservation.",
                "VIOLATED": "Evidence establishes violation.",
                "INDETERMINATE": "Evidence is insufficient.",
            }),
        })),
    })

def impasse_output_schema() -> dict[str, Any]:
    return object_field("Closed classification of whether a genuine execution impasse exists.", {
        "requested_result_or_required_dependency_is_currently_unattainable": boolean_field("Is the relevant remaining state currently unattainable?", "Unattainable.", "Not established unattainable."),
        "materially_different_legitimate_path_remains_available": boolean_field("Does another legitimate path remain?", "Another path remains.", "No materially different path remains."),
        "missing_information_is_resolvable_retrievable_calculable_or_safely_assumable": boolean_field("Can missing information be resolved?", "Resolvable.", "Not resolvable."),
        "remaining_block_is_created_only_by_assistant_process_or_preference": boolean_field("Is the block assistant-created process/preference?", "Assistant-created.", "Not merely assistant-created."),
        "scope": enum_field("Maximum scope of unattainability.", {
            "TRANSITION_ONLY": "Only one transition is blocked.",
            "PREDICATE_UNATTAINABLE": "The scheduled predicate has no legitimate attainable path.",
            "TASK_UNATTAINABLE": "The remaining contract has no attainable completion path.",
            "UNKNOWN": "Scope is not established.",
        }),
    })

def action_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "fields": {
            "executed": {"type": "boolean"},
            "succeeded": {"type": "boolean"},
            "observable_evidence": {"type": "string"},
            "resulting_state": {"type": "string"},
        },
    }

def semantic_return_protocol() -> dict[str, Any]:
    return {
        "type": SEMANTIC_OUTPUT_TYPE,
        "semantic_request": "return the SEMANTIC_REQUEST payload unchanged",
        "output": "return only JSON matching request.output_schema",
    }

def _transport_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    snap = deepcopy(item)
    for key in ("state", "recording_event", "recording_instruction"):
        snap.pop(key, None)
    for container_key in ("semantic_request", "payload", "source_request"):
        container = snap.get(container_key)
        if isinstance(container, dict):
            for key in ("state", "recording_event", "recording_instruction"):
                container.pop(key, None)
    return snap

def _append_transport(state: dict[str, Any], item: dict[str, Any], timestamp: str) -> None:
    state.setdefault("transport_history", []).append(_transport_snapshot(item))
    state.setdefault("transport_times", []).append(timestamp)

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
    container = req_dict(out.get("semantic_request"), "semantic_request") if typ == SEMANTIC_OUTPUT_TYPE else req_dict(out.get("payload"), "payload")
    container["state"] = state
    seal(container)
    return out

def _initial_state(inp: dict[str, Any], timestamp_started: str) -> dict[str, Any]:
    return {
        "transport_history": [deepcopy(inp)],
        "transport_times": [timestamp_started],
        "turn_id": rid("turn"),
        "exact_user_prompt": req_text(inp.get("user_prompt"), "user_prompt"),
    }

def _sheet_cell(value: str) -> dict[str, Any]:
    return {"userEnteredValue": {"stringValue": value}}

def _recorder_placeholder(reason: str, value: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"$omitted": reason}
    if value is not None:
        try:
            raw = canon(value)
            out["sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            out["serialized_chars"] = len(raw)
        except Exception:
            out["value_type"] = type(value).__name__
    return out

def _recorder_sanitize(value: Any, depth: int = 0, ancestors: set[int] | None = None) -> Any:
    if depth > RECORDER_MAX_DEPTH:
        return _recorder_placeholder("max_depth_exceeded")
    if not isinstance(value, (dict, list)):
        return deepcopy(value)
    ancestors = set() if ancestors is None else ancestors
    oid = id(value)
    if oid in ancestors:
        return _recorder_placeholder("object_cycle_detected")
    branch_ancestors = set(ancestors)
    branch_ancestors.add(oid)
    if isinstance(value, list):
        return [_recorder_sanitize(v, depth + 1, branch_ancestors) for v in value]
    out: dict[str, Any] = {}
    for key, branch in value.items():
        if depth > 0 and key in RECORDER_OMIT_KEYS:
            out[key] = _recorder_placeholder("recursive_controller_branch", branch)
        else:
            out[key] = _recorder_sanitize(branch, depth + 1, branch_ancestors)
    return out

def _recorder_json(value: Any) -> str:
    sanitized = _recorder_sanitize(value)
    text = canon(sanitized)
    if len(text) <= RECORDER_MAX_CELL_CHARS:
        return text
    summary: dict[str, Any] = {
        "$omitted": "oversized_recorder_json",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "serialized_chars": len(text),
    }
    if isinstance(sanitized, dict):
        for key in ("type", "protocol", "authority", "directive", "schema", "control_version", "action_id"):
            if key in sanitized and not isinstance(sanitized[key], (dict, list)):
                summary[key] = sanitized[key]
    return canon(summary)

def _duration_ms(started: str, completed: str) -> str:
    try:
        a = datetime.fromisoformat(started.replace("Z", "+00:00"))
        b = datetime.fromisoformat(completed.replace("Z", "+00:00"))
        return str(max(0, round((b - a).total_seconds() * 1000)))
    except Exception:
        return ""

def event_row(event: dict[str, Any]) -> list[str]:
    inv = event["invocation"]
    inp = inv["input"]
    out = inv["output"]
    return [
        INVOCATION_EVENT_SCHEMA,
        str(event["event_id"]),
        str(event["timestamp_started"]),
        str(event["timestamp_completed"]),
        _duration_ms(str(event["timestamp_started"]), str(event["timestamp_completed"])),
        str(event["turn_id"]),
        str(event["source"]["method"]),
        str(inp.get("type", "")) if isinstance(inp, dict) else "",
        str(out.get("protocol", "")) if isinstance(out, dict) else "",
        str(out.get("authority", "")) if isinstance(out, dict) else "",
        str(out.get("directive", "")) if isinstance(out, dict) else "",
        str(inv["exception"]["type"]) if isinstance(inv.get("exception"), dict) else "",
        str(inv["exception"]["message"]) if isinstance(inv.get("exception"), dict) else "",
        _recorder_json(inp),
        _recorder_json(out),
    ]

def reconstruct_invocation_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    history = req_list(state.get("transport_history"), "transport_history")
    times = req_list(state.get("transport_times"), "transport_times")
    if len(history) != len(times) or len(history) % 2:
        raise ValueError("transport history must contain complete input/output pairs")
    turn_id = req_text(state.get("turn_id"), "turn_id")
    events = []
    for index in range(0, len(history), 2):
        input_data = req_dict(history[index], f"transport_history[{index}]")
        output_data = req_dict(history[index + 1], f"transport_history[{index + 1}]")
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
            "Pass api_call verbatim.",
            "Do not feed this recording instruction or its result into the controller semantic or execution-evaluation chain.",
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
            "Do not add tests, verification, inspection, planning, clarification, documentation, approvals, or process gates unless explicitly required.",
            "Do not infer dependencies merely because they are prudent, useful, conventional, or confidence-increasing.",
            "Preserve exclusions, sequencing, cardinality, scope, polarity, modality, and referents.",
            "Return JSON only using exactly output_schema.",
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
        seen.add(pid); tids.add(pid)
        order = x.get("explicit_order", i)
        if not isinstance(order, int) or order < 0:
            raise ValueError("explicit_order must be nonnegative integer")
        nts.append({
            "id": pid, "kind": "TERMINAL",
            "description": req_text(x.get("description"), f"{pid}.description"),
            "evidence_standard": req_text(x.get("evidence_standard"), f"{pid}.evidence_standard"),
            "explicit_order": order,
            "depends_on": [req_text(v, "dependency id") for v in req_list(x.get("depends_on", []), "depends_on")],
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
        seen.add(did); dep_ids.add(did)
        required_for = [req_text(v, "required_for") for v in req_list(x.get("required_for"), "required_for")]
        if not required_for or any(pid not in tids for pid in required_for):
            raise ValueError(f"{did} has invalid required_for")
        deps.append({
            "id": did, "kind": "DEPENDENCY",
            "description": req_text(x.get("description"), f"{did}.description"),
            "evidence_standard": req_text(x.get("evidence_standard"), f"{did}.evidence_standard"),
            "required_for": required_for, "origin": "USER_EXPLICIT",
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
        "active_target": None,
        "active_action_id": None,
        "last_knowledge": None,
        "record": [],
    }
    record(state, "CONTRACT_ACCEPTED", {"contract_sha256": contract["contract_sha256"]})
    return state

def terminal(state: dict[str, Any], pid: str) -> dict[str, Any] | None:
    return next((p for p in state["contract"]["terminal_predicates"] if p["id"] == pid), None)

def dependency(state: dict[str, Any], did: str) -> dict[str, Any] | None:
    return next((d for d in state["contract"]["explicit_dependencies"] if d["id"] == did), None)

def deps_for(state: dict[str, Any], p: dict[str, Any]) -> list[str]:
    return list(p.get("depends_on", []))

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
    deps = [{**deepcopy(d), "status": state["predicate_state"].get(d["id"], "UNSATISFIED")} for d in state["contract"]["explicit_dependencies"]]
    recent = deepcopy(state.get("record", [])[-8:])
    return {
        "scheduled_predicate": descriptor(state, pid, kind),
        "dependencies": deps,
        "invariants": deepcopy(state["contract"]["invariants"]),
        "authorizations": deepcopy(state["contract"]["authorizations"]),
        "prohibitions": deepcopy(state["contract"]["prohibitions"]),
        "recent_execution_record": recent,
    }

def _validate_kb_record(item: Any, label: str = "knowledge record") -> dict[str, Any]:
    item = req_dict(item, label)
    kid = req_text(item.get("id"), "knowledge id")
    req_enum(item.get("type"), KNOWLEDGE_TYPES, "knowledge type")
    req_text(item.get("summary"), f"{kid}.summary")
    return item

def _load_pending_overlay() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not RUNTIME_MANIFEST_PATH.exists():
        return [], {"available": False, "overlay_version": 0, "pending": 0}
    manifest = req_dict(json.loads(RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")), "runtime manifest")
    if manifest.get("schema") != "execution-runtime-manifest-v1":
        raise ValueError("invalid runtime manifest schema")
    overlay_path = RUNTIME_MANIFEST_PATH.with_name("kb_overlay.json")
    overlay = req_dict(json.loads(overlay_path.read_text(encoding="utf-8")), "runtime knowledge overlay")
    records = req_list(overlay.get("records"), "overlay records")
    published_through = int(overlay.get("published_through", 0))
    if published_through < 0 or published_through > len(records):
        raise ValueError("invalid overlay published_through")
    pending = [_validate_kb_record(x, "overlay record") for x in records[published_through:]]
    return pending, {
        "available": True,
        "generation": manifest.get("generation"),
        "overlay_version": int(overlay.get("version", 0)),
        "pending": len(pending),
    }

def _load_kb() -> dict[str, Any]:
    raw = json.loads(KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != KNOWLEDGE_SCHEMA:
        raise ValueError("invalid execution knowledge base schema")
    if not isinstance(raw.get("version"), int):
        raise ValueError("invalid execution knowledge base version")
    base_records = req_list(raw.get("records"), "knowledge records")
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for original in base_records:
        item = _validate_kb_record(original)
        kid = item["id"]
        if kid in merged:
            raise ValueError(f"duplicate knowledge id {kid}")
        merged[kid] = item
        order.append(kid)
    pending, overlay_meta = _load_pending_overlay()
    for item in pending:
        kid = item["id"]
        if kid not in merged:
            order.append(kid)
        merged[kid] = item
    out = deepcopy(raw)
    out["records"] = [deepcopy(merged[k]) for k in order]
    out["runtime_overlay"] = overlay_meta
    return out

_TOKEN_RE = re.compile(r"[a-z0-9]+")
def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower().replace("_", " ").replace("-", " ").replace(".", " "))

def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten_text(v)}" for k, v in value.items())
    if value is None:
        return ""
    return str(value)

def _record_search_text(item: dict[str, Any]) -> str:
    parts = [item.get("id", ""), item.get("type", ""), item.get("summary", ""), _flatten_text(item.get("retrieval", {}))]
    if item.get("type") in {"action", "procedure"}:
        parts.append(_flatten_text(item.get("applicability", {})))
        parts.append(_flatten_text(item.get("execution", {}).get("success", "")))
    if item.get("type") == "capability":
        parts.append(_flatten_text(item.get("interface", {})))
    if item.get("type") == "pattern":
        parts.append(_flatten_text(item.get("composition", [])))
    return " ".join(parts)

def _link_ids(item: dict[str, Any]) -> list[str]:
    links = item.get("links", {})
    if not isinstance(links, dict):
        return []
    out = []
    for value in links.values():
        if isinstance(value, list):
            out.extend(v for v in value if isinstance(v, str))
    return out

def search_knowledge(query: str, requested_types: list[str], top_k: int | None = None) -> dict[str, Any]:
    kb = _load_kb()
    cfg = req_dict(kb.get("retrieval"), "knowledge retrieval config")
    max_k = int(cfg.get("max_top_k", 16))
    k = min(max(1, int(top_k or cfg.get("default_top_k", 8))), max_k)
    types = [req_enum(t, KNOWLEDGE_TYPES, "knowledge query type") for t in requested_types]
    if not types:
        types = sorted(KNOWLEDGE_TYPES)
    qtokens = _tokens(req_text(query, "knowledge query"))
    qset = set(qtokens)
    records = [r for r in req_list(kb["records"], "records") if r.get("type") in types]
    if not records:
        return {"schema": KNOWLEDGE_SCHEMA, "version": kb["version"], "runtime_overlay": deepcopy(kb.get("runtime_overlay", {})), "query": query, "types": types, "results": []}

    docs = {}
    df = {}
    for r in records:
        toks = _tokens(_record_search_text(r))
        docs[r["id"]] = toks
        for tok in set(toks):
            df[tok] = df.get(tok, 0) + 1
    n = len(records)
    avgdl = sum(len(v) for v in docs.values()) / max(n, 1)
    priors = cfg.get("type_prior", {}) if isinstance(cfg.get("type_prior"), dict) else {}
    scored = []
    for r in records:
        toks = docs[r["id"]]
        counts = {}
        for tok in toks:
            counts[tok] = counts.get(tok, 0) + 1
        score = 0.0
        for tok in qset:
            if tok not in counts:
                continue
            freq = counts[tok]
            idf = math.log(1.0 + (n - df.get(tok, 0) + 0.5) / (df.get(tok, 0) + 0.5))
            denom = freq + 1.2 * (1 - 0.75 + 0.75 * len(toks) / max(avgdl, 1.0))
            score += idf * (freq * 2.2 / denom)
        low_query = query.lower()
        kid = r["id"].lower()
        if kid in low_query:
            score += 8.0
        aliases = r.get("retrieval", {}).get("aliases", []) if isinstance(r.get("retrieval"), dict) else []
        for alias in aliases if isinstance(aliases, list) else []:
            if isinstance(alias, str) and alias.lower() in low_query:
                score += 4.0
        score *= float(priors.get(r["type"], 1.0))
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    primary = scored[:k]

    by_id = {r["id"]: r for r in req_list(kb["records"], "records")}
    results = []
    seen = set()
    for score, r in primary:
        results.append({"id": r["id"], "type": r["type"], "score": round(score, 6), "source": "primary", "record": deepcopy(r)})
        seen.add(r["id"])
    for score, r in primary:
        for linked_id in _link_ids(r):
            if linked_id in seen or linked_id not in by_id:
                continue
            linked = by_id[linked_id]
            results.append({"id": linked_id, "type": linked["type"], "score": round(score * 0.35, 6), "source": f"link:{r['id']}", "record": deepcopy(linked)})
            seen.add(linked_id)
            if len(results) >= max_k:
                break
        if len(results) >= max_k:
            break
    return {
        "schema": KNOWLEDGE_SCHEMA,
        "version": kb["version"],
        "runtime_overlay": deepcopy(kb.get("runtime_overlay", {})),
        "query": query,
        "types": types,
        "results": results,
    }

def knowledge_query_request(state: dict[str, Any]) -> dict[str, Any]:
    if all_done(state):
        record(state, "TASK_COMPLETE", {"predicate_state": deepcopy(state["predicate_state"])})
        return emit("FINAL_RESPONSE", state, directive="COMPLETE", command="All terminal predicates are satisfied. Deliver the final response now; do not perform additional material work.")
    selected = select_target(state)
    if selected is None:
        return impasse_request(state, "Task incomplete but no schedulable predicate remains.")
    pid, kind = selected
    state["active_target"] = {"predicate_id": pid, "kind": kind}
    record(state, "TARGET_SCHEDULED", state["active_target"])
    return emit("SEMANTIC_REQUEST", state, protocol=KNOWLEDGE_QUERY_PROTOCOL, return_protocol=semantic_return_protocol(), request={
        "task": "Formulate the just-in-time execution-knowledge query that will best improve the next material action decision for the scheduled predicate.",
        "decision_context": decision_context(state, pid, kind),
        "knowledge_base": {
            "schema": KNOWLEDGE_SCHEMA,
            "path": str(KNOWLEDGE_BASE_PATH),
            "available_types": sorted(KNOWLEDGE_TYPES),
            "query_interface": "The controller deterministically retrieves matching typed records after this semantic query is returned.",
        },
        "output_schema": knowledge_query_output_schema(),
        "rules": [
            "Query for the outcome and current situation, not merely a guessed method name.",
            "Use current known identifiers and prior results in the query when they change applicability.",
            "Include action and procedure when an established execution path may exist.",
            "Include heuristic when strategy choice may benefit from preferred execution guidance.",
            "Include capability or pattern when implementation is not already grounded.",
            "Do not request the entire knowledge base.",
            "Return JSON only using exactly output_schema.",
        ],
    })

def realization_request(state: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    return emit("SEMANTIC_REQUEST", state, protocol=REALIZATION_PROTOCOL, return_protocol=semantic_return_protocol(), request={
        "task": "Select or compose the next material action using the retrieved execution knowledge and current decision context.",
        "decision_context": decision_context(state, a["predicate_id"], a["kind"]),
        "retrieved_execution_knowledge": deepcopy(retrieval),
        "output_schema": realization_output_schema(),
        "rules": [
            "Interpret retrieved records according to their type and authority.",
            "If a directly applicable deterministic action or procedure fully supplies the required execution path, prefer KNOWLEDGE_ACTION and bind its required arguments.",
            "Do not add unlisted steps inside a selected deterministic action or closed procedure.",
            "Otherwise use heuristics to narrow strategy and capabilities/patterns to compose one concrete OPERATION.",
            "TARGET means the action is intended to establish the scheduled predicate. DEPENDENCY means it realizes a genuinely necessary intermediate condition and leaves the scheduled predicate active.",
            "Do not use DEPENDENCY merely for prudence, confidence, conventional process, optional verification, or rediscovery of known state.",
            "Classify only hard conflicts: accepted invariants, explicit prohibitions, and authorized objective boundaries.",
            "Return JSON only using exactly output_schema.",
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
        "recent_execution_record": deepcopy(state.get("record", [])[-8:]),
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
            "A missing method is not established merely because the current context lacks it; consider whether knowledge retrieval or available capabilities can resolve the gap.",
            "Return JSON only using exactly output_schema.",
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

def _hard_conflict(r: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    result = {
        "violates_invariant": req_bool(r.get("violates_invariant"), "violates_invariant"),
        "violates_prohibition": req_bool(r.get("violates_prohibition"), "violates_prohibition"),
        "outside_authorized_objective": req_bool(r.get("outside_authorized_objective"), "outside_authorized_objective"),
        "conflicting_ids": [req_text(v, "conflicting id") for v in req_list(r.get("conflicting_ids", []), "conflicting_ids")],
    }
    conflict = result["violates_invariant"] or result["violates_prohibition"] or result["outside_authorized_objective"]
    return conflict, result

def _knowledge_record(kid: str) -> dict[str, Any]:
    kb = _load_kb()
    item = next((r for r in kb["records"] if r.get("id") == kid), None)
    if not isinstance(item, dict):
        raise ValueError(f"unknown knowledge id {kid}")
    return deepcopy(item)

def _bind_knowledge_action(item: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") not in {"action", "procedure"}:
        raise ValueError("knowledge action must reference action or procedure")
    applicability = item.get("applicability", {})
    required = applicability.get("requires", []) if isinstance(applicability, dict) else []
    if not isinstance(required, list):
        required = []
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError(f"missing deterministic action arguments: {missing}")
    return {
        "knowledge_id": item["id"],
        "knowledge_type": item["type"],
        "summary": item["summary"],
        "arguments": deepcopy(arguments),
        "applicability": deepcopy(item.get("applicability", {})),
        "execution": deepcopy(item.get("execution", {})),
    }

def _emit_task_action(state: dict[str, Any], role: str, operation: dict[str, Any] | None = None, deterministic_spec: dict[str, Any] | None = None, knowledge_used: list[str] | None = None, necessity_basis: str = "") -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    action_id = rid("action")
    state["active_action_id"] = action_id
    payload = {
        "action_id": action_id,
        "scheduled_predicate": descriptor(state, a["predicate_id"], a["kind"]),
        "action_role": role,
        "knowledge_used": knowledge_used or [],
        "necessity_basis": necessity_basis,
        "return_protocol": {
            "type": "ACTION_RESULT",
            "payload": "return this TASK_ACTION payload unchanged; it carries controller state required for the next invocation",
            "result_schema": action_result_schema(),
        },
    }
    if deterministic_spec is not None:
        payload["deterministic_spec"] = deterministic_spec
        payload["command"] = "Execute deterministic_spec exactly as defined. Do not add unlisted material steps. Resolve $variables from arguments and prior saved step results. Return one ACTION_RESULT for the complete deterministic action or procedure."
    elif operation is not None:
        payload["operation"] = operation
        payload["command"] = operation["command"]
    else:
        raise ValueError("TASK_ACTION requires deterministic_spec or operation")
    record(state, "ACTION_AUTHORIZED", {
        "action_id": action_id,
        "predicate_id": a["predicate_id"],
        "role": role,
        "knowledge_used": knowledge_used or [],
        "operation": deepcopy(operation),
        "deterministic_spec": deepcopy(deterministic_spec),
    })
    return emit("TASK_ACTION", state, **payload)

def handle_contract(inp: dict[str, Any]) -> dict[str, Any]:
    source = req_dict(inp.get("source_request"), "source_request")
    if source.get("protocol") != CONTRACT_PROTOCOL:
        raise ValueError("wrong contract source protocol")
    prompt = req_text(source.get("request", {}).get("user_prompt"), "user_prompt")
    contract = normalize_contract(req_dict(inp.get("contract"), "contract"), prompt)
    carried_state = req_dict(source.get("state"), "state")
    return knowledge_query_request(init_state(prompt, contract, carried_state))

def handle_knowledge_query(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != KNOWLEDGE_QUERY_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    query = req_text(r.get("query"), "query")
    types = [req_enum(v, KNOWLEDGE_TYPES, "knowledge type") for v in req_list(r.get("types"), "types")]
    reason = req_text(r.get("reason"), "reason")
    retrieval = search_knowledge(query, types)
    state["last_knowledge"] = {
        "query": query,
        "types": types,
        "reason": reason,
        "result_ids": [item["id"] for item in retrieval["results"]],
        "kb_version": retrieval["version"],
    }
    record(state, "KNOWLEDGE_RETRIEVED", deepcopy(state["last_knowledge"]))
    return realization_request(state, retrieval)

def handle_realization(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload"))
    state = deepcopy(p["state"])
    if p.get("protocol") != REALIZATION_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    kind = req_enum(r.get("kind"), {"KNOWLEDGE_ACTION", "OPERATION", "IMPASSE_CLAIM"}, "kind")
    if kind == "IMPASSE_CLAIM":
        return impasse_request(state, "An impasse claim was proposed for the scheduled predicate.", req_dict(r.get("claim"), "claim"))
    role = req_enum(r.get("role"), ACTION_ROLES, "role")
    conflict, conflict_detail = _hard_conflict(req_dict(r.get("hard_conflict"), "hard_conflict"))
    knowledge_used = [req_text(v, "knowledge_used id") for v in req_list(r.get("knowledge_used", []), "knowledge_used")]
    necessity_basis = req_text(r.get("necessity_basis"), "necessity_basis")
    record(state, "HARD_BOUNDARY_CLASSIFIED", {"conflict": conflict, "detail": conflict_detail})
    if conflict:
        record(state, "ACTION_REJECTED_HARD_CONFLICT", {"detail": conflict_detail})
        return knowledge_query_request(state)
    if kind == "KNOWLEDGE_ACTION":
        kid = req_text(r.get("knowledge_id"), "knowledge_id")
        last = req_dict(state.get("last_knowledge"), "last_knowledge")
        if kid not in last.get("result_ids", []):
            raise ValueError("selected knowledge action was not in retrieved context")
        item = _knowledge_record(kid)
        args = req_dict(r.get("arguments"), "arguments")
        spec = _bind_knowledge_action(item, args)
        if kid not in knowledge_used:
            knowledge_used.append(kid)
        return _emit_task_action(state, role, deterministic_spec=spec, knowledge_used=knowledge_used, necessity_basis=necessity_basis)
    op = normalize_operation(req_dict(r.get("operation"), "operation"))
    return _emit_task_action(state, role, operation=op, knowledge_used=knowledge_used, necessity_basis=necessity_basis)

def evidence_request(task_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(task_payload["state"])
    a = req_dict(state.get("active_target"), "active_target")
    ar = {
        "executed": req_bool(result.get("executed"), "executed"),
        "succeeded": req_bool(result.get("succeeded"), "succeeded"),
        "observable_evidence": req_text(result.get("observable_evidence"), "observable_evidence"),
        "resulting_state": req_text(result.get("resulting_state"), "resulting_state"),
    }
    role = req_enum(task_payload.get("action_role"), ACTION_ROLES, "action_role")
    record(state, "ACTION_RESULT_REPORTED", {
        "action_id": task_payload.get("action_id"),
        "predicate_id": a["predicate_id"],
        "role": role,
        "result": deepcopy(ar),
    })
    state["active_action_id"] = None
    if role == "DEPENDENCY":
        record(state, "DEPENDENCY_ACTION_COMPLETED", {
            "predicate_id": a["predicate_id"],
            "succeeded": ar["succeeded"],
            "evidence": ar["observable_evidence"],
            "necessity_basis": task_payload.get("necessity_basis", ""),
        })
        return knowledge_query_request(state)
    return emit("SEMANTIC_REQUEST", state, protocol=EVIDENCE_PROTOCOL, return_protocol=semantic_return_protocol(), pending_action_result=ar, request={
        "task": "Classify whether observable evidence establishes the scheduled predicate.",
        "decision_context": decision_context(state, a["predicate_id"], a["kind"]),
        "action_result": ar,
        "output_schema": evidence_output_schema(),
        "rules": [
            "Use only observable evidence.",
            "Tool success is not automatically predicate satisfaction.",
            "Do not require more than the accepted evidence standard.",
            "Do not invent post-action verification requirements absent from the contract.",
            "Return JSON only using exactly output_schema.",
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
        record(state, "PREDICATE_SATISFIED", {"predicate_id": pid, "evidence": deepcopy(p.get("pending_action_result"))})
        return knowledge_query_request(state)
    record(state, "PREDICATE_NOT_SATISFIED", {"predicate_id": pid, "verdict": verdict, "evidence": deepcopy(p.get("pending_action_result"))})
    return knowledge_query_request(state)

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
    return knowledge_query_request(state)

def dispatch_semantic_transport(inp: dict[str, Any]) -> dict[str, Any]:
    typ = inp.get("type")
    if typ == "CONTRACT_RESULT":
        return handle_contract(inp)
    if typ == "KNOWLEDGE_QUERY_RESULT":
        return handle_knowledge_query(inp)
    if typ == "REALIZATION_RESULT":
        return handle_realization(inp)
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
