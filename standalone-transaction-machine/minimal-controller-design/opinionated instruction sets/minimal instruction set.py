from __future__ import annotations

import importlib.util
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


def run() -> dict[str, Any]:
    initial_script = INITIAL_PATH.read_text(encoding="utf-8")
    do_transaction = _load_do_transaction()
    return do_transaction(
        initial_script,
        receipt_dir=RECEIPT_DIR,
    )


if __name__ == "__main__":
    run()
