from __future__ import annotations

import json
import sys
from typing import Any


def _emit(value: Any) -> None:
    sys.stdout.write(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    sys.stdout.write("\n")
    sys.stdout.flush()


def _read_object() -> dict[str, Any]:
    line = sys.stdin.readline()
    if line == "":
        raise EOFError("model response was not received on stdin")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


def _read_q1() -> list[str]:
    response = _read_object()
    if set(response) != {"q1"}:
        raise ValueError("question response must contain exactly the field 'q1'")
    q1 = response["q1"]
    if not isinstance(q1, list) or any(
        not isinstance(question, str) or not question.strip() for question in q1
    ):
        raise ValueError("q1 must be an array of non-empty question strings")
    return list(q1)


def _read_answer() -> Any:
    response = _read_object()
    if set(response) != {"answer"}:
        raise ValueError("answer response must contain exactly the field 'answer'")
    return response["answer"]


def main() -> int:
    _emit(
        {
            "instruction": (
                "Return a question list q1 in the domain of the current user's problem. "
                "Include the questions needed to solve the problem. Return only the required JSON."
            ),
            "output_schema": {"q1": ["question string"]},
        }
    )

    q1 = _read_q1()
    qa1: list[dict[str, Any]] = []

    for question in q1:
        _emit(
            {
                "instruction": "Answer this question. Return only the required JSON.",
                "question": question,
                "output_schema": {"answer": "any JSON value"},
            }
        )
        qa1.append({"question": question, "answer": _read_answer()})

    _emit(
        {
            "instruction": (
                "Return a well-formed JSON object with exactly one field, 'script', containing "
                "executable Python source that solves the current user's problem. Use qa1 as a "
                "context parameter. Return only the required JSON."
            ),
            "qa1": qa1,
            "output_schema": {"script": "string"},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
