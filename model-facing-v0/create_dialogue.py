#!/usr/bin/env python3
"""First reusable model-facing CREATE dialogue.

Transport contract
------------------
stdin  : newline-delimited JSON responses from the model
stdout : newline-delimited JSON messages that are visible to the model
stderr : diagnostics only
optional TRANSACTION_META_FD : newline-delimited JSON evaluation metadata that
                               is not included in model-visible messages

The final model stdin response contains both the minimal executable contract and
its next requested lifecycle action:

{
  "contract": {
    "execution_script": "<complete Python source>",
    "return_schema": { ... JSON Schema for the script's stdout object ... }
  },
  "next_action": "execute" | "revise" | "exit"
}

On a valid final response this dialogue exits successfully without writing an
additional stdout message. A transaction wrapper can therefore preserve every
stdin response and treat the last stdin value as the completed builder product.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXECUTION_KB_PATH = HERE / "execution_knowledge_base.json"
CONTEXT_KB_PATH = HERE / "model_facing_context_kb.json"
META_FD_ENV = "TRANSACTION_META_FD"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_message_sequence = 0


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def emit_metadata(event: str, **fields: Any) -> None:
    """Write hidden evaluation metadata when a metadata FD was supplied."""
    raw_fd = os.environ.get(META_FD_ENV)
    if raw_fd is None:
        return
    try:
        fd = int(raw_fd)
        payload = {"event": event, **fields}
        os.write(fd, (_compact_json(payload) + "\n").encode("utf-8"))
    except Exception:
        # Metadata must never corrupt the model dialogue. The parent process can
        # detect a missing metadata stream independently if it requires one.
        return


def emit_model(payload: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> int:
    """Emit one model-visible JSON message and parallel hidden metadata."""
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

    sys.stdout.write(_compact_json(payload) + "\n")
    sys.stdout.flush()
    return sequence


def fail(code: str, message: str, *, stage: str | None = None, path: str | None = None) -> None:
    emit_metadata(
        "DIALOGUE_ERROR",
        code=code,
        message=message,
        stage=stage,
        path=path,
    )
    # stderr is deliberately separate from the model-visible protocol.
    sys.stderr.write(f"{code}: {message}\n")
    sys.stderr.flush()
    raise SystemExit(2)


def read_json_object(*, stage: str, responding_to: int) -> dict[str, Any]:
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


def require_nonempty_string(obj: dict[str, Any], key: str, *, stage: str) -> str:
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
    if not isinstance(value, list):
        fail("INVALID_FIELD", f"'{key}' must be an array of strings.", stage=stage, path=f"$.{key}")
    if not (min_items <= len(value) <= max_items):
        fail(
            "INVALID_CARDINALITY",
            f"'{key}' must contain between {min_items} and {max_items} items.",
            stage=stage,
            path=f"$.{key}",
        )
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            fail(
                "INVALID_FIELD",
                f"'{key}[{i}]' must be a non-empty string.",
                stage=stage,
                path=f"$.{key}[{i}]",
            )
        out.append(item)
    return out


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("MISSING_FILE", f"Required file is missing: {path.name}.")
    except json.JSONDecodeError as exc:
        fail("INVALID_KB_JSON", f"{path.name} is invalid JSON: {exc.msg}.")
    if not isinstance(value, dict):
        fail("INVALID_KB_SHAPE", f"{path.name} must contain a JSON object.")
    return value


def context_entry(context_kb: dict[str, Any], entry_id: str) -> dict[str, Any]:
    entries = context_kb.get("entries")
    if not isinstance(entries, list):
        fail("INVALID_CONTEXT_KB", "Context KB must contain an 'entries' array.")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    fail("MISSING_CONTEXT_ENTRY", f"Required context KB entry does not exist: {entry_id}.")
    raise AssertionError("unreachable")


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def retrieval_text(record: dict[str, Any]) -> str:
    retrieval = record.get("retrieval", {})
    return json.dumps(retrieval, ensure_ascii=False, sort_keys=True)


def score_record(record: dict[str, Any], queries: list[str], type_prior: dict[str, Any]) -> float:
    record_id = str(record.get("id", ""))
    summary = str(record.get("summary", ""))
    rid_tokens = token_set(record_id)
    summary_tokens = token_set(summary)
    retrieval_tokens = token_set(retrieval_text(record))

    score = 0.0
    for query in queries:
        q_tokens = tokens(query)
        q_norm = " ".join(q_tokens)
        if not q_tokens:
            continue
        for tok in q_tokens:
            if tok in rid_tokens:
                score += 4.0
            if tok in summary_tokens:
                score += 3.0
            if tok in retrieval_tokens:
                score += 1.0
        searchable = " ".join(tokens(record_id + " " + summary + " " + retrieval_text(record)))
        if q_norm and q_norm in searchable:
            score += 8.0

    prior = type_prior.get(record.get("type"), 1.0)
    try:
        score *= float(prior)
    except (TypeError, ValueError):
        pass
    return score


def search_topics(execution_kb: dict[str, Any], queries: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = execution_kb.get("records")
    if not isinstance(records, list):
        fail("INVALID_EXECUTION_KB", "Execution KB must contain a 'records' array.")

    retrieval_cfg = execution_kb.get("retrieval", {})
    if not isinstance(retrieval_cfg, dict):
        retrieval_cfg = {}
    type_prior = retrieval_cfg.get("type_prior", {})
    if not isinstance(type_prior, dict):
        type_prior = {}

    top_k = retrieval_cfg.get("default_top_k", 8)
    max_top_k = retrieval_cfg.get("max_top_k", 16)
    if not isinstance(top_k, int) or top_k < 1:
        top_k = 8
    if not isinstance(max_top_k, int) or max_top_k < top_k:
        max_top_k = max(top_k, 16)
    top_k = min(top_k, max_top_k)

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        score = score_record(record, queries, type_prior)
        if score > 0:
            scored.append((score, record["id"], record))

    scored.sort(key=lambda item: (-item[0], item[1]))

    retrieval_eval: list[dict[str, Any]] = []
    if not scored:
        fallback = [r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)]
        fallback.sort(key=lambda r: r["id"])
        selected_records = fallback[:top_k]
        for record in selected_records:
            retrieval_eval.append({"id": record["id"], "score": 0.0, "fallback": True})
    else:
        selected_records = [record for _, _, record in scored[:top_k]]
        for score, record_id, _ in scored[:top_k]:
            retrieval_eval.append({"id": record_id, "score": score, "fallback": False})

    projections = [
        {
            "id": record["id"],
            "type": record.get("type"),
            "summary": record.get("summary", ""),
        }
        for record in selected_records
    ]
    return projections, retrieval_eval


def resolve_selected(execution_kb: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    records = execution_kb.get("records", [])
    by_id = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    return [by_id[item_id] for item_id in ids]


def validate_contract_response(obj: dict[str, Any], *, stage: str) -> tuple[dict[str, Any], str]:
    if set(obj.keys()) != {"contract", "next_action"}:
        fail(
            "INVALID_SHAPE",
            "Final response must contain exactly 'contract' and 'next_action'.",
            stage=stage,
        )

    contract = obj.get("contract")
    if not isinstance(contract, dict):
        fail("INVALID_FIELD", "'contract' must be a JSON object.", stage=stage, path="$.contract")
    if set(contract.keys()) != {"execution_script", "return_schema"}:
        fail(
            "INVALID_CONTRACT_SHAPE",
            "'contract' must contain exactly 'execution_script' and 'return_schema'.",
            stage=stage,
            path="$.contract",
        )

    execution_script = contract.get("execution_script")
    if not isinstance(execution_script, str) or not execution_script.strip():
        fail(
            "INVALID_FIELD",
            "'contract.execution_script' must be a non-empty string.",
            stage=stage,
            path="$.contract.execution_script",
        )

    return_schema = contract.get("return_schema")
    if not isinstance(return_schema, dict):
        fail(
            "INVALID_FIELD",
            "'contract.return_schema' must be a JSON Schema object.",
            stage=stage,
            path="$.contract.return_schema",
        )
    if return_schema.get("type") != "object":
        fail(
            "INVALID_RETURN_SCHEMA",
            "The execution return schema must describe a JSON object with type='object'.",
            stage=stage,
            path="$.contract.return_schema.type",
        )

    next_action = obj.get("next_action")
    if next_action not in {"execute", "revise", "exit"}:
        fail(
            "INVALID_FIELD",
            "'next_action' must be one of: execute, revise, exit.",
            stage=stage,
            path="$.next_action",
        )

    return contract, next_action


def main() -> None:
    execution_kb = load_json(EXECUTION_KB_PATH)
    context_kb = load_json(CONTEXT_KB_PATH)

    emit_metadata(
        "DIALOGUE_STARTED",
        dialogue="create_dialogue_v1",
        execution_kb_schema=execution_kb.get("schema"),
        execution_kb_version=execution_kb.get("version"),
        context_kb_schema=context_kb.get("schema"),
        context_kb_version=context_kb.get("version"),
    )

    # 1. Welcome and acquire the exact user prompt.
    seq = emit_model(
        {
            "stage": "WELCOME_AND_USER_PROMPT",
            "message": "Welcome. This dialogue will construct an executable transaction from the current user request. At each step, return only the JSON object defined by return_schema.",
            "request": "Return the exact current user prompt without rewriting it.",
            "return_schema": {
                "type": "object",
                "required": ["user_prompt"],
                "properties": {"user_prompt": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "acquire_user_prompt",
            "mandatory_context_ids": [],
        },
    )
    prompt_msg = read_json_object(stage="WELCOME_AND_USER_PROMPT", responding_to=seq)
    user_prompt = require_nonempty_string(prompt_msg, "user_prompt", stage="WELCOME_AND_USER_PROMPT")

    # 2. Prompt -> goal.
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
        metadata={
            "semantic_operation": "prompt_to_goal",
            "mandatory_context_ids": [prompt_to_goal["id"]],
        },
    )
    goal_msg = read_json_object(stage="PROMPT_TO_GOAL", responding_to=seq)
    goal = require_nonempty_string(goal_msg, "goal", stage="PROMPT_TO_GOAL")

    # 3. Goal -> retrieval queries.
    goal_to_query = context_entry(context_kb, "context.goal-to-query")
    seq = emit_model(
        {
            "stage": "GOAL_TO_QUERY",
            "goal": goal,
            "mandatory_context": goal_to_query,
            "request": "Write the execution-KB query or queries needed to retrieve useful context for this goal.",
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
        metadata={
            "semantic_operation": "goal_to_queries",
            "mandatory_context_ids": [goal_to_query["id"]],
        },
    )
    query_msg = read_json_object(stage="GOAL_TO_QUERY", responding_to=seq)
    queries = require_string_list(query_msg, "queries", stage="GOAL_TO_QUERY")

    # 4. Deterministic KB retrieval -> selectable topic projections.
    candidate_topics, retrieval_eval = search_topics(execution_kb, queries)
    select_topics = context_entry(context_kb, "context.select-topics")
    seq = emit_model(
        {
            "stage": "TOPIC_SELECTION",
            "goal": goal,
            "queries": queries,
            "candidate_topics": candidate_topics,
            "mandatory_context": select_topics,
            "request": "Select the KB topics whose full records should be supplied as context for writing the executable script.",
            "return_schema": {
                "type": "object",
                "required": ["selected_topics"],
                "properties": {
                    "selected_topics": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": len(candidate_topics),
                        "items": {
                            "type": "string",
                            "enum": [item["id"] for item in candidate_topics],
                        },
                        "uniqueItems": True,
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "select_retrieved_topics",
            "mandatory_context_ids": [select_topics["id"]],
            "retrieval_queries": queries,
            "retrieval_results": retrieval_eval,
            "candidate_topic_ids": [item["id"] for item in candidate_topics],
        },
    )
    selection_msg = read_json_object(stage="TOPIC_SELECTION", responding_to=seq)
    selected_topics = require_string_list(
        selection_msg,
        "selected_topics",
        stage="TOPIC_SELECTION",
        min_items=1,
        max_items=max(1, len(candidate_topics)),
    )

    candidate_ids = {item["id"] for item in candidate_topics}
    if len(set(selected_topics)) != len(selected_topics):
        fail(
            "DUPLICATE_SELECTION",
            "'selected_topics' must contain unique IDs.",
            stage="TOPIC_SELECTION",
            path="$.selected_topics",
        )
    invalid = [item_id for item_id in selected_topics if item_id not in candidate_ids]
    if invalid:
        fail(
            "INVALID_SELECTION",
            "Selected topic IDs must come from the candidate list: " + ", ".join(invalid),
            stage="TOPIC_SELECTION",
            path="$.selected_topics",
        )

    selected_context = resolve_selected(execution_kb, selected_topics)

    # 5. Expose the selected IDs and complete KB records, then request the
    # executable Python contract and the next lifecycle choice in one response.
    write_script = context_entry(context_kb, "context.write-execution-script")
    seq = emit_model(
        {
            "stage": "WRITE_EXECUTION_SCRIPT",
            "user_prompt": user_prompt,
            "goal": goal,
            "queries": queries,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
            "mandatory_context": write_script,
            "request": "Using the supplied context, write the complete executable Python contract. Then choose whether the controller should execute it, revise it, or exit.",
            "return_schema": {
                "type": "object",
                "required": ["contract", "next_action"],
                "properties": {
                    "contract": {
                        "type": "object",
                        "required": ["execution_script", "return_schema"],
                        "properties": {
                            "execution_script": {"type": "string", "minLength": 1},
                            "return_schema": {
                                "type": "object",
                                "description": "JSON Schema for the one JSON object the execution script must write to stdout on successful completion. Its root type must be object."
                            },
                        },
                        "additionalProperties": False,
                    },
                    "next_action": {
                        "type": "string",
                        "enum": ["execute", "revise", "exit"],
                    },
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "write_execution_contract_and_choose_next_action",
            "mandatory_context_ids": [write_script["id"]],
            "selected_topic_ids": selected_topics,
            "selected_context_count": len(selected_context),
            "terminal_response": True,
        },
    )

    final_msg = read_json_object(stage="WRITE_EXECUTION_SCRIPT", responding_to=seq)
    contract, next_action = validate_contract_response(final_msg, stage="WRITE_EXECUTION_SCRIPT")

    emit_metadata(
        "DIALOGUE_COMPLETED",
        dialogue="create_dialogue_v1",
        final_message_sequence=seq,
        next_action=next_action,
        execution_script_chars=len(contract["execution_script"]),
        selected_topic_ids=selected_topics,
    )
    # Deliberately no further stdout. The transaction wrapper can capture all
    # stdin values and use this final stdin object as the dialogue return value.


if __name__ == "__main__":
    main()
