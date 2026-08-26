from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
INITIAL_PATH = HERE / "initial.py"
TRANSACTION_LAYER_PATH = HERE.parent / "simplified-transaction-layer" / "transaction_layer.py"
RECEIPT_DIR = HERE / "transaction-receipts"


def _load_do_transaction():
    spec = importlib.util.spec_from_file_location(
        "simplified_transaction_layer",
        TRANSACTION_LAYER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load transaction layer: {TRANSACTION_LAYER_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.do_transaction


def extract_generated_script(receipt: dict[str, Any]) -> str:
    """Mechanically return the final stdin JSON object's script field."""
    for event in reversed(receipt["events"]):
        if event.get("stream") != "stdin":
            continue
        try:
            value = json.loads(event["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("script"), str):
            return value["script"]
    raise RuntimeError("generated script was not found in transaction receipt")


def run() -> str:
    initial_script = INITIAL_PATH.read_text(encoding="utf-8")
    do_transaction = _load_do_transaction()
    receipt = do_transaction(
        initial_script,
        receipt_dir=RECEIPT_DIR,
    )
    return extract_generated_script(receipt)


if __name__ == "__main__":
    print(run())
