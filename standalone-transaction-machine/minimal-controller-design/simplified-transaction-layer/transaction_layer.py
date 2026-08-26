from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


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


def _receipt_sha256(receipt: dict[str, Any]) -> str:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _persist_receipt(receipt: dict[str, Any], receipt_path: Path) -> None:
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
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _make_recorder() -> tuple[list[dict[str, Any]], threading.Lock, list[int]]:
    return [], threading.Lock(), [0]


def _record(
    transcript: list[dict[str, Any]],
    lock: threading.Lock,
    sequence: list[int],
    *,
    stream: str,
    direction: str,
    data: str,
) -> None:
    with lock:
        sequence[0] += 1
        transcript.append(
            {
                "sequence": sequence[0],
                "timestamp": _utc_now(),
                "stream": stream,
                "direction": direction,
                "data": data,
            }
        )


def _pump_stdin(
    caller_stdin: TextIO,
    child_stdin: TextIO,
    transcript: list[dict[str, Any]],
    lock: threading.Lock,
    sequence: list[int],
) -> None:
    try:
        while True:
            data = caller_stdin.readline()
            if data == "":
                break
            _record(
                transcript,
                lock,
                sequence,
                stream="stdin",
                direction="down",
                data=data,
            )
            child_stdin.write(data)
            child_stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            child_stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def _pump_output(
    child_stream: TextIO,
    caller_stream: TextIO,
    stream_name: str,
    transcript: list[dict[str, Any]],
    lock: threading.Lock,
    sequence: list[int],
) -> None:
    while True:
        data = child_stream.readline()
        if data == "":
            break
        _record(
            transcript,
            lock,
            sequence,
            stream=stream_name,
            direction="up",
            data=data,
        )
        caller_stream.write(data)
        caller_stream.flush()


def _last_stdout(transcript: list[dict[str, Any]]) -> str | None:
    for event in reversed(transcript):
        if event["stream"] == "stdout":
            return event["data"]
    return None


def _json_result(result_text: str | None) -> tuple[bool, Any]:
    if result_text is None:
        return False, None
    try:
        return True, json.loads(result_text)
    except json.JSONDecodeError:
        return False, None


def _write_receipt(
    *,
    receipt_dir: Path,
    transaction_id: str,
    script: str | None,
    started_at: str,
    completed_at: str,
    child_started: bool,
    exit_code: int | None,
    transcript: list[dict[str, Any]],
    result_text: str | None,
    result: Any,
    json_valid: bool | None,
    parent_transaction_id: str | None,
    depth: int,
    error: dict[str, str] | None,
) -> dict[str, Any]:
    receipt_path = receipt_dir / f"{transaction_id}.json"
    receipt: dict[str, Any] = {
        "transaction_id": transaction_id,
        "kind": "transaction",
        "script": script,
        "child_started": child_started,
        "started_at": started_at,
        "completed_at": completed_at,
        "exit_code": exit_code,
        "transcript": transcript,
        "result_text": result_text,
        "result": result,
        "json_valid": json_valid,
        "parent_transaction_id": parent_transaction_id,
        "depth": depth,
        "error": error,
        "persisted_receipt_path": str(receipt_path.resolve()),
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    _persist_receipt(receipt, receipt_path)
    return receipt


def _run_script(
    script: str,
    *,
    caller_stdin: TextIO,
    caller_stdout: TextIO,
    caller_stderr: TextIO,
    receipt_dir: Path,
    parent_transaction_id: str | None,
    depth: int,
) -> tuple[dict[str, Any], Any, bool]:
    transaction_id = f"txn_{uuid.uuid4().hex}"
    started_at = _utc_now()
    transcript, lock, sequence = _make_recorder()

    try:
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        receipt = _write_receipt(
            receipt_dir=receipt_dir,
            transaction_id=transaction_id,
            script=script,
            started_at=started_at,
            completed_at=_utc_now(),
            child_started=False,
            exit_code=None,
            transcript=transcript,
            result_text=None,
            result=None,
            json_valid=False,
            parent_transaction_id=parent_transaction_id,
            depth=depth,
            error=error,
        )
        raise

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdin_thread = threading.Thread(
        target=_pump_stdin,
        args=(caller_stdin, process.stdin, transcript, lock, sequence),
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=_pump_output,
        args=(process.stdout, caller_stdout, "stdout", transcript, lock, sequence),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pump_output,
        args=(process.stderr, caller_stderr, "stderr", transcript, lock, sequence),
        daemon=True,
    )

    stdin_thread.start()
    stdout_thread.start()
    stderr_thread.start()

    exit_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    result_text = _last_stdout(transcript)
    json_valid, result = _json_result(result_text)
    error = None
    if exit_code != 0:
        error = {
            "type": "ChildProcessExit",
            "message": f"child exited with code {exit_code}",
        }

    receipt = _write_receipt(
        receipt_dir=receipt_dir,
        transaction_id=transaction_id,
        script=script,
        started_at=started_at,
        completed_at=_utc_now(),
        child_started=True,
        exit_code=exit_code,
        transcript=transcript,
        result_text=result_text,
        result=result,
        json_valid=json_valid,
        parent_transaction_id=parent_transaction_id,
        depth=depth,
        error=error,
    )
    return receipt, result, json_valid


def _record_no_script(
    *,
    receipt_dir: Path,
    parent_transaction_id: str | None,
    depth: int,
) -> dict[str, Any]:
    transaction_id = f"txn_{uuid.uuid4().hex}"
    now = _utc_now()
    return _write_receipt(
        receipt_dir=receipt_dir,
        transaction_id=transaction_id,
        script=None,
        started_at=now,
        completed_at=now,
        child_started=False,
        exit_code=None,
        transcript=[],
        result_text=None,
        result=None,
        json_valid=None,
        parent_transaction_id=parent_transaction_id,
        depth=depth,
        error=None,
    )


def do_transaction(
    script: str | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    receipt_dir: str | os.PathLike[str] = "./transaction-receipts",
    _parent_transaction_id: str | None = None,
    _depth: int = 0,
) -> Any:
    """Run one script transaction and follow the explicit JSON ``script`` continuation contract."""
    receipt_root = Path(receipt_dir).expanduser().resolve()

    if script is None:
        _record_no_script(
            receipt_dir=receipt_root,
            parent_transaction_id=_parent_transaction_id,
            depth=_depth,
        )
        return None
    if not isinstance(script, str):
        raise TypeError("script must be a string or None")

    caller_stdin = sys.stdin if stdin is None else stdin
    caller_stdout = sys.stdout if stdout is None else stdout
    caller_stderr = sys.stderr if stderr is None else stderr

    receipt, result, json_valid = _run_script(
        script,
        caller_stdin=caller_stdin,
        caller_stdout=caller_stdout,
        caller_stderr=caller_stderr,
        receipt_dir=receipt_root,
        parent_transaction_id=_parent_transaction_id,
        depth=_depth,
    )

    transaction_id = receipt["transaction_id"]

    if not json_valid:
        do_transaction(
            None,
            stdin=caller_stdin,
            stdout=caller_stdout,
            stderr=caller_stderr,
            receipt_dir=receipt_root,
            _parent_transaction_id=transaction_id,
            _depth=_depth + 1,
        )
        return None

    if isinstance(result, dict) and "script" in result:
        return do_transaction(
            result["script"],
            stdin=caller_stdin,
            stdout=caller_stdout,
            stderr=caller_stderr,
            receipt_dir=receipt_root,
            _parent_transaction_id=transaction_id,
            _depth=_depth + 1,
        )

    return result
