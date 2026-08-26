from __future__ import annotations

import json
import sys
from typing import Any, Callable


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read_json_object() -> tuple[dict[str, Any] | None, str | None]:
    line = sys.stdin.readline()
    if line == "":
        raise RuntimeError("stdin closed before interrogation completed")

    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None, "stdin response must be valid JSON"

    if not isinstance(value, dict):
        return None, "stdin response must be a JSON object"

    return value, None


def receive_valid(
    previous_message: dict[str, Any],
    validator: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    while True:
        value, error = _read_json_object()
        if error is None and value is not None:
            error = validator(value)

        if error is None and value is not None:
            return value

        emit(
            {
                "error": error,
                "repeat": previous_message,
            }
        )


def validate_q1(value: dict[str, Any]) -> str | None:
    if set(value.keys()) != {"q1"}:
        return "stdin response keys must be exactly ['q1']"
    q1 = value["q1"]
    if not isinstance(q1, list) or not all(isinstance(q, str) for q in q1):
        return "q1 must be a JSON array of strings"
    return None


def validate_answer(value: dict[str, Any]) -> str | None:
    if set(value.keys()) != {"answer"}:
        return "stdin response keys must be exactly ['answer']"
    if not isinstance(value["answer"], str):
        return "answer must be a string"
    return None


def validate_script(value: dict[str, Any]) -> str | None:
    if set(value.keys()) != {"script"}:
        return "stdin response keys must be exactly ['script']"
    if not isinstance(value["script"], str):
        return "script must be a string"
    return None


def main() -> int:
    question_request = {
        "instruction": (
            "Create a list of questions q1 in the domain of the current problem. "
            "Return only the required return schema."
        ),
        "return_schema": {
            "q1": ["<question>"]
        },
    }
    emit(question_request)

    question_response = receive_valid(question_request, validate_q1)
    q1 = question_response["q1"]

    qa1: list[dict[str, str]] = []
    for question in q1:
        answer_request = {
            "instruction": (
                "Answer the supplied question in the domain of the current problem. "
                "Return only the required return schema."
            ),
            "question": question,
            "return_schema": {
                "answer": "<answer>"
            },
        }
        emit(answer_request)

        answer_response = receive_valid(answer_request, validate_answer)
        qa1.append({"question": question, "answer": answer_response["answer"]})

    script_request = {
        "instruction": (
            "Return a script that solves the current problem. Use qa1 as a context parameter. "
            "Return only the required return schema."
        ),
        "qa1": qa1,
        "return_schema": {
            "script": "<script>"
        },
    }
    emit(script_request)

    receive_valid(script_request, validate_script)

    emit({"message": "Thanks, that completes the interrogation."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
