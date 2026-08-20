#!/usr/bin/env python3
"""Deterministic execution-contract / state-transition controller.

The model is a bounded semantic service. This script owns contract structure,
predicate state, dependency admission, scheduling, authorization, evidence
updates, completion, and impasse routing.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

CONTROL_VERSION = 1
INITIALIZATION_SCHEMA = "execution-contract-controller-initialization-v1"
PAYLOAD_SCHEMA = "execution-contract-controller-payload-v1"
CONTRACT_SCHEMA = "execution-contract-v1"

CONTRACT_PROTOCOL = "compile-contract-v1"
REALIZATION_PROTOCOL = "realize-transition-v1"
ADMISSIBILITY_PROTOCOL = "classify-operation-v1"
DEPENDENCY_PROTOCOL = "admit-dependency-v1"
EVIDENCE_PROTOCOL = "classify-evidence-v1"
IMPASSE_PROTOCOL = "classify-impasse-v1"

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
    "For semantic requests, evaluate the supplied contract, predicate, operation, dependency, evidence, or impasse claim in its current execution context; do not substitute an independent plan or redefine the task.",
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
    base = {k: v for k, v in payload.items() if k != "payload_sha256"}
    payload["payload_sha256"] = digest(base)
    return payload


def verify(payload: dict[str, Any]) -> dict[str, Any]:
    req_dict(payload, "payload")
    if payload.get("schema") != PAYLOAD_SCHEMA:
        raise ValueError("invalid payload schema")
    expected = payload.get("payload_sha256")
    base = {k: v for k, v in payload.items() if k != "payload_sha256"}
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


def contract_request(prompt: str) -> dict[str, Any]:
    return {
        "schema": PAYLOAD_SCHEMA,
        "control_version": CONTROL_VERSION,
        "authority": "SEMANTIC_REQUEST",
        "protocol": CONTRACT_PROTOCOL,
        "behavioral_instructions": BEHAVIORAL_INSTRUCTIONS,
        "request": {
            "task": "Compile the exact user instruction into an execution contract. Do not plan execution.",
            "user_prompt": prompt,
            "output_schema": {
                "schema": CONTRACT_SCHEMA,
                "terminal_predicates": [{"id": "P1", "description": "observable requested end state", "evidence_standard": "sufficient observable evidence", "explicit_order": 0, "depends_on": []}],
                "invariants": [{"id": "I1", "description": "condition that must remain true"}],
                "authorizations": [{"id": "A1", "description": "authorized objective or operation class"}],
                "prohibitions": [{"id": "X1", "description": "explicitly prohibited operation, target, or outcome"}],
                "explicit_dependencies": [{"id": "D1", "description": "explicitly required prerequisite condition", "required_for": ["P1"], "evidence_standard": "sufficient observable evidence"}],
            },
            "rules": [
                "Represent requested results as terminal predicates, not execution steps.",
                "Do not add tests, verification, inspection, planning, clarification, documentation, approvals, or process gates unless explicitly required by the user or a governing requirement.",
                "Do not infer dependencies merely because they are prudent, useful, conventional, or confidence-increasing.",
                "Preserve exclusions, sequencing, cardinality, scope, polarity, modality, and referents.",
                "Return JSON only.",
            ],
        },
    }


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
        seen.add(did); dep_ids.add(did)
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


def init_state(prompt: str, contract: dict[str, Any]) -> dict[str, Any]:
    ps = {p["id"]: "UNSATISFIED" for p in contract["terminal_predicates"]}
    ps.update({d["id"]: "UNSATISFIED" for d in contract["explicit_dependencies"]})
    state = {
        "turn_id": rid("turn"),
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
    return emit("SEMANTIC_REQUEST", state, protocol=REALIZATION_PROTOCOL, request={
        "task": "Produce exactly one realization proposal for the scheduled predicate.",
        "scheduled_predicate": descriptor(state, pid, kind),
        "blocked_realizations": deepcopy(state["blocked_realizations"].get(pid, [])),
        "allowed_kinds": ["OPERATION", "DEPENDENCY_PROPOSAL", "IMPASSE_CLAIM"],
        "operation_schema": {"kind": "OPERATION", "operation": {"operation_kind": sorted(OP_KINDS), "objective": "text", "target": "text", "command": "text", "expected_observable_effect": "text"}},
        "dependency_schema": {"kind": "DEPENDENCY_PROPOSAL", "dependency": {"description": "text", "evidence_standard": "text", "observed_block": "specific current blocking fact"}},
        "rules": [
            "If a direct operation can realize the scheduled predicate, propose it.",
            "Do not submit indirect/support work as OPERATION; use DEPENDENCY_PROPOSAL.",
            "Before proposing a dependency, apply the counterfactual: if omitting it leaves any legitimate path to the scheduled predicate, do not propose it.",
            "Return JSON only.",
        ],
    })


def admissibility_request(state: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    return emit("SEMANTIC_REQUEST", state, protocol=ADMISSIBILITY_PROTOCOL, pending_operation=op, request={
        "task": "Classify the proposed operation using only the closed fields.",
        "scheduled_predicate": descriptor(state, a["predicate_id"], a["kind"]),
        "operation": deepcopy(op),
        "questions": {
            "relationship": sorted(RELATIONS),
            "violates_invariant": "boolean",
            "violates_prohibition": "boolean",
            "outside_authorized_objective": "boolean",
            "introduces_unadmitted_prerequisite": "boolean",
            "repeats_blocked_realization_or_semantic_equivalent": "boolean",
            "requires_additional_material_action_before_it_can_have_stated_effect": "boolean",
            "is_indirect_or_support_operation": "boolean",
            "legitimate_path_to_scheduled_predicate_remains_if_operation_is_omitted": "boolean",
        },
        "rules": [
            "Evaluate contextually, not lexically.",
            "If indirect/support and a legitimate path remains when omitted, the operation is inadmissible.",
            "Indirect/support work must be represented as a dependency proposal, not as a direct operation.",
            "Return JSON only.",
        ],
    })


def dependency_request(state: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    a = req_dict(state.get("active_target"), "active_target")
    return emit("SEMANTIC_REQUEST", state, protocol=DEPENDENCY_PROTOCOL, pending_dependency=proposal, request={
        "task": "Determine whether this dependency may enter the execution graph.",
        "scheduled_predicate": descriptor(state, a["predicate_id"], a["kind"]),
        "proposed_dependency": deepcopy(proposal),
        "questions": {
            "observed_block_is_current_and_concrete": "boolean",
            "scheduled_predicate_cannot_legitimately_be_realized_while_condition_is_false": "boolean",
            "condition_is_not_merely_prudent_optional_or_confidence_increasing": "boolean",
            "dependency_is_within_user_objective_or_governing_requirement": "boolean",
            "simpler_direct_realization_remains_available": "boolean",
            "legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted": "boolean",
        },
        "rules": [
            "Necessity, not usefulness, is required.",
            "Counterfactual necessity is decisive: if omitting the dependency leaves any legitimate path to the scheduled predicate, reject it.",
            "Return JSON only.",
        ],
    })


def impasse_request(state: dict[str, Any], reason: str, claim: dict[str, Any] | None = None) -> dict[str, Any]:
    active = state.get("active_target")
    target = descriptor(state, active["predicate_id"], active["kind"]) if isinstance(active, dict) else None
    return emit("SEMANTIC_REQUEST", state, protocol=IMPASSE_PROTOCOL, request={
        "task": "Classify whether a genuine execution impasse exists.",
        "controller_reason": reason,
        "scheduled_predicate": target,
        "claim": deepcopy(claim),
        "questions": {
            "requested_result_or_required_dependency_is_currently_unattainable": "boolean",
            "materially_different_legitimate_path_remains_available": "boolean",
            "missing_information_is_resolvable_retrievable_calculable_or_safely_assumable": "boolean",
            "remaining_block_is_created_only_by_assistant_process_or_preference": "boolean",
            "scope": sorted(SCOPES),
        },
        "rules": ["A failed operation is not task impasse.", "Impasse requires evidence that no legitimate continuation path remains.", "Return JSON only."],
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
    return digest({"operation_kind": op["operation_kind"], "objective": op["objective"].lower(), "target": op["target"].lower(), "expected_observable_effect": op["expected_observable_effect"].lower()})


def handle_contract(inp: dict[str, Any]) -> dict[str, Any]:
    source = req_dict(inp.get("source_request"), "source_request")
    if source.get("protocol") != CONTRACT_PROTOCOL:
        raise ValueError("wrong contract source protocol")
    prompt = req_text(source.get("request", {}).get("user_prompt"), "user_prompt")
    contract = normalize_contract(req_dict(inp.get("contract"), "contract"), prompt)
    return realization_request(init_state(prompt, contract))


def handle_realization(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload")); state = deepcopy(p["state"])
    if p.get("protocol") != REALIZATION_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
    kind = req_text(r.get("kind"), "kind")
    if kind == "OPERATION":
        return admissibility_request(state, normalize_operation(req_dict(r.get("operation"), "operation")))
    if kind == "DEPENDENCY_PROPOSAL":
        d = req_dict(r.get("dependency"), "dependency")
        return dependency_request(state, {"description": req_text(d.get("description"), "description"), "evidence_standard": req_text(d.get("evidence_standard"), "evidence_standard"), "observed_block": req_text(d.get("observed_block"), "observed_block")})
    if kind == "IMPASSE_CLAIM":
        return impasse_request(state, "An impasse claim was proposed for the scheduled predicate.", req_dict(r.get("claim"), "claim"))
    raise ValueError("unknown realization kind")


def handle_admissibility(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload")); state = deepcopy(p["state"])
    if p.get("protocol") != ADMISSIBILITY_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result")
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
    op = req_dict(p.get("pending_operation"), "pending_operation")
    admissible = relationship == expected and not any(flags) and not is_indirect and not (is_indirect and path_remains)
    record(state, "ADMISSIBILITY_CLASSIFIED", {"predicate_id": a["predicate_id"], "admissible": admissible, "counterfactual_path_remains": path_remains, "result": deepcopy(r)})
    if not admissible:
        state["blocked_realizations"].setdefault(a["predicate_id"], []).append({"fingerprint": op_fingerprint(op), "operation": deepcopy(op), "semantic_result": deepcopy(r)})
        return realization_request(state)
    action_id = rid("action"); state["active_action_id"] = action_id
    record(state, "ACTION_AUTHORIZED", {"action_id": action_id, "predicate_id": a["predicate_id"], "operation": deepcopy(op)})
    return emit("TASK_ACTION", state, action_id=action_id, scheduled_predicate=descriptor(state, a["predicate_id"], a["kind"]), operation=op, command=op["command"], return_protocol={"type": "ACTION_RESULT", "result_schema": {"executed": "boolean", "succeeded": "boolean", "observable_evidence": "text", "resulting_state": "text"}})


def handle_dependency(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload")); state = deepcopy(p["state"])
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
    admit = vals["observed_block_is_current_and_concrete"] and vals["scheduled_predicate_cannot_legitimately_be_realized_while_condition_is_false"] and vals["condition_is_not_merely_prudent_optional_or_confidence_increasing"] and vals["dependency_is_within_user_objective_or_governing_requirement"] and not vals["simpler_direct_realization_remains_available"] and not vals["legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted"]
    a = req_dict(state.get("active_target"), "active_target")
    proposal = req_dict(p.get("pending_dependency"), "pending_dependency")
    record(state, "DEPENDENCY_CLASSIFIED", {"parent": a["predicate_id"], "admitted": admit, "counterfactual_path_remains": vals["legitimate_path_to_scheduled_predicate_remains_if_dependency_is_omitted"], "result": deepcopy(r)})
    if not admit:
        return realization_request(state)
    did = rid("DYN")
    dep = {"id": did, "kind": "DEPENDENCY", "description": proposal["description"], "evidence_standard": proposal["evidence_standard"], "required_for": [a["predicate_id"]], "origin": "OBSERVED_TECHNICAL_NECESSITY", "observed_block": proposal["observed_block"]}
    state["dynamic_dependencies"].append(dep); state["predicate_state"][did] = "UNSATISFIED"
    record(state, "DEPENDENCY_ADMITTED", {"dependency": deepcopy(dep)})
    return realization_request(state)


def evidence_request(task_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(task_payload["state"]); a = req_dict(state.get("active_target"), "active_target")
    ar = {"executed": req_bool(result.get("executed"), "executed"), "succeeded": req_bool(result.get("succeeded"), "succeeded"), "observable_evidence": req_text(result.get("observable_evidence"), "observable_evidence"), "resulting_state": req_text(result.get("resulting_state"), "resulting_state")}
    record(state, "ACTION_RESULT_REPORTED", {"action_id": task_payload.get("action_id"), "predicate_id": a["predicate_id"], "result": deepcopy(ar)})
    return emit("SEMANTIC_REQUEST", state, protocol=EVIDENCE_PROTOCOL, pending_action_result=ar, pending_operation=deepcopy(task_payload.get("operation")), request={"task": "Classify whether the observable evidence establishes the scheduled predicate.", "scheduled_predicate": descriptor(state, a["predicate_id"], a["kind"]), "action_result": ar, "verdict": sorted(VERDICTS), "invariant_status": [{"id": i["id"], "status": "PRESERVED / VIOLATED / INDETERMINATE"} for i in state["contract"]["invariants"]], "rules": ["Use only observable evidence.", "Tool success is not automatically predicate satisfaction.", "Do not require more than the accepted evidence standard.", "Return JSON only."]})


def handle_evidence(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload")); state = deepcopy(p["state"])
    if p.get("protocol") != EVIDENCE_PROTOCOL:
        raise ValueError("wrong protocol")
    r = req_dict(inp.get("result"), "result"); verdict = req_enum(r.get("verdict"), VERDICTS, "verdict")
    allowed = {x["id"] for x in state["contract"]["invariants"]}; violated = False
    for x in req_list(r.get("invariant_status", []), "invariant_status"):
        x = req_dict(x, "invariant status"); iid = req_text(x.get("id"), "invariant id")
        if iid not in allowed:
            raise ValueError(f"unknown invariant {iid}")
        if req_text(x.get("status"), "status") == "VIOLATED":
            violated = True
    a = req_dict(state.get("active_target"), "active_target"); pid = a["predicate_id"]
    if violated:
        return impasse_request(state, "Accepted invariant classified as violated.")
    if verdict == "SATISFIED":
        state["predicate_state"][pid] = "SATISFIED"; state["active_target"] = None; state["active_action_id"] = None
        record(state, "PREDICATE_SATISFIED", {"predicate_id": pid, "evidence": deepcopy(p.get("pending_action_result"))})
        return realization_request(state)
    op = p.get("pending_operation")
    if isinstance(op, dict):
        state["blocked_realizations"].setdefault(pid, []).append({"fingerprint": op_fingerprint(op), "operation": deepcopy(op), "semantic_result": {"post_action_verdict": verdict}})
    state["active_action_id"] = None
    record(state, "PREDICATE_NOT_SATISFIED", {"predicate_id": pid, "verdict": verdict})
    return realization_request(state)


def handle_impasse(inp: dict[str, Any]) -> dict[str, Any]:
    p = verify(req_dict(inp.get("payload"), "payload")); state = deepcopy(p["state"])
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


def dispatch(inp: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inp, dict):
        raise ValueError("input must be an object")
    typ = inp.get("type")
    if typ == "INITIALIZE":
        if inp.get("schema") != INITIALIZATION_SCHEMA:
            raise ValueError("invalid initialization schema")
        return contract_request(req_text(inp.get("user_prompt"), "user_prompt"))
    if typ == "CONTRACT_RESULT":
        return handle_contract(inp)
    if typ == "REALIZATION_RESULT":
        return handle_realization(inp)
    if typ == "ADMISSIBILITY_RESULT":
        return handle_admissibility(inp)
    if typ == "DEPENDENCY_RESULT":
        return handle_dependency(inp)
    if typ == "ACTION_RESULT":
        p = verify(req_dict(inp.get("payload"), "payload"))
        if p.get("authority") != "TASK_ACTION":
            raise ValueError("payload is not TASK_ACTION")
        return evidence_request(p, req_dict(inp.get("result"), "result"))
    if typ == "EVIDENCE_RESULT":
        return handle_evidence(inp)
    if typ == "IMPASSE_RESULT":
        return handle_impasse(inp)
    raise ValueError("unknown input type")


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"error": "expected one JSON line on stdin"}))
        return 2
    try:
        print(json.dumps(dispatch(json.loads(line)), ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"schema": PAYLOAD_SCHEMA, "control_version": CONTROL_VERSION, "authority": "PROTOCOL_ERROR", "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
