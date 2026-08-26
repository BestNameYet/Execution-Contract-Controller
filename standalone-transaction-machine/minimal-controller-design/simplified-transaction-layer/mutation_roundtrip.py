from __future__ import annotations

import copy
import json
import sys
from typing import Any, Callable


INSTRUCTION = "return <return schema>"
INITIAL_OBJECT: dict[str, Any] = {"counter": 0}


def set_stage_1(value: dict[str, Any]) -> None:
    value["stage_1"] = "applied"


def increment_counter(value: dict[str, Any]) -> None:
    value["counter"] = int(value.get("counter", 0)) + 1


def add_nested(value: dict[str, Any]) -> None:
    value["nested"] = {"created": True, "depth": 1}


def append_alpha(value: dict[str, Any]) -> None:
    value.setdefault("items", []).append("alpha")


def append_beta(value: dict[str, Any]) -> None:
    value.setdefault("items", []).append("beta")


def set_flag(value: dict[str, Any]) -> None:
    value["flag"] = True


def update_nested(value: dict[str, Any]) -> None:
    value.setdefault("nested", {})["depth"] = 2


def set_status(value: dict[str, Any]) -> None:
    value["status"] = "mutating"


def add_summary(value: dict[str, Any]) -> None:
    value["summary"] = {
        "item_count": len(value.get("items", [])),
        "counter": value.get("counter"),
    }


def mark_complete(value: dict[str, Any]) -> None:
    value["status"] = "complete"


MUTATIONS: list[Callable[[dict[str, Any]], None]] = [
    set_stage_1,
    increment_counter,
    add_nested,
    append_alpha,
    append_beta,
    set_flag,
    update_nested,
    set_status,
    add_summary,
    mark_complete,
]


def message_for(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": INSTRUCTION,
        "return_schema": {
            "object": copy.deepcopy(value),
        },
    }


def extract_object(message: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(message["return_schema"]["object"])


def emit_stdout(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_audit(stdin_copies: list[dict[str, Any]], stdout_copies: list[dict[str, Any]]) -> None:
    audit = {
        "audit": {
            "stdin_objects": stdin_copies,
            "stdout_objects": stdout_copies,
        }
    }
    sys.stderr.write(json.dumps(audit, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def main() -> None:
    current = copy.deepcopy(INITIAL_OBJECT)
    stdin_copies: list[dict[str, Any]] = []
    stdout_copies: list[dict[str, Any]] = []

    initial_message = message_for(current)
    stdout_copies.append(copy.deepcopy(initial_message["return_schema"]["object"]))
    emit_stdout(initial_message)

    for mutation in MUTATIONS:
        line = sys.stdin.readline()
        if line == "":
            raise RuntimeError("stdin closed before all mutations were applied")

        received_message = json.loads(line)
        received_object = extract_object(received_message)
        stdin_copies.append(copy.deepcopy(received_object))

        mutation(received_object)
        current = received_object

        outbound_message = message_for(current)
        stdout_copies.append(copy.deepcopy(outbound_message["return_schema"]["object"]))
        emit_stdout(outbound_message)

    emit_audit(stdin_copies, stdout_copies)


if __name__ == "__main__":
    main()
