from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RECEIPT_FIELDS = {
    "transaction_id",
    "kind",
    "definition",
    "contract",
    "pre_execution_context_broadcast",
    "stdout",
    "stderr",
    "exit_code",
    "result",
    "transition",
    "return_schema_valid",
    "persisted_receipt_path",
    "model_messages",
    "model_responses",
    "metadata",
    "receipt_sha256",
}


class ChildExecutionError(RuntimeError):
    """Raised when the child execution environment fails."""


class ChildOutcomeValidationError(ValueError):
    """Raised when the child does not return a valid JSON outcome object."""


class ReceiptValidationError(ValueError):
    """Raised when a transaction receipt is structurally or cryptographically invalid."""


class ReceiptVerificationError(RuntimeError):
    """Raised when a saved receipt cannot be verified against the in-memory receipt."""


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


def _receipt_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def _receipt_sha256(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(_receipt_payload(receipt))).hexdigest()


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, Mapping):
        raise ReceiptValidationError("receipt must be an object")

    keys = set(receipt.keys())
    if keys != RECEIPT_FIELDS:
        missing = sorted(RECEIPT_FIELDS - keys)
        extra = sorted(keys - RECEIPT_FIELDS)
        raise ReceiptValidationError(
            f"receipt fields do not match required envelope; missing={missing}, extra={extra}"
        )

    if not isinstance(receipt["transaction_id"], str) or not receipt["transaction_id"]:
        raise ReceiptValidationError("transaction_id must be a non-empty string")
    if not isinstance(receipt["kind"], str) or not receipt["kind"]:
        raise ReceiptValidationError("kind must be a non-empty string")
    if not isinstance(receipt["definition"], dict):
        raise ReceiptValidationError("definition must be an object")
    if not isinstance(receipt["stdout"], str):
        raise ReceiptValidationError("stdout must be a string")
    if not isinstance(receipt["stderr"], str):
        raise ReceiptValidationError("stderr must be a string")
    if receipt["exit_code"] is not None and (
        not isinstance(receipt["exit_code"], int) or isinstance(receipt["exit_code"], bool)
    ):
        raise ReceiptValidationError("exit_code must be an integer or null")
    if not isinstance(receipt["persisted_receipt_path"], str) or not receipt["persisted_receipt_path"]:
        raise ReceiptValidationError("persisted_receipt_path must be a non-empty string")
    if not isinstance(receipt["model_messages"], list):
        raise ReceiptValidationError("model_messages must be an array")
    if not isinstance(receipt["model_responses"], list):
        raise ReceiptValidationError("model_responses must be an array")
    if not isinstance(receipt["metadata"], dict):
        raise ReceiptValidationError("metadata must be an object")

    actual = receipt["receipt_sha256"]
    expected = _receipt_sha256(receipt)
    if not isinstance(actual, str) or actual != expected:
        raise ReceiptValidationError("receipt_sha256 does not match receipt contents")

    try:
        _canonical_bytes(dict(receipt))
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError("receipt must be JSON-compatible") from exc


def validate_saved_receipt(path: str | os.PathLike[str]) -> dict[str, Any]:
    receipt_path = Path(path)
    try:
        persisted_bytes = receipt_path.read_bytes()
        persisted = json.loads(persisted_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError(f"saved receipt is unreadable or invalid JSON: {receipt_path}") from exc

    validate_receipt(persisted)
    expected_bytes = _canonical_bytes(persisted) + b"\n"
    if persisted_bytes != expected_bytes:
        raise ReceiptVerificationError("saved receipt bytes are not canonical")
    if persisted["persisted_receipt_path"] != str(receipt_path.resolve()):
        raise ReceiptVerificationError("persisted_receipt_path does not identify the saved receipt")
    return persisted


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


def _save_and_verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    validate_receipt(receipt)
    receipt_path = Path(receipt["persisted_receipt_path"])
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(receipt) + b"\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{receipt['transaction_id']}.",
        suffix=".tmp",
        dir=receipt_path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, receipt_path)
        _fsync_directory(receipt_path.parent)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    persisted = validate_saved_receipt(receipt_path)
    if persisted != receipt:
        raise ReceiptVerificationError("saved receipt differs from validated in-memory receipt")
    return persisted


