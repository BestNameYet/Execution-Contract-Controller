from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


class EventRecorder:
    """Keep the complete transaction transcript in memory until close."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._sequence = 0
        self._lock = threading.Lock()

    def record(self, stream: str, direction: str, data: str) -> None:
        with self._lock:
            self._sequence += 1
            self._events.append(
                {
                    "sequence": self._sequence,
                    "timestamp": _utc_now(),
                    "stream": stream,
                    "direction": direction,
                    "data": data,
                }
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events]


def _resolve_receipt_path(
    transaction_id: str,
    *,
    receipt_file: str | os.PathLike[str] | None,
    receipt_dir: str | os.PathLike[str],
) -> Path:
    if receipt_file is not None:
        return Path(receipt_file).expanduser().resolve()
    return (
        Path(receipt_dir).expanduser().resolve()
        / f"{transaction_id}.json"
    )


def _write_receipt_once(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(receipt) + b"\n"
    with path.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _pump_input(
    caller_stdin: TextIO,
    child_stdin: TextIO,
    recorder: EventRecorder,
    closing: threading.Event,
) -> None:
    try:
        while not closing.is_set():
            data = caller_stdin.readline()
            if data == "" or closing.is_set():
                return
            recorder.record("stdin", "down", data)
            child_stdin.write(data)
            child_stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        return


def _pump_output(
    child_stream: TextIO,
    caller_stream: TextIO,
    stream_name: str,
    recorder: EventRecorder,
) -> None:
    while True:
        data = child_stream.readline()
        if data == "":
            return
        recorder.record(stream_name, "up", data)
        caller_stream.write(data)
        caller_stream.flush()


def _receipt(
    *,
    transaction_id: str,
    script: str | None,
    started_at: str,
    closed_at: str,
    child_created: bool,
    events: list[dict[str, Any]],
    receipt_path: Path,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "transaction_id": transaction_id,
        "kind": "transaction",
        "script": script,
        "started_at": started_at,
        "closed_at": closed_at,
        "child_created": child_created,
        "events": events,
        "receipt_file": str(receipt_path),
    }
    value["receipt_sha256"] = _receipt_sha256(value)
    return value


def do_transaction(
    script: str | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    receipt_file: str | os.PathLike[str] | None = None,
    receipt_dir: str | os.PathLike[str] = "./transaction-receipts",
) -> dict[str, Any]:
    """Run one neutral, recorded script transaction.

    Standard-stream traffic is forwarded without semantic interpretation and is
    accumulated only in memory while the script runs. After the child closes,
    one receipt is written to ``receipt_file`` or to a generated file in
    ``receipt_dir``.
    """
    if script is not None and not isinstance(script, str):
        raise TypeError("script must be a string or None")

    transaction_id = f"txn_{uuid.uuid4().hex}"
    started_at = _utc_now()
    receipt_path = _resolve_receipt_path(
        transaction_id,
        receipt_file=receipt_file,
        receipt_dir=receipt_dir,
    )
    recorder = EventRecorder()

    if script is None:
        receipt = _receipt(
            transaction_id=transaction_id,
            script=None,
            started_at=started_at,
            closed_at=_utc_now(),
            child_created=False,
            events=recorder.snapshot(),
            receipt_path=receipt_path,
        )
        _write_receipt_once(receipt_path, receipt)
        return receipt

    caller_stdin = sys.stdin if stdin is None else stdin
    caller_stdout = sys.stdout if stdout is None else stdout
    caller_stderr = sys.stderr if stderr is None else stderr

    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    closing = threading.Event()
    stdin_thread = threading.Thread(
        target=_pump_input,
        args=(caller_stdin, process.stdin, recorder, closing),
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=_pump_output,
        args=(process.stdout, caller_stdout, "stdout", recorder),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pump_output,
        args=(process.stderr, caller_stderr, "stderr", recorder),
        daemon=True,
    )

    stdin_thread.start()
    stdout_thread.start()
    stderr_thread.start()

    process.wait()
    closing.set()
    stdout_thread.join()
    stderr_thread.join()

    try:
        process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass

    receipt = _receipt(
        transaction_id=transaction_id,
        script=script,
        started_at=started_at,
        closed_at=_utc_now(),
        child_created=True,
        events=recorder.snapshot(),
        receipt_path=receipt_path,
    )
    _write_receipt_once(receipt_path, receipt)
    return receipt
