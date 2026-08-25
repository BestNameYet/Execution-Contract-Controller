from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


INSTRUCTION_1 = (
    "Create the questions required to solve the supplied user prompt. "
    "Return only JSON with exactly one key, 'questions', whose value is an array of question strings."
)

INSTRUCTION_2 = (
    "Answer every supplied question. Preserve each question exactly and in the same order. "
    "Return only JSON with exactly one key, 'qa', whose value is an array of objects with exactly "
    "the keys 'question' and 'answer'."
)

INSTRUCTION_3 = (
    "Use the supplied question/answer pairs as parameters to make the executable solution script. "
    "Return only JSON with exactly one key, 'script', whose value is the solution script."
)


class StageValidationError(ValueError):
    """Raised when a staged input or model response has an invalid deterministic shape."""


class StageExecutionError(RuntimeError):
    """Raised when a fresh stage subprocess fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _make_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = dict(payload)
    snapshot["timestamp"] = _utc_now()
    snapshot["sha256"] = _sha256(snapshot)
    return snapshot


def _verify_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise StageValidationError("snapshot must be an object")
    if not isinstance(snapshot.get("timestamp"), str) or not snapshot["timestamp"]:
        raise StageValidationError("snapshot timestamp must be a non-empty string")
    actual = snapshot.get("sha256")
    if not isinstance(actual, str) or not actual:
        raise StageValidationError("snapshot sha256 must be a non-empty string")
    payload = dict(snapshot)
    payload.pop("sha256")
    if actual != _sha256(payload):
        raise StageValidationError("snapshot contents do not match immutable sha256")
    return snapshot


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StageValidationError(f"{name} must be a JSON object")
    return value


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    actual = set(value.keys())
    if actual != keys:
        raise StageValidationError(
            f"{name} fields do not match required shape; missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
        )


def _questions_from_response(response: Any) -> list[str]:
    obj = _require_object(response, "question response")
    _require_exact_keys(obj, {"questions"}, "question response")
    questions = obj["questions"]
    if not isinstance(questions, list):
        raise StageValidationError("questions must be an array")
    if any(not isinstance(question, str) or not question.strip() for question in questions):
        raise StageValidationError("every question must be a non-empty string")
    return list(questions)


def _qa_from_response(response: Any) -> list[dict[str, Any]] | None:
    if not isinstance(response, dict) or set(response.keys()) != {"qa"}:
        return None
    qa = response["qa"]
    if not isinstance(qa, list):
        return None
    pairs: list[dict[str, Any]] = []
    for pair in qa:
        if not isinstance(pair, dict) or set(pair.keys()) != {"question", "answer"}:
            return None
        if not isinstance(pair["question"], str):
            return None
        pairs.append({"question": pair["question"], "answer": pair["answer"]})
    return pairs


def capture_1(input_state: Mapping[str, Any]) -> dict[str, Any]:
    """Capture the user prompt and produce deterministic instruction 1."""
    state = _require_object(dict(input_state), "capture_1 input")
    _require_exact_keys(state, {"user_prompt", "attempt"}, "capture_1 input")
    prompt = state["user_prompt"]
    attempt = state["attempt"]
    if not isinstance(prompt, str):
        raise StageValidationError("user_prompt must be a string")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise StageValidationError("attempt must be a positive integer")

    prompt_snapshot = _make_snapshot({"user_prompt": prompt})
    return {
        "attempt": attempt,
        "prompt_snapshot": prompt_snapshot,
        "model_request": {
            "instruction": INSTRUCTION_1,
            "payload": dict(prompt_snapshot),
        },
        "next_stage": "capture_2",
    }


def capture_2(input_state: Mapping[str, Any]) -> dict[str, Any]:
    """Capture the model's question set and produce deterministic instruction 2."""
    state = _require_object(dict(input_state), "capture_2 input")
    _require_exact_keys(
        state,
        {"attempt", "prompt_snapshot", "model_request", "next_stage", "model_response"},
        "capture_2 input",
    )
    if state["next_stage"] != "capture_2":
        raise StageValidationError("capture_2 input has the wrong next_stage")
    prompt_snapshot = _verify_snapshot(state["prompt_snapshot"])
    questions = _questions_from_response(state["model_response"])
    questions_snapshot = _make_snapshot({"questions": questions})

    return {
        "attempt": state["attempt"],
        "prompt_snapshot": dict(prompt_snapshot),
        "questions_snapshot": questions_snapshot,
        "model_request": {
            "instruction": INSTRUCTION_2,
            "payload": {"questions": list(questions)},
        },
        "next_stage": "capture_3",
    }


