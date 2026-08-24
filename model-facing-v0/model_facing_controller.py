#!/usr/bin/env python3
"""Minimal model-facing CREATE controller.

Protocol (newline-delimited JSON over stdin/stdout):

1. Controller asks model for the exact user prompt.
2. Controller injects mandatory prompt->goal KB context; model returns {"goal": ...}.
3. Controller injects mandatory goal->query KB context; model returns {"queries": [...]}.
4. Controller deterministically searches the execution KB, injects mandatory
   topic-selection context, and asks the model to return selected topic IDs.
5. Controller validates those IDs, resolves them to full KB records, emits the
   selected context, and exits.

This controller intentionally stops at topic selection. It does not construct,
validate, revise, or execute a contract.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXECUTION_KB_PATH = HERE / "execution_knowledge_base.json"
CONTEXT_KB_PATH = HERE / "model_facing_context_kb.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str, *, path: str | None = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        error["path"] = path
    emit({"stage": "PROTOCOL_ERROR", "error": error})
    raise SystemExit(2)


def read_json_object() -> dict[str, Any]:
    line = sys.stdin.readline()
    if line == "":
        fail("EOF", "Expected a JSON object from the model but stdin closed.")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        fail("INVALID_JSON", f"Model response is not valid JSON: {exc.msg}.")
    if not isinstance(value, dict):
        fail("INVALID_SHAPE", "Model response must be a JSON object.")
    return value


def require_nonempty_string(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail("INVALID_FIELD", f"'{key}' must be a non-empty string.", path=f"$.{key}")
    return value


def require_string_list(obj: dict[str, Any], key: str, *, min_items: int = 1, max_items: int = 8) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        fail("INVALID_FIELD", f"'{key}' must be an array of strings.", path=f"$.{key}")
    if not (min_items <= len(value) <= max_items):
        fail(
            "INVALID_CARDINALITY",
            f"'{key}' must contain between {min_items} and {max_items} items.",
            path=f"$.{key}",
        )
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            fail("INVALID_FIELD", f"'{key}[{i}]' must be a non-empty string.", path=f"$.{key}[{i}]")
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


def search_topics(execution_kb: dict[str, Any], queries: list[str]) -> list[dict[str, Any]]:
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

    # If lexical retrieval produces no hit, expose a bounded deterministic
    # fallback rather than inventing semantic results in the controller.
    if not scored:
        fallback = [r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)]
        fallback.sort(key=lambda r: r["id"])
        selected = fallback[:top_k]
    else:
        selected = [record for _, _, record in scored[:top_k]]

    return [
        {
            "id": record["id"],
            "type": record.get("type"),
            "summary": record.get("summary", ""),
        }
        for record in selected
    ]


def resolve_selected(execution_kb: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    records = execution_kb.get("records", [])
    by_id = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    return [by_id[item_id] for item_id in ids]


def main() -> None:
    execution_kb = load_json(EXECUTION_KB_PATH)
    context_kb = load_json(CONTEXT_KB_PATH)

    # Stage 0: acquire the exact user prompt from the model-facing side.
    emit(
        {
            "stage": "USER_PROMPT",
            "request": "Return the exact current user prompt.",
            "return_schema": {
                "type": "object",
                "required": ["user_prompt"],
                "properties": {"user_prompt": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        }
    )
    prompt_msg = read_json_object()
    user_prompt = require_nonempty_string(prompt_msg, "user_prompt")

    # Stage 1: prompt -> goal.
    emit(
        {
            "stage": "PROMPT_TO_GOAL",
            "user_prompt": user_prompt,
            "mandatory_context": context_entry(context_kb, "context.prompt-to-goal"),
            "return_schema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        }
    )
    goal_msg = read_json_object()
    goal = require_nonempty_string(goal_msg, "goal")

    # Stage 2: goal -> KB query list.
    emit(
        {
            "stage": "GOAL_TO_QUERY",
            "goal": goal,
            "mandatory_context": context_entry(context_kb, "context.goal-to-query"),
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
        }
    )
    query_msg = read_json_object()
    queries = require_string_list(query_msg, "queries")

    # Stage 3: deterministic retrieval -> semantic topic selection.
    candidate_topics = search_topics(execution_kb, queries)
    emit(
        {
            "stage": "TOPIC_SELECTION",
            "goal": goal,
            "queries": queries,
            "candidate_topics": candidate_topics,
            "mandatory_context": context_entry(context_kb, "context.select-topics"),
            "return_schema": {
                "type": "object",
                "required": ["selected_topics"],
                "properties": {
                    "selected_topics": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "string",
                            "enum": [item["id"] for item in candidate_topics],
                        },
                        "uniqueItems": True,
                    }
                },
                "additionalProperties": False,
            },
        }
    )
    selection_msg = read_json_object()
    selected_topics = require_string_list(
        selection_msg,
        "selected_topics",
        min_items=1,
        max_items=max(1, len(candidate_topics)),
    )

    candidate_ids = {item["id"] for item in candidate_topics}
    if len(set(selected_topics)) != len(selected_topics):
        fail("DUPLICATE_SELECTION", "'selected_topics' must contain unique IDs.", path="$.selected_topics")
    invalid = [item_id for item_id in selected_topics if item_id not in candidate_ids]
    if invalid:
        fail(
            "INVALID_SELECTION",
            "Selected topic IDs must come from the candidate list: " + ", ".join(invalid),
            path="$.selected_topics",
        )

    selected_context = resolve_selected(execution_kb, selected_topics)
    emit(
        {
            "stage": "TOPIC_SELECTION_COMPLETE",
            "user_prompt": user_prompt,
            "goal": goal,
            "queries": queries,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
        }
    )


if __name__ == "__main__":
    main()
