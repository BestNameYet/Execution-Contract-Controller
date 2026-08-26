from __future__ import annotations

import json
import sys
from typing import Any


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def receive() -> dict[str, Any]:
    line = sys.stdin.readline()
    if line == "":
        raise RuntimeError("stdin closed before interrogation completed")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise TypeError("response must be a JSON object")
    return value


def main() -> None:
    emit(
        {
            "instruction": (
                "Create a list of questions q1 in the domain of the current problem. "
                "Return only the required return schema."
            ),
            "return_schema": {
                "q1": ["<question>"]
            },
        }
    )

    question_response = receive()
    q1 = question_response["q1"]
    if not isinstance(q1, list) or not all(isinstance(q, str) for q in q1):
        raise TypeError("q1 must be a JSON array of strings")

    qa1: list[dict[str, str]] = []
    for question in q1:
        emit(
            {
                "instruction": (
                    "Answer the supplied question in the domain of the current problem. "
                    "Return only the required return schema."
                ),
                "question": question,
                "return_schema": {
                    "answer": "<answer>"
                },
            }
        )

        answer_response = receive()
        answer = answer_response["answer"]
        if not isinstance(answer, str):
            raise TypeError("answer must be a string")
        qa1.append({"question": question, "answer": answer})

    emit(
        {
            "instruction": (
                "Return a script that solves the current problem. Use qa1 as a context parameter. "
                "Return only the required return schema."
            ),
            "qa1": qa1,
            "return_schema": {
                "script": "<script>"
            },
        }
    )

    script_response = receive()
    script = script_response["script"]
    if not isinstance(script, str):
        raise TypeError("script must be a string")


if __name__ == "__main__":
    main()