def capture_3(input_state: Mapping[str, Any]) -> dict[str, Any]:
    """Capture QA, verify question identity, and produce instruction 3 or restart A."""
    state = _require_object(dict(input_state), "capture_3 input")
    _require_exact_keys(
        state,
        {
            "attempt",
            "prompt_snapshot",
            "questions_snapshot",
            "model_request",
            "next_stage",
            "model_response",
        },
        "capture_3 input",
    )
    if state["next_stage"] != "capture_3":
        raise StageValidationError("capture_3 input has the wrong next_stage")
    _verify_snapshot(state["prompt_snapshot"])
    questions_snapshot = _verify_snapshot(state["questions_snapshot"])
    original_questions = questions_snapshot.get("questions")
    if not isinstance(original_questions, list):
        raise StageValidationError("questions snapshot has invalid questions")

    qa = _qa_from_response(state["model_response"])
    returned_questions = None if qa is None else [pair["question"] for pair in qa]
    if returned_questions != original_questions:
        return {
            "restart_at": "capture_1",
            "reason": "question_mismatch",
            "attempt": state["attempt"] + 1,
            "user_prompt": state["prompt_snapshot"]["user_prompt"],
        }

    qa_snapshot = _make_snapshot({"qa": qa})
    return {
        "attempt": state["attempt"],
        "prompt_snapshot": dict(state["prompt_snapshot"]),
        "questions_snapshot": dict(questions_snapshot),
        "qa_snapshot": qa_snapshot,
        "model_request": {
            "instruction": INSTRUCTION_3,
            "payload": {"qa": json.loads(json.dumps(qa, ensure_ascii=False))},
        },
        "next_stage": "capture_4",
    }


def capture_4(input_state: Mapping[str, Any]) -> dict[str, Any]:
    """Capture and validate the solution script produced from validated QA."""
    state = _require_object(dict(input_state), "capture_4 input")
    _require_exact_keys(
        state,
        {
            "attempt",
            "prompt_snapshot",
            "questions_snapshot",
            "qa_snapshot",
            "model_request",
            "next_stage",
            "model_response",
        },
        "capture_4 input",
    )
    if state["next_stage"] != "capture_4":
        raise StageValidationError("capture_4 input has the wrong next_stage")
    _verify_snapshot(state["prompt_snapshot"])
    _verify_snapshot(state["questions_snapshot"])
    _verify_snapshot(state["qa_snapshot"])

    response = _require_object(state["model_response"], "script response")
    _require_exact_keys(response, {"script"}, "script response")
    script = response["script"]
    if not isinstance(script, str) or not script.strip():
        raise StageValidationError("solution script must be a non-empty string")

    return {
        "attempt": state["attempt"],
        "prompt_snapshot": dict(state["prompt_snapshot"]),
        "questions_snapshot": dict(state["questions_snapshot"]),
        "qa_snapshot": dict(state["qa_snapshot"]),
        "script": script,
    }


STAGES: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "capture_1": capture_1,
    "capture_2": capture_2,
    "capture_3": capture_3,
    "capture_4": capture_4,
}


def run_stage(stage_name: str, input_state: Mapping[str, Any]) -> dict[str, Any]:
    try:
        stage = STAGES[stage_name]
    except KeyError as exc:
        raise StageValidationError(f"unknown stage: {stage_name}") from exc
    return stage(input_state)


def _run_stage_subprocess(stage_name: str, input_state: Mapping[str, Any]) -> dict[str, Any]:
    """Run exactly one stage in a fresh Python subprocess with no stdin."""
    encoded = _canonical_bytes(dict(input_state)) + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix="initial-stage-", suffix=".json")
    state_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--stage", stage_name, "--state-file", str(state_path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        state_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        raise StageExecutionError(
            f"stage {stage_name} failed with code {completed.returncode}: {completed.stderr.rstrip()}"
        )
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise StageExecutionError(f"stage {stage_name} did not return one JSON object") from exc
    if not isinstance(parsed, dict):
        raise StageExecutionError(f"stage {stage_name} output must be a JSON object")
    return parsed


def _cli() -> int:
    if len(sys.argv) != 5 or sys.argv[1] != "--stage" or sys.argv[3] != "--state-file":
        print(
            "usage: initial.py --stage <capture_1|capture_2|capture_3|capture_4> --state-file <path>",
            file=sys.stderr,
        )
        return 2

    stage_name = sys.argv[2]
    state_path = Path(sys.argv[4])
    try:
        input_state = json.loads(state_path.read_text(encoding="utf-8"))
        output = run_stage(stage_name, input_state)
        sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
