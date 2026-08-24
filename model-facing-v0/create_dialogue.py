#!/usr/bin/env python3
"""CREATE dialogue transaction.

stdin  : newline-delimited JSON responses from the model
stdout : newline-delimited JSON messages visible to the model
stderr : diagnostics only
optional TRANSACTION_META_FD : newline-delimited JSON evaluation metadata

The final model response is an internal transaction outcome envelope:

{
  "result": {
    "execution_script": "<complete Python source>",
    "return_schema": { ... JSON Schema for execution result ... }
  },
  "transition": "execute" | "revise" | "exit"
}

`result` is the CREATE transaction's semantic product. `transition` is control
information for the higher-level mode controller. The transaction runtime owns
the receipt and keeps it off the model-visible channel.
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


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def emit_metadata(event: str, **fields: Any) -> None:
    raw_fd = os.environ.get(META_FD_ENV)
    if raw_fd is None:
        return
    try:
        fd = int(raw_fd)
        os.write(fd, (compact({"event": event, **fields}) + "\n").encode("utf-8"))
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
            f"'{key}' must be an array of {min_items}..{max_items} non-empty strings.",
            stage=stage,
            path=f"$.{key}",
        )
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            fail("INVALID_FIELD", f"'{key}[{index}]' must be a non-empty string.", stage=stage)
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
    fail("MISSING_CONTEXT_ENTRY", f"Required context entry does not exist: {entry_id}.")
    raise AssertionError("unreachable")


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def retrieval_text(record: dict[str, Any]) -> str:
    return json.dumps(record.get("retrieval", {}), ensure_ascii=False, sort_keys=True)


def score_record(record: dict[str, Any], queries: list[str], priors: dict[str, Any]) -> float:
    rid = set(tokens(str(record.get("id", ""))))
    summary = set(tokens(str(record.get("summary", ""))))
    retrieval = set(tokens(retrieval_text(record)))
    searchable = " ".join(tokens(str(record.get("id", "")) + " " + str(record.get("summary", "")) + " " + retrieval_text(record)))
    score = 0.0
    for query in queries:
        q = tokens(query)
        if not q:
            continue
        for token in q:
            if token in rid:
                score += 4.0
            if token in summary:
                score += 3.0
            if token in retrieval:
                score += 1.0
        phrase = " ".join(q)
        if phrase and phrase in searchable:
            score += 8.0
    try:
        score *= float(priors.get(record.get("type"), 1.0))
    except (TypeError, ValueError):
        pass
    return score


def search_topics(execution_kb: dict[str, Any], queries: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = execution_kb.get("records")
    if not isinstance(records, list):
        fail("INVALID_EXECUTION_KB", "Execution KB must contain a 'records' array.")
    retrieval_cfg = execution_kb.get("retrieval") if isinstance(execution_kb.get("retrieval"), dict) else {}
    priors = retrieval_cfg.get("type_prior") if isinstance(retrieval_cfg.get("type_prior"), dict) else {}
    top_k = retrieval_cfg.get("default_top_k", 8)
    if not isinstance(top_k, int) or top_k < 1:
        top_k = 8

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        score = score_record(record, queries, priors)
        if score > 0:
            scored.append((score, record["id"], record))
    scored.sort(key=lambda item: (-item[0], item[1]))

    eval_rows: list[dict[str, Any]] = []
    if scored:
        selected = [row[2] for row in scored[:top_k]]
        eval_rows = [{"id": row[1], "score": row[0], "fallback": False} for row in scored[:top_k]]
    else:
        selected = sorted(
            [record for record in records if isinstance(record, dict) and isinstance(record.get("id"), str)],
            key=lambda record: record["id"],
        )[:top_k]
        eval_rows = [{"id": record["id"], "score": 0.0, "fallback": True} for record in selected]

    candidates = [
        {"id": record["id"], "type": record.get("type"), "summary": record.get("summary", "")}
        for record in selected
    ]
    return candidates, eval_rows


def resolve_selected(execution_kb: dict[str, Any], selected_ids: list[str]) -> list[dict[str, Any]]:
    records = execution_kb.get("records", [])
    by_id = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    return [by_id[item] for item in selected_ids]


def contract_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["execution_script", "return_schema"],
        "properties": {
            "execution_script": {"type": "string", "minLength": 1},
            "return_schema": {"type": "object"},
        },
        "additionalProperties": False,
    }


def validate_final(obj: dict[str, Any], *, stage: str) -> tuple[dict[str, Any], str]:
    if set(obj.keys()) != {"result", "transition"}:
        fail("INVALID_SHAPE", "Final response must contain exactly 'result' and 'transition'.", stage=stage)
    result = obj.get("result")
    if not isinstance(result, dict):
        fail("INVALID_FIELD", "'result' must be an object.", stage=stage, path="$.result")
    if set(result.keys()) != {"execution_script", "return_schema"}:
        fail("INVALID_CONTRACT_SHAPE", "'result' must contain exactly execution_script and return_schema.", stage=stage)
    if not isinstance(result.get("execution_script"), str) or not result["execution_script"].strip():
        fail("INVALID_FIELD", "execution_script must be a non-empty string.", stage=stage)
    if not isinstance(result.get("return_schema"), dict) or result["return_schema"].get("type") != "object":
        fail("INVALID_RETURN_SCHEMA", "return_schema must be a JSON object schema with root type='object'.", stage=stage)
    transition = obj.get("transition")
    if transition not in {"execute", "revise", "exit"}:
        fail("INVALID_TRANSITION", "transition must be execute, revise, or exit.", stage=stage)
    return result, transition


def main() -> None:
    execution_kb = load_json(EXECUTION_KB_PATH)
    context_kb = load_json(CONTEXT_KB_PATH)
    emit_metadata(
        "DIALOGUE_STARTED",
        dialogue="create",
        execution_kb_schema=execution_kb.get("schema"),
        execution_kb_version=execution_kb.get("version"),
        context_kb_schema=context_kb.get("schema"),
        context_kb_version=context_kb.get("version"),
    )

    seq = emit_model(
        {
            "stage": "WELCOME_AND_USER_PROMPT",
            "message": "Welcome to Transactional Knowledge Mode. Return only the JSON object defined by return_schema at each step.",
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
    prompt = require_string(read_object(stage="WELCOME_AND_USER_PROMPT", responding_to=seq), "user_prompt", stage="WELCOME_AND_USER_PROMPT")

    prompt_goal = context_entry(context_kb, "context.prompt-to-goal")
    seq = emit_model(
        {
            "stage": "PROMPT_TO_GOAL",
            "user_prompt": prompt,
            "mandatory_context": prompt_goal,
            "request": "Return the execution goal.",
            "return_schema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "prompt_to_goal", "mandatory_context_ids": [prompt_goal["id"]]},
    )
    goal = require_string(read_object(stage="PROMPT_TO_GOAL", responding_to=seq), "goal", stage="PROMPT_TO_GOAL")

    goal_query = context_entry(context_kb, "context.goal-to-query")
    seq = emit_model(
        {
            "stage": "GOAL_TO_QUERY",
            "goal": goal,
            "mandatory_context": goal_query,
            "request": "Return the execution-KB query or queries needed for this goal.",
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
        metadata={"semantic_operation": "goal_to_queries", "mandatory_context_ids": [goal_query["id"]]},
    )
    queries = require_string_list(read_object(stage="GOAL_TO_QUERY", responding_to=seq), "queries", stage="GOAL_TO_QUERY")

    candidates, retrieval_eval = search_topics(execution_kb, queries)
    selection_context = context_entry(context_kb, "context.select-topics")
    seq = emit_model(
        {
            "stage": "TOPIC_SELECTION",
            "goal": goal,
            "queries": queries,
            "candidate_topics": candidates,
            "mandatory_context": selection_context,
            "request": "Return the IDs of the KB topics whose full entries should be supplied.",
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
            "semantic_operation": "select_topics",
            "mandatory_context_ids": [selection_context["id"]],
            "retrieval": retrieval_eval,
        },
    )
    selected_ids = require_string_list(
        read_object(stage="TOPIC_SELECTION", responding_to=seq),
        "selected_topics",
        stage="TOPIC_SELECTION",
        max_items=max(1, len(candidates)),
    )
    if len(set(selected_ids)) != len(selected_ids):
        fail("DUPLICATE_SELECTION", "selected_topics must contain unique IDs.", stage="TOPIC_SELECTION")
    candidate_ids = {item["id"] for item in candidates}
    invalid = [item for item in selected_ids if item not in candidate_ids]
    if invalid:
        fail("INVALID_SELECTION", "selected_topics contains IDs not present in candidate_topics.", stage="TOPIC_SELECTION")

    selected_context = resolve_selected(execution_kb, selected_ids)
    write_context = context_entry(context_kb, "context.write-execution-script")
    final_response_schema = {
        "type": "object",
        "required": ["result", "transition"],
        "properties": {
            "result": contract_schema(),
            "transition": {"type": "string", "enum": ["execute", "revise", "exit"]},
        },
        "additionalProperties": False,
    }
    seq = emit_model(
        {
            "stage": "WRITE_EXECUTION_SCRIPT",
            "user_prompt": prompt,
            "goal": goal,
            "queries": queries,
            "selected_topics": selected_ids,
            "selected_context": selected_context,
            "mandatory_context": write_context,
            "request": "Write the complete executable Python contract as result, then choose the next transaction transition: execute, revise, or exit.",
            "return_schema": final_response_schema,
        },
        metadata={
            "semantic_operation": "write_execution_contract_and_transition",
            "mandatory_context_ids": [write_context["id"]],
            "selected_topic_ids": selected_ids,
            "terminal_response": True,
        },
    )

    final_message = read_object(stage="WRITE_EXECUTION_SCRIPT", responding_to=seq)
    result, transition = validate_final(final_message, stage="WRITE_EXECUTION_SCRIPT")
    emit_metadata(
        "DIALOGUE_COMPLETED",
        dialogue="create",
        final_message_sequence=seq,
        transition=transition,
        execution_script_chars=len(result["execution_script"]),
        selected_topic_ids=selected_ids,
    )
    # No further stdout. The transaction runtime consumes this final stdin object.


if __name__ == "__main__":
    main()
