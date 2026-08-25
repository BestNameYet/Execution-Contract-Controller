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


def _request_envelope(stage_state: Mapping[str, Any], receipt_dir: str | os.PathLike[str]) -> dict[str, Any]:
    state = _require_object(dict(stage_state), "stage state")
    if not isinstance(state.get("model_request"), dict):
        raise StageValidationError("stage state must contain model_request")
    return {
        "type": "MODEL_REQUEST",
        "receipt_dir": str(Path(receipt_dir).expanduser().resolve()),
        "state": state,
    }


def start_initial(
    user_prompt: str,
    *,
    receipt_dir: str | os.PathLike[str] = "./transaction-receipts",
) -> dict[str, Any]:
    """Start the machine and return the first model request. No model handle is required."""
    if not isinstance(user_prompt, str):
        raise TypeError("user_prompt must be a string")

    state = _run_stage_subprocess(
        "capture_1",
        {"user_prompt": user_prompt, "attempt": 1},
    )
    return _request_envelope(state, receipt_dir)


def resume_initial(
    machine_state: Mapping[str, Any],
    model_response: Mapping[str, Any],
) -> dict[str, Any]:
    """Advance one model-response boundary and return the next request or COMPLETE."""
    envelope = _require_object(dict(machine_state), "machine state")
    _require_exact_keys(envelope, {"type", "receipt_dir", "state"}, "machine state")
    if envelope["type"] != "MODEL_REQUEST":
        raise StageValidationError("machine state type must be MODEL_REQUEST")
    receipt_dir = envelope["receipt_dir"]
    if not isinstance(receipt_dir, str) or not receipt_dir:
        raise StageValidationError("receipt_dir must be a non-empty string")

    stage_state = _require_object(envelope["state"], "machine stage state")
    next_stage = stage_state.get("next_stage")
    if next_stage not in {"capture_2", "capture_3", "capture_4"}:
        raise StageValidationError("machine stage state has no valid next_stage")
    if not isinstance(model_response, Mapping):
        raise StageValidationError("model_response must be a JSON object")

    stage_input = dict(stage_state)
    stage_input["model_response"] = dict(model_response)
    output = _run_stage_subprocess(next_stage, stage_input)

    if output.get("restart_at") == "capture_1":
        restart_state = _run_stage_subprocess(
            "capture_1",
            {
                "user_prompt": output["user_prompt"],
                "attempt": output["attempt"],
            },
        )
        return _request_envelope(restart_state, receipt_dir)

    if "script" in output:
        from minimal_controller import do_transaction

        result = do_transaction(output["script"], receipt_dir=receipt_dir)
        return {
            "type": "COMPLETE",
            "receipt_dir": receipt_dir,
            "final_state": output,
            "result": result,
        }

    return _request_envelope(output, receipt_dir)


def _write_stdout_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")


def _cli() -> int:
    try:
        if len(sys.argv) == 5 and sys.argv[1] == "--stage" and sys.argv[3] == "--state-file":
            stage_name = sys.argv[2]
            state_path = Path(sys.argv[4])
            input_state = json.loads(state_path.read_text(encoding="utf-8"))
            _write_stdout_json(run_stage(stage_name, input_state))
            return 0

        if len(sys.argv) == 3 and sys.argv[1] == "--start-file":
            start_path = Path(sys.argv[2])
            start_input = json.loads(start_path.read_text(encoding="utf-8"))
            start_obj = _require_object(start_input, "start input")
            allowed = {"user_prompt", "receipt_dir"}
            extra = set(start_obj) - allowed
            if "user_prompt" not in start_obj or extra:
                raise StageValidationError(
                    f"start input must contain user_prompt and optional receipt_dir; extra={sorted(extra)}"
                )
            output = start_initial(
                start_obj["user_prompt"],
                receipt_dir=start_obj.get("receipt_dir", "./transaction-receipts"),
            )
            _write_stdout_json(output)
            return 0

        if (
            len(sys.argv) == 5
            and sys.argv[1] == "--resume-file"
            and sys.argv[3] == "--response-file"
        ):
            machine_state = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
            model_response = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
            _write_stdout_json(resume_initial(machine_state, model_response))
            return 0

        print(
            "usage:\n"
            "  initial.py --start-file <json-path>\n"
            "  initial.py --resume-file <machine-state-json> --response-file <model-response-json>\n"
            "  initial.py --stage <capture_1|capture_2|capture_3|capture_4> --state-file <path>",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
