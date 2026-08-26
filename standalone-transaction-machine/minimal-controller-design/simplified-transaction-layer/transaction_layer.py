from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EventRecorder:
    """Keep the ordered transaction stream transcript in memory until close."""

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


def resolve_receipt_path(
    transaction_id: str,
    *,
    receipt_file: str | os.PathLike[str] | None,
    receipt_dir: str | os.PathLike[str],
) -> Path:
    if receipt_file is not None:
        return Path(receipt_file).expanduser().resolve()
    return Path(receipt_dir).expanduser().resolve() / f"{transaction_id}.json"


def create_runner(script: str) -> subprocess.Popen[str]:
    """Instantiate the default runner configuration for one supplied script."""
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _readline_cancellable(
    caller_stdin: TextIO,
    closing: threading.Event,
    *,
    poll_seconds: float = 0.05,
) -> str | None:
    """Read one caller-stdin line while remaining cancellable by transaction close."""
    try:
        fd = caller_stdin.fileno()
    except (AttributeError, OSError, ValueError):
        if closing.is_set():
            return None
        return caller_stdin.readline()

    while not closing.is_set():
        readable, _, _ = select.select([fd], [], [], poll_seconds)
        if readable:
            return caller_stdin.readline()
    return None


def record_and_forward_input(
    caller_stdin: TextIO,
    child_stdin: TextIO,
    recorder: EventRecorder,
    closing: threading.Event,
) -> None:
    """Map transaction-caller stdin to script stdin while recording each event."""
    try:
        while not closing.is_set():
            data = _readline_cancellable(caller_stdin, closing)
            if data is None or data == "" or closing.is_set():
                return
            recorder.record("stdin", "caller_to_script", data)
            child_stdin.write(data)
            child_stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        return


def record_and_forward_output(
    child_stream: TextIO,
    caller_stream: TextIO,
    stream_name: str,
    recorder: EventRecorder,
) -> None:
    """Map script stdout/stderr to the transaction caller while recording it."""
    while True:
        data = child_stream.readline()
        if data == "":
            return
        recorder.record(stream_name, "script_to_caller", data)
        caller_stream.write(data)
        caller_stream.flush()


def build_receipt(
    *,
    transaction_id: str,
    script: str | None,
    started_at: str,
    closed_at: str,
    child_created: bool,
    events: list[dict[str, Any]],
    receipt_path: Path,
) -> dict[str, Any]:
    """Build the concise in-memory receipt for one completed transaction."""
    return {
        "transaction_id": transaction_id,
        "script": script,
        "started_at": started_at,
        "closed_at": closed_at,
        "child_created": child_created,
        "events": events,
        "receipt_file": str(receipt_path),
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Persist the completed in-memory receipt exactly once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    with path.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def verify_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Require a persisted receipt to exist and equal the in-memory receipt."""
    if not path.is_file():
        raise RuntimeError(f"receipt was not written: {path}")

    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"receipt could not be read back: {path}") from exc

    if persisted != receipt:
        raise RuntimeError("persisted receipt does not match in-memory receipt")


def _join_stream_worker(thread: threading.Thread, name: str) -> None:
    """Require a transaction-owned stream worker to be gone before return."""
    thread.join(timeout=1.0)
    if thread.is_alive():
        raise RuntimeError(f"transaction {name} worker did not terminate")


def do_transaction(
    script: str | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    receipt_file: str | os.PathLike[str] | None = None,
    receipt_dir: str | os.PathLike[str] = "./transaction-receipts",
) -> dict[str, Any]:
    """Run one finite script transaction and leave a verified local receipt."""
    if script is not None and not isinstance(script, str):
        raise TypeError("script must be a string or None")

    transaction_id = f"txn_{uuid.uuid4().hex}"
    started_at = _utc_now()
    receipt_path = resolve_receipt_path(
        transaction_id,
        receipt_file=receipt_file,
        receipt_dir=receipt_dir,
    )
    recorder = EventRecorder()

    if script is None:
        receipt = build_receipt(
            transaction_id=transaction_id,
            script=None,
            started_at=started_at,
            closed_at=_utc_now(),
            child_created=False,
            events=recorder.snapshot(),
            receipt_path=receipt_path,
        )
        write_receipt(receipt_path, receipt)
        verify_receipt(receipt_path, receipt)
        return receipt

    caller_stdin = sys.stdin if stdin is None else stdin
    caller_stdout = sys.stdout if stdout is None else stdout
    caller_stderr = sys.stderr if stderr is None else stderr

    process = create_runner(script)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    closing = threading.Event()
    stdin_thread = threading.Thread(
        target=record_and_forward_input,
        args=(caller_stdin, process.stdin, recorder, closing),
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=record_and_forward_output,
        args=(process.stdout, caller_stdout, "stdout", recorder),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=record_and_forward_output,
        args=(process.stderr, caller_stderr, "stderr", recorder),
        daemon=True,
    )

    stdin_thread.start()
    stdout_thread.start()
    stderr_thread.start()

    process.wait()
    closing.set()

    try:
        process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass

    _join_stream_worker(stdin_thread, "stdin")
    _join_stream_worker(stdout_thread, "stdout")
    _join_stream_worker(stderr_thread, "stderr")

    receipt = build_receipt(
        transaction_id=transaction_id,
        script=script,
        started_at=started_at,
        closed_at=_utc_now(),
        child_created=True,
        events=recorder.snapshot(),
        receipt_path=receipt_path,
    )
    write_receipt(receipt_path, receipt)
    verify_receipt(receipt_path, receipt)
    return receipt
