# Standalone Transaction Machine

This folder is intentionally independent of the Execution Contract Controller runtime. It uses only the Python standard library and does not import `runtime-source`, the runtime carrier, the knowledge base, or the bootstrap.

## Contract

`do_transaction(object)` is the machine-facing primitive. Each invocation:

1. creates a transaction identity and automatically derives `parent_transaction_id` and `depth` from any active enclosing transaction;
2. runs the optional work function (or treats the supplied object itself as the result when no work function is supplied);
3. captures child transaction IDs when nested `do_transaction(...)` calls occur;
4. builds a complete transaction receipt;
5. validates the receipt and its self-hash before writing;
6. writes the receipt atomically to persistent filesystem storage, flushes it with `fsync`, and fsyncs the containing directory;
7. re-reads the persisted receipt, validates it again, and verifies its content hash;
8. returns success only with a `verification.verified == true` receipt-verification object.

Failures are also written and verified before the original exception is re-raised. The exception receives a `transaction_receipt` attribute containing the persisted failure evidence.

## Nested transactions

```python
from transaction_machine import TransactionMachine

machine = TransactionMachine("./transaction-store")

def outer_work():
    child = machine.do_transaction({"name": "child"})
    return {"child_id": child["transaction_id"]}

outer = machine.do_transaction({"name": "outer"}, outer_work)
assert outer["verification"]["verified"] is True
```

The child's receipt records the outer transaction as its parent. The outer receipt records the child transaction ID in its `children` array.

## One-call API

```python
from transaction_machine import do_transaction

receipt = do_transaction({"operation": "example"}, store_path="./transaction-store")
```

## CLI

```bash
python transaction_machine.py '{"operation":"example"}' --store ./transaction-store
```

Receipts are stored as canonical JSON at:

```text
<store>/receipts/<transaction_id>.json
```