def _validate_script(script: Any) -> str:
    if not isinstance(script, str):
        raise TypeError("script must be a string")
    if not script.strip():
        raise ValueError("script must be a non-empty string")
    return script


def _run_child(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _build_receipt(
    *,
    transaction_id: str,
    script: str,
    receipt_path: Path,
    started_at: str,
    completed_at: str,
    completed: subprocess.CompletedProcess[str],
    outcome: dict[str, Any] | None,
    status: str,
    error: dict[str, str] | None,
    parent_transaction_id: str | None,
    depth: int,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "transaction_id": transaction_id,
        "kind": "transaction",
        "definition": {"script": script},
        "contract": None,
        "pre_execution_context_broadcast": None,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
        "result": outcome,
        "transition": None,
        "return_schema_valid": None,
        "persisted_receipt_path": str(receipt_path.resolve()),
        "model_messages": [],
        "model_responses": [],
        "metadata": {
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "parent_transaction_id": parent_transaction_id,
            "depth": depth,
            "error": error,
        },
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    return receipt


def _do_transaction(
    script: str,
    *,
    receipt_dir: Path,
    parent_transaction_id: str | None,
    depth: int,
) -> dict[str, Any]:
    current_script = _validate_script(script)
    transaction_id = f"txn_{uuid.uuid4().hex}"
    receipt_path = receipt_dir / f"{transaction_id}.json"
    started_at = _utc_now()
    completed = _run_child(current_script)

    outcome: dict[str, Any] | None = None
    status = "COMPLETE"
    error: dict[str, str] | None = None
    failure: BaseException | None = None

    if completed.returncode != 0:
        status = "FAILED"
        failure = ChildExecutionError(
            f"child exited with code {completed.returncode}: {completed.stderr.rstrip()}"
        )
        error = {"type": type(failure).__name__, "message": str(failure)}
    else:
        try:
            parsed = json.loads(completed.stdout)
            if not isinstance(parsed, dict):
                raise ChildOutcomeValidationError("child outcome must be a JSON object")
            outcome = parsed
            if "script" in outcome:
                _validate_script(outcome["script"])
        except (json.JSONDecodeError, ChildOutcomeValidationError, TypeError, ValueError) as exc:
            status = "FAILED"
            if isinstance(exc, json.JSONDecodeError):
                failure = ChildOutcomeValidationError("child stdout must be exactly one JSON object")
            else:
                failure = exc
            error = {"type": type(failure).__name__, "message": str(failure)}

    receipt = _build_receipt(
        transaction_id=transaction_id,
        script=current_script,
        receipt_path=receipt_path,
        started_at=started_at,
        completed_at=_utc_now(),
        completed=completed,
        outcome=outcome,
        status=status,
        error=error,
        parent_transaction_id=parent_transaction_id,
        depth=depth,
    )
    _save_and_verify_receipt(receipt)

    if failure is not None:
        setattr(failure, "receipt_path", str(receipt_path.resolve()))
        raise failure

    assert outcome is not None
    if "script" not in outcome:
        do_transaction(receipt_dir=receipt_dir)
        return outcome

    return _do_transaction(
        outcome["script"],
        receipt_dir=receipt_dir,
        parent_transaction_id=transaction_id,
        depth=depth + 1,
    )


def do_transaction(
    script: str | None = None,
    *,
    receipt_dir: str | os.PathLike[str] = "./transaction-receipts",
) -> dict[str, Any] | None:
    """Execute the script chain; an empty invocation halts the machine."""
    if script is None:
        return None
    return _do_transaction(
        script,
        receipt_dir=Path(receipt_dir).expanduser().resolve(),
        parent_transaction_id=None,
        depth=0,
    )
