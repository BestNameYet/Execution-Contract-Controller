from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import tempfile
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

RECEIPT_SCHEMA = "standalone-transaction-receipt-v1"
VERIFICATION_SCHEMA = "standalone-transaction-verification-v1"


class ReceiptValidationError(ValueError):
    """Raised when an in-memory or persisted transaction receipt is invalid."""


class ReceiptVerificationError(RuntimeError):
    """Raised when a receipt cannot be proven to match durable storage."""


@dataclass
class _ActiveTransaction:
    transaction_id: str
    parent_transaction_id: str | None
    depth: int
    children: list[str] = field(default_factory=list)


_ACTIVE_STACK: contextvars.ContextVar[tuple[_ActiveTransaction, ...]] = contextvars.ContextVar(
    "standalone_transaction_stack", default=()
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation of a Python object."""
    try:
        _canonical_bytes(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, Path):
            return {"python_type": "pathlib.Path", "value": str(value)}
        if isinstance(value, bytes):
            return {
                "python_type": "bytes",
                "encoding": "hex",
                "value": value.hex(),
            }
        if isinstance(value, Mapping):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        return {
            "python_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
        }


def _receipt_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "transaction_id",
        "parent_transaction_id",
        "depth",
        "status",
        "started_at",
        "completed_at",
        "input",
        "result",
        "error",
        "children",
        "receipt_sha256",
    }
    missing = sorted(required.difference(receipt.keys()))
    if missing:
        raise ReceiptValidationError(f"missing receipt fields: {missing}")
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise ReceiptValidationError(f"unexpected receipt schema: {receipt['schema']!r}")
    if not isinstance(receipt["transaction_id"], str) or not receipt["transaction_id"]:
        raise ReceiptValidationError("transaction_id must be a non-empty string")
    parent = receipt["parent_transaction_id"]
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise ReceiptValidationError("parent_transaction_id must be null or a non-empty string")
    depth = receipt["depth"]
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
        raise ReceiptValidationError("depth must be a non-negative integer")
    if receipt["status"] not in {"COMPLETE", "FAILED"}:
        raise ReceiptValidationError("status must be COMPLETE or FAILED")
    if not isinstance(receipt["started_at"], str) or not receipt["started_at"]:
        raise ReceiptValidationError("started_at must be a non-empty string")
    if not isinstance(receipt["completed_at"], str) or not receipt["completed_at"]:
        raise ReceiptValidationError("completed_at must be a non-empty string")
    if not isinstance(receipt["children"], list) or not all(
        isinstance(v, str) and v for v in receipt["children"]
    ):
        raise ReceiptValidationError("children must be a list of transaction ids")
    if receipt["status"] == "COMPLETE" and receipt["error"] is not None:
        raise ReceiptValidationError("COMPLETE receipt cannot contain an error")
    if receipt["status"] == "FAILED" and not isinstance(receipt["error"], dict):
        raise ReceiptValidationError("FAILED receipt must contain an error object")

    expected = _sha256(_receipt_payload(receipt))
    actual = receipt["receipt_sha256"]
    if not isinstance(actual, str) or actual != expected:
        raise ReceiptValidationError("receipt_sha256 does not match receipt contents")

    _canonical_bytes(dict(receipt))


class ReceiptStore:
    """Durable per-transaction JSON receipt store using atomic replace + fsync."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.receipts_dir = self.root / "receipts"
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self._fsync_directory(self.receipts_dir)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
        try:
            fd = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def receipt_path(self, transaction_id: str) -> Path:
        if not transaction_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in transaction_id):
            raise ValueError("transaction_id contains unsupported path characters")
        return self.receipts_dir / f"{transaction_id}.json"

    def write_and_verify(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        receipt_dict = dict(receipt)
        validate_receipt(receipt_dict)
        path = self.receipt_path(receipt_dict["transaction_id"])
        encoded = _canonical_bytes(receipt_dict) + b"\n"

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{receipt_dict['transaction_id']}.", suffix=".tmp", dir=self.receipts_dir
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            self._fsync_directory(self.receipts_dir)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            finally:
                raise

        with path.open("rb") as f:
            persisted_bytes = f.read()
        try:
            persisted = json.loads(persisted_bytes)
        except json.JSONDecodeError as exc:
            raise ReceiptVerificationError(f"persisted receipt is not valid JSON: {path}") from exc

        validate_receipt(persisted)
        if persisted != receipt_dict:
            raise ReceiptVerificationError("persisted receipt differs from the validated in-memory receipt")
        persisted_sha256 = hashlib.sha256(_canonical_bytes(persisted)).hexdigest()
        expected_persisted_sha256 = hashlib.sha256(_canonical_bytes(receipt_dict)).hexdigest()
        if persisted_sha256 != expected_persisted_sha256:
            raise ReceiptVerificationError("persisted receipt byte-content hash verification failed")

        return {
            "schema": VERIFICATION_SCHEMA,
            "transaction_id": receipt_dict["transaction_id"],
            "receipt_path": str(path),
            "receipt_sha256": receipt_dict["receipt_sha256"],
            "persisted_object_sha256": persisted_sha256,
            "validated_before_write": True,
            "fsynced_before_publish": True,
            "re_read_after_write": True,
            "validated_after_read": True,
            "hash_verified": True,
            "verified": True,
        }

    def read_verified(self, transaction_id: str) -> dict[str, Any]:
        path = self.receipt_path(transaction_id)
        with path.open("r", encoding="utf-8") as f:
            receipt = json.load(f)
        validate_receipt(receipt)
        return receipt


class TransactionMachine:
    """Standalone nested transaction runner with durable verified receipts."""

    def __init__(self, store_path: str | os.PathLike[str] = "./transaction-store"):
        self.store = ReceiptStore(store_path)

    def do_transaction(
        self,
        obj: Any,
        work: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        stack = _ACTIVE_STACK.get()
        parent = stack[-1] if stack else None
        active = _ActiveTransaction(
            transaction_id=f"txn_{uuid.uuid4().hex}",
            parent_transaction_id=parent.transaction_id if parent else None,
            depth=len(stack),
        )
        token = _ACTIVE_STACK.set(stack + (active,))
        started_at = _utc_now()

        status = "COMPLETE"
        result: Any = None
        error: dict[str, Any] | None = None
        caught: BaseException | None = None
        try:
            result = work() if work is not None else obj
        except BaseException as exc:
            status = "FAILED"
            caught = exc
            error = {
                "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            }
        finally:
            _ACTIVE_STACK.reset(token)

        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "transaction_id": active.transaction_id,
            "parent_transaction_id": active.parent_transaction_id,
            "depth": active.depth,
            "status": status,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "input": _json_safe(obj),
            "result": _json_safe(result),
            "error": _json_safe(error) if error is not None else None,
            "children": list(active.children),
        }
        receipt["receipt_sha256"] = _sha256(receipt)
        verification = self.store.write_and_verify(receipt)

        if parent is not None:
            parent.children.append(active.transaction_id)

        outcome = {
            "transaction_id": active.transaction_id,
            "parent_transaction_id": active.parent_transaction_id,
            "depth": active.depth,
            "status": status,
            "result": result,
            "receipt": receipt,
            "verification": verification,
        }
        if caught is not None:
            setattr(caught, "transaction_receipt", outcome)
            raise caught
        return outcome


def do_transaction(
    obj: Any,
    work: Callable[[], Any] | None = None,
    *,
    store_path: str | os.PathLike[str] = "./transaction-store",
) -> dict[str, Any]:
    """One-call convenience API. Nested calls share lineage within the current context."""
    machine = _DEFAULT_MACHINES.get(str(Path(store_path).expanduser().resolve()))
    if machine is None:
        machine = TransactionMachine(store_path)
        _DEFAULT_MACHINES[str(machine.store.root)] = machine
    return machine.do_transaction(obj, work)


_DEFAULT_MACHINES: dict[str, TransactionMachine] = {}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run one standalone durable transaction")
    parser.add_argument("object", help="JSON value used as the transaction object")
    parser.add_argument("--store", default="./transaction-store", help="persistent receipt-store directory")
    args = parser.parse_args()
    obj = json.loads(args.object)
    outcome = do_transaction(obj, store_path=args.store)
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
