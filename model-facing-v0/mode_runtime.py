#!/usr/bin/env python3
"""Higher-level transaction mode router.

CREATE is automatic on initialization. There is no synthetic transition into
CREATE. After any transaction that returns a control-plane transition, this
module resolves that transition into the next transaction definition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from transaction_runtime import TransactionOutcome, execution_definition

HERE = Path(__file__).resolve().parent
DEFAULT_MODE = HERE / "transaction_mode.json"


class ModeError(RuntimeError):
    pass


def load_mode(path: str | Path = DEFAULT_MODE) -> tuple[dict[str, Any], Path]:
    mode_path = Path(path).resolve()
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    if not isinstance(mode, dict) or mode.get("schema") != "transaction-mode-v1":
        raise ModeError("mode definition must use schema transaction-mode-v1")
    return mode, mode_path.parent


def initialize(path: str | Path = DEFAULT_MODE) -> Path:
    """Return the automatic initial CREATE transaction definition."""
    mode, base = load_mode(path)
    initial = mode.get("initial_transaction")
    if not isinstance(initial, dict) or initial.get("automatic") is not True:
        raise ModeError("mode must declare one automatic initial transaction")
    ref = initial.get("definition_ref")
    if not isinstance(ref, str) or not ref:
        raise ModeError("initial transaction requires definition_ref")
    return (base / ref).resolve()


def next_transaction(
    outcome: TransactionOutcome,
    path: str | Path = DEFAULT_MODE,
) -> dict[str, Any] | Path | None:
    """Resolve outcome.transition into the next transaction definition.

    Returns:
      dict  - dynamically constructed transaction definition
      Path  - referenced static transaction definition
      None  - terminal EXIT
    """
    transition = outcome.transition
    if transition is None:
        return None

    mode, base = load_mode(path)
    routes = mode.get("transition_routes")
    if not isinstance(routes, dict) or transition not in routes:
        raise ModeError(f"no route exists for transition {transition!r}")
    route = routes[transition]
    if not isinstance(route, dict):
        raise ModeError(f"route for {transition!r} must be an object")

    kind = route.get("kind")
    if kind == "terminal":
        return None
    if kind == "execution_from_previous_result":
        return execution_definition(outcome.result)
    if kind == "definition_ref":
        ref = route.get("definition_ref")
        if not isinstance(ref, str) or not ref:
            raise ModeError(f"route for {transition!r} requires definition_ref")
        return (base / ref).resolve()

    raise ModeError(f"unsupported route kind {kind!r} for transition {transition!r}")
