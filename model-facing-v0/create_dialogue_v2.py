#!/usr/bin/env python3
"""CREATE dialogue v2: prompt -> goal -> query -> KB selection -> solver instruction -> contract.

Model-visible transport is newline-delimited JSON on stdout/stdin.
Hidden evaluation metadata is emitted on TRANSACTION_META_FD when supplied.
The final model stdin object is an outcome envelope:

    {"result": <object matching create_dialogue.json:return_schema>,
     "transition": "execute" | "revise" | "exit"}

The script emits no additional stdout after accepting that terminal envelope.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFINITION_PATH = HERE / "create_dialogue.json"
EXECUTION_KB_PATH = HERE / "execution_knowledge_base.json"
CONTEXT_KB_PATH = HERE / "model_facing_context_kb.json"
META_FD_ENV = "TRANSACTION_META_FD"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_message_sequence = 0


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def emit_metadata(event: str, **fields: Any) -> None:
    raw = os.environ.get(META_FD_ENV)
    if raw is None:
        return
    try:
        os.write(int(raw), (compact({"event": event, **fields}) + "\n").encode("utf-8"))
    except Exception:
        return


def emit_model(payload: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> int:
    global _message_sequence
    _message_sequence += 1
    sequence = _message_sequence
    meta = {
        "message_sequence": sequence,
        "stage": payload.get("stage"),
        "model_visible_keys": sorted(payload.keys()),
    }
    if metadata:
        meta.update(metadata)
    emit_metadata("MODEL_MESSAGE", **meta)
    sys.stdout.write(compact(payload) + "\n")
    sys.stdout.flush()
    return sequence


def fail(code: str, message: str, *, stage: str | None = None, path: str | None = None) -> None:
    emit_metadata("DIALOGUE_ERROR", code=code, message=message, stage=stage, path=path)
    sys.stderr.write(f"{code}: {message}\n")
    sys.stderr.flush()
    raise SystemExit(2)


def read_object(*, stage: str, responding_to: int) -> dict[str, Any]:
    line = sys.stdin.readline()
    if line == "":
        fail("EOF", "Expected a JSON object from the model but stdin closed.", stage=stage)
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        fail("INVALID_JSON", f"Model response is not valid JSON: {exc.msg}.", stage=stage)
    if not isinstance(value, dict):
        fail("INVALID_SHAPE", "Model response must be a JSON object.", stage=stage)
    emit_metadata(
        "MODEL_RESPONSE_RECEIVED",
        message_sequence=responding_to,
        stage=stage,
        response_keys=sorted(value.keys()),
    )
    return value


def require_string(obj: dict[str, Any], key: str, *, stage: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail("INVALID_FIELD", f"'{key}' must be a non-empty string.", stage=stage, path=f"$.{key}")
    return value


def require_string_list(
    obj: dict[str, Any],
    key: str,
    *,
    stage: str,
    min_items: int = 1,
    max_items: int = 8,
) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list) or not (min_items <= len(value) <= max_items):
        fail(
            "INVALID_FIELD",
            f"'{key}' must be an array containing {min_items}..{max_items} strings.",
            stage=stage,
            path=f"$.{key}",
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        fail("INVALID_FIELD", f"'{key}' must contain only non-empty strings.", stage=stage, path=f"$.{key}")
    return value


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("MISSING_FILE", f"Required file is missing: {path.name}.")
    except json.JSONDecodeError as exc:
        fail("INVALID_JSON_FILE", f"{path.name} is invalid JSON: {exc.msg}.")
    if not isinstance(value, dict):
        fail("INVALID_FILE_SHAPE", f"{path.name} must contain a JSON object.")
    return value


def context_entry(context_kb: dict[str, Any], entry_id: str) -> dict[str, Any]:
    entries = context_kb.get("entries")
    if not isinstance(entries, list):
        fail("INVALID_CONTEXT_KB", "Context KB must contain an entries array.")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    fail("MISSING_CONTEXT_ENTRY", f"Required context entry does not exist: {entry_id}.")
    raise AssertionError("unreachable")


def token_set(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def retrieval_text(record: dict[str, Any]) -> str:
    return json.dumps(record.get("retrieval", {}), ensure_ascii=False, sort_keys=True)


def score_record(record: dict[str, Any], queries: list[str], type_prior: dict[str, Any]) -> float:
    rid_tokens = token_set(str(record.get("id", "")))
    summary_tokens = token_set(str(record.get("summary", "")))
    retrieval_tokens = token_set(retrieval_text(record))
    searchable = " ".join(
        _TOKEN_RE.findall(
            (str(record.get("id", "")) + " " + str(record.get("summary", "")) + " " + retrieval_text(record)).lower()
        )
    )
    score = 0.0
    for query in queries:
        q_tokens = _TOKEN_RE.findall(query.lower())
        q_norm = " ".join(q_tokens)
        for token in q_tokens:
            if token in rid_tokens:
                score += 4.0
            if token in summary_tokens:
                score += 3.0
            if token in retrieval_tokens:
                score += 1.0
        if q_norm and q_norm in searchable:
            score += 8.0
    try:
        score *= float(type_prior.get(record.get("type"), 1.0))
    except (TypeError, ValueError):
        pass
    return score


def search_topics(execution_kb: dict[str, Any], queries: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = execution_kb.get("records")
    if not isinstance(records, list):
        fail("INVALID_EXECUTION_KB", "Execution KB must contain a records array.")
    retrieval_cfg = execution_kb.get("retrieval") if isinstance(execution_kb.get("retrieval"), dict) else {}
    type_prior = retrieval_cfg.get("type_prior") if isinstance(retrieval_cfg.get("type_prior"), dict) else {}
    top_k = retrieval_cfg.get("default_top_k", 8)
    if not isinstance(top_k, int) or top_k < 1:
        top_k = 8

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        score = score_record(record, queries, type_prior)
        if score > 0:
            scored.append((score, record["id"], record))
    scored.sort(key=lambda item: (-item[0], item[1]))

    if scored:
        chosen = scored[:top_k]
    else:
        fallback = sorted(
            [record for record in records if isinstance(record, dict) and isinstance(record.get("id"), str)],
            key=lambda record: record["id"],
        )[:top_k]
        chosen = [(0.0, record["id"], record) for record in fallback]

    projections = [
        {"id": record_id, "type": record.get("type"), "summary": record.get("summary", "")}
        for _, record_id, record in chosen
    ]
    evaluation = [
        {"id": record_id, "score": score, "fallback": score == 0.0}
        for score, record_id, _ in chosen
    ]
    return projections, evaluation


def resolve_selected(execution_kb: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    records = execution_kb.get("records", [])
    by_id = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    return [by_id[item_id] for item_id in ids]


def validate_terminal_outcome(
    obj: dict[str, Any],
    *,
    allowed_transitions: list[str],
    stage: str,
) -> tuple[dict[str, Any], str]:
    if set(obj.keys()) != {"result", "transition"}:
        fail("INVALID_SHAPE", "Terminal response must contain exactly result and transition.", stage=stage)
    result = obj.get("result")
    if not isinstance(result, dict) or set(result.keys()) != {"execution_script", "return_schema"}:
        fail(
            "INVALID_RESULT",
            "result must contain exactly execution_script and return_schema.",
            stage=stage,
            path="$.result",
        )
    if not isinstance(result.get("execution_script"), str) or not result["execution_script"].strip():
        fail("INVALID_RESULT", "execution_script must be a non-empty string.", stage=stage, path="$.result.execution_script")
    if not isinstance(result.get("return_schema"), dict):
        fail("INVALID_RESULT", "return_schema must be a JSON object.", stage=stage, path="$.result.return_schema")
    transition = obj.get("transition")
    if transition not in allowed_transitions:
        fail("INVALID_TRANSITION", "transition is not allowed for CREATE.", stage=stage, path="$.transition")
    return result, transition


def main() -> None:
    definition = load_object(DEFINITION_PATH)
    execution_kb = load_object(EXECUTION_KB_PATH)
    context_kb = load_object(CONTEXT_KB_PATH)
    create_return_schema = definition.get("return_schema")
    allowed_transitions = definition.get("allowed_transitions")
    if not isinstance(create_return_schema, dict):
        fail("INVALID_DEFINITION", "CREATE definition must contain return_schema.")
    if not isinstance(allowed_transitions, list) or not all(isinstance(x, str) for x in allowed_transitions):
        fail("INVALID_DEFINITION", "CREATE definition must contain allowed_transitions.")

    emit_metadata(
        "DIALOGUE_STARTED",
        dialogue="create_dialogue_v2",
        definition_id=definition.get("id"),
        context_kb_version=context_kb.get("version"),
    )

    seq = emit_model(
        {
            "stage": "WELCOME_AND_USER_PROMPT",
            "message": "Welcome. This mode constructs an executable transaction from the current user request. Return only the JSON object required at each step.",
            "request": "Return the exact current user prompt without rewriting it.",
            "return_schema": {
                "type": "object",
                "required": ["user_prompt"],
                "properties": {"user_prompt": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "acquire_user_prompt"},
    )
    user_prompt = require_string(
        read_object(stage="WELCOME_AND_USER_PROMPT", responding_to=seq),
        "user_prompt",
        stage="WELCOME_AND_USER_PROMPT",
    )

    prompt_to_goal = context_entry(context_kb, "context.prompt-to-goal")
    seq = emit_model(
        {
            "stage": "PROMPT_TO_GOAL",
            "user_prompt": user_prompt,
            "mandatory_context": prompt_to_goal,
            "request": "Convert the user prompt to its execution goal.",
            "return_schema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "prompt_to_goal", "mandatory_context_ids": [prompt_to_goal["id"]]},
    )
    goal = require_string(read_object(stage="PROMPT_TO_GOAL", responding_to=seq), "goal", stage="PROMPT_TO_GOAL")

    goal_to_query = context_entry(context_kb, "context.goal-to-query")
    seq = emit_model(
        {
            "stage": "GOAL_TO_QUERY",
            "goal": goal,
            "mandatory_context": goal_to_query,
            "request": "Return the execution-KB queries needed to retrieve useful context for this goal.",
            "return_schema": {
                "type": "object",
                "required": ["queries"],
                "properties": {
                    "queries": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1},
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "goal_to_queries", "mandatory_context_ids": [goal_to_query["id"]]},
    )
    queries = require_string_list(read_object(stage="GOAL_TO_QUERY", responding_to=seq), "queries", stage="GOAL_TO_QUERY")

    candidates, retrieval_eval = search_topics(execution_kb, queries)
    select_topics = context_entry(context_kb, "context.select-topics")
    seq = emit_model(
        {
            "stage": "TOPIC_SELECTION",
            "goal": goal,
            "queries": queries,
            "candidate_topics": candidates,
            "mandatory_context": select_topics,
            "request": "Select the candidate KB topics whose full records should ground construction of the solver instruction.",
            "return_schema": {
                "type": "object",
                "required": ["selected_topics"],
                "properties": {
                    "selected_topics": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "enum": [item["id"] for item in candidates]},
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "select_execution_context",
            "mandatory_context_ids": [select_topics["id"]],
            "retrieval": retrieval_eval,
        },
    )
    selected_topics = require_string_list(
        read_object(stage="TOPIC_SELECTION", responding_to=seq),
        "selected_topics",
        stage="TOPIC_SELECTION",
        max_items=max(1, len(candidates)),
    )
    candidate_ids = {item["id"] for item in candidates}
    if len(set(selected_topics)) != len(selected_topics) or any(item not in candidate_ids for item in selected_topics):
        fail("INVALID_SELECTION", "selected_topics must be unique IDs from candidate_topics.", stage="TOPIC_SELECTION")
    selected_context = resolve_selected(execution_kb, selected_topics)

    synthesize = context_entry(context_kb, "context.synthesize-solver-instruction")
    seq = emit_model(
        {
            "stage": "SYNTHESIZE_SOLVER_INSTRUCTION",
            "user_prompt": user_prompt,
            "goal": goal,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
            "mandatory_context": synthesize,
            "request": "Construct the complete instruction that should be followed to solve this goal under the supplied KB context. Do not solve the goal yet.",
            "return_schema": {
                "type": "object",
                "required": ["instruction"],
                "properties": {"instruction": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "synthesize_solver_instruction",
            "mandatory_context_ids": [synthesize["id"]],
            "selected_topic_ids": selected_topics,
        },
    )
    solver_instruction = require_string(
        read_object(stage="SYNTHESIZE_SOLVER_INSTRUCTION", responding_to=seq),
        "instruction",
        stage="SYNTHESIZE_SOLVER_INSTRUCTION",
    )

    apply_instruction = context_entry(context_kb, "context.apply-solver-instruction")
    terminal_schema = {
        "type": "object",
        "required": ["result", "transition"],
        "properties": {
            "result": create_return_schema,
            "transition": {"type": "string", "enum": allowed_transitions},
        },
        "additionalProperties": False,
    }
    seq = emit_model(
        {
            "stage": "APPLY_SOLVER_INSTRUCTION",
            "user_prompt": user_prompt,
            "goal": goal,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
            "solver_instruction": solver_instruction,
            "mandatory_context": apply_instruction,
            "request": "Execute the supplied solver_instruction semantically now. Return its executable contract as result and choose the next transaction transition.",
            "return_schema": terminal_schema,
        },
        metadata={
            "semantic_operation": "apply_solver_instruction",
            "mandatory_context_ids": [apply_instruction["id"]],
            "selected_topic_ids": selected_topics,
            "solver_instruction_chars": len(solver_instruction),
            "terminal_response": True,
        },
    )
    final_message = read_object(stage="APPLY_SOLVER_INSTRUCTION", responding_to=seq)
    result, transition = validate_terminal_outcome(
        final_message,
        allowed_transitions=allowed_transitions,
        stage="APPLY_SOLVER_INSTRUCTION",
    )
    emit_metadata(
        "DIALOGUE_COMPLETED",
        dialogue="create_dialogue_v2",
        final_message_sequence=seq,
        transition=transition,
        execution_script_chars=len(result["execution_script"]),
        selected_topic_ids=selected_topics,
        solver_instruction_chars=len(solver_instruction),
    )
    # Deliberately no further stdout; the transaction runtime consumes the
    # final stdin object as the terminal outcome envelope.


if __name__ == "__main__":
    main()
