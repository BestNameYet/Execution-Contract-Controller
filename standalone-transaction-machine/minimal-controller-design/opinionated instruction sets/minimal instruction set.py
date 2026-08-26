from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
INITIAL_PATH = HERE / "initial.py"
TRANSACTION_LAYER_PATH = HERE.parent / "simplified-transaction-layer" / "transaction_layer.py"
INTERROGATION_RECEIPT_DIR = HERE / "interrogation-receipts"
EXECUTION_RECEIPT_DIR = HERE / "execution-receipts"


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


def read_receipt(receipt_path: Path) -> dict[str, Any]:
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("transaction receipt must be a JSON object")
    return value


def extract_generated_script(receipt: dict[str, Any]) -> str:
    """Mechanically return the final valid stdin JSON object's script field."""
    events = receipt.get("events")
    if not isinstance(events, list):
        raise TypeError("transaction receipt events must be a list")

    for event in reversed(events):
        if not isinstance(event, dict) or event.get("stream") != "stdin":
            continue
        try:
            value = json.loads(event["data"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if set(value.keys()) == {"script"} and isinstance(value["script"], str):
            return value["script"]

    raise RuntimeError("generated script was not found in interrogation receipt")


def run() -> dict[str, str]:
    do_transaction = _load_do_transaction()
    run_id = uuid.uuid4().hex

    interrogation_receipt_path = (
        INTERROGATION_RECEIPT_DIR / f"interrogation_{run_id}.json"
    )
    execution_receipt_path = EXECUTION_RECEIPT_DIR / f"execution_{run_id}.json"

    initial_script = INITIAL_PATH.read_text(encoding="utf-8")
    do_transaction(
        initial_script,
        receipt_file=interrogation_receipt_path,
    )

    interrogation_receipt = read_receipt(interrogation_receipt_path)
    generated_script = extract_generated_script(interrogation_receipt)

    do_transaction(
        generated_script,
        receipt_file=execution_receipt_path,
    )

    return {
        "interrogation_receipt": str(interrogation_receipt_path),
        "execution_receipt": str(execution_receipt_path),
    }


if __name__ == "__main__":
    print(json.dumps(run(), separators=(",", ":")))
