#!/usr/bin/env python3
"""Run the automatic CREATE transaction over this process's stdin/stdout.

Protocol
--------
stdin  : JSON responses from the connected model
stdout : JSON dialogue messages to the model, followed by the validated CREATE
         transaction result as the final stdout JSON object
stderr : diagnostics/errors

The CREATE transaction definition remains authoritative. This runner only loads
that initial transaction and executes it through the generic transaction()
primitive.
"""

from __future__ import annotations

import json
import sys

from transaction_runtime import TransactionError, initial_transaction, transaction


def main() -> None:
    try:
        outcome = transaction(
            initial_transaction(),
            model_stdin=sys.stdin,
            model_stdout=sys.stdout,
        )
    except TransactionError as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.stderr.flush()
        raise SystemExit(2)

    # The model-facing terminal value is only the CREATE transaction result.
    # outcome.transition is control-plane state for the higher-level runtime;
    # outcome.receipt is record-plane state and is emitted separately by the
    # transaction runtime when TRANSACTION_RECEIPT_FD is configured.
    sys.stdout.write(json.dumps(outcome.result, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
