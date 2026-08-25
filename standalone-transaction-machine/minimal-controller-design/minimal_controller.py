from __future__ import annotations

import json
from typing import Any


SCRIPT_FIELDS = ("script", "solution", "event", "result")


def do_transaction(item: dict[str, Any]) -> Any:
    """Execute a Python script literal carried by one incoming JSON object.

    The first string value found under script, solution, event, or result is
    executed as Python. The script receives the original object as
    ``transaction`` and must assign its JSON-compatible return object to
    ``output``.
    """

    if not isinstance(item, dict):
        raise TypeError("do_transaction expects one JSON object")

    script: str | None = None
    source_field: str | None = None

    for field in SCRIPT_FIELDS:
        value = item.get(field)
        if isinstance(value, str):
            script = value
            source_field = field
            break

    if script is None or source_field is None:
        raise ValueError(
            "no Python script literal found in any of: "
            + ", ".join(SCRIPT_FIELDS)
        )

    scope: dict[str, Any] = {
        "transaction": item,
        "output": None,
    }
    exec(compile(script, f"<transaction:{source_field}>", "exec"), scope, scope)

    output = scope["output"]
    try:
        json.dumps(output, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError("transaction script output must be JSON-compatible") from exc

    return output
