from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


class ChildExecutionError(RuntimeError):
    """Raised when the child execution environment fails."""


class ChildOutcomeValidationError(ValueError):
    """Raised when the child does not return a valid JSON outcome object."""


def _validate_script(script: Any) -> str:
    if not isinstance(script, str):
        raise TypeError("script must be a string")
    if not script.strip():
        raise ValueError("script must be a non-empty string")
    return script


def _run_child(script: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise ChildExecutionError(
            f"child exited with code {completed.returncode}: {completed.stderr.rstrip()}"
        )

    try:
        outcome = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ChildOutcomeValidationError(
            "child stdout must be exactly one JSON object"
        ) from exc

    if not isinstance(outcome, dict):
        raise ChildOutcomeValidationError("child outcome must be a JSON object")

    return outcome


def do_transaction(script: str | None = None) -> dict[str, Any] | None:
    """Execute one transaction and recursively execute the script it generates.

    ``do_transaction()`` with no script halts the machine.

    A non-empty script is executed in a child Python process. The child must
    return a JSON object to the parent on stdout. If that outcome contains a
    ``script`` field, the parent validates it and starts the next transaction
    by calling ``do_transaction(next_script)``. If the outcome contains no
    ``script`` field, the parent calls ``do_transaction()`` to halt and returns
    the terminal child outcome.

    Other child-outcome fields are not interpreted or restricted here.
    """

    if script is None:
        return None

    current_script = _validate_script(script)
    outcome = _run_child(current_script)

    if "script" not in outcome:
        do_transaction()
        return outcome

    next_script = _validate_script(outcome["script"])
    return do_transaction(next_script)
