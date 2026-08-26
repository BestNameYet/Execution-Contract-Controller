from __future__ import annotations

import json
import sys
from typing import Any, Callable


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_shape_error(error: str) -> None:
    emit({"error": error})


def receive_validated(
    previous_message: dict[str, Any],
    validator: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    while True:
        line = sys.stdin.readline()
        if line == "":
            raise RuntimeError("stdin closed before interrogation completed")

        try:
            value = json.loads(line)
            return validator(value)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            emit_shape_error(str(exc))
            emit(previous_message)


def require_exact_object(value: Any, expected_key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("stdin response must be a JSON object")

    actual_keys = set(value.keys())
    expected_keys = {expected_key}
    if actual_keys != expected_keys:
        raise TypeError(
            f"stdin response keys must be exactly {sorted(expected_keys)}; "
            f"received {sorted(actual_keys)}"
        )

    return value


def validate_q1(value: Any) -> dict[str, Any]:
    value = require_exact_object(value, "q1")
    q1 = value["q1"]
    if not isinstance(q1, list) or not all(isinstance(q, str) for q in q1):
        raise TypeError("q1 must be a JSON array of strings")
    return value


def validate_answer(value: Any) -> dict[str, Any]:
    value = require_exact_object(value, "answer")
    if not isinstance(value["answer"], str):
        raise TypeError("answer must be a string")
    return value


def validate_script(value: Any) -> dict[str, Any]:
    value = require_exact_object(value, "script")
    if not isinstance(value["script"], str):
        raise TypeError("script must be a string")
    return value


def main() -> None:
    question_message = {
        "instruction": (
            "Create a list of questions q1 in the domain of the current problem. "
            "Return only the required return schema."
        ),
        "return_schema": {
            "q1": ["<question>"]
        },
    }
    emit(question_message)

    question_response = receive_validated(question_message, validate_q1)
    q1 = question_response["q1"]

    qa1: list[dict[str, str]] = []
    for question in q1:
        answer_message = {
            "instruction": (
                "Answer the supplied question in the domain of the current problem. "
                "Return only the required return schema."
            ),
            "question": question,
            "return_schema": {
                "answer": "<answer>"
            },
        }
        emit(answer_message)

        answer_response = receive_validated(answer_message, validate_answer)
        qa1.append({"question": question, "answer": answer_response["answer"]})

    script_message = {
        "instruction": (
            "Return a script that solves the current problem. Use qa1 as a context parameter. "
            "Return only the required return schema."
        ),
        "qa1": qa1,
        "return_schema": {
            "script": "<script>"
        },
    }
    emit(script_message)

    receive_validated(script_message, validate_script)


if __name__ == "__main__":
    main()
