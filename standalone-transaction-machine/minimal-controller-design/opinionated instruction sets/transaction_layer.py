from __future__ import annotations

import json
import os
import queue
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


class TransactionStreamBridge:
    """Per-transaction intermediate between caller streams and child pipes."""

    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder
        self._input: queue.Queue[str | None] = queue.Queue()
        self._output_lock = threading.Lock()
        self._stdout_sink: TextIO | None = None
        self._stderr_sink: TextIO | None = None

    def attach_outputs(self, stdout: TextIO, stderr: TextIO) -> None:
        with self._output_lock:
            self._stdout_sink = stdout
            self._stderr_sink = stderr

    def detach_outputs(self) -> None:
        with self._output_lock:
            self._stdout_sink = None
            self._stderr_sink = None

    def route_caller_input(self, data: str) -> None:
        self._input.put(data)

    def stop_input(self) -> None:
        self._input.put(None)

    def forward_input_to_child(self, child_stdin: TextIO) -> None:
        """Forward only bridge input to child stdin; never read caller stdin directly."""
        try:
            while True:
                data = self._input.get()
                if data is None:
                    return
                self._recorder.record("stdin", "caller_to_script", data)
                child_stdin.write(data)
                child_stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return

    def forward_child_output(self, child_stream: TextIO, stream_name: str) -> None:
        """Record child output and route it to the attached caller sink, if any."""
        while True:
            data = child_stream.readline()
            if data == "":
                return

            self._recorder.record(stream_name, "script_to_caller", data)
            with self._output_lock:
                sink = self._stdout_sink if stream_name == "stdout" else self._stderr_sink
                if sink is not None:
                    sink.write(data)
                    sink.flush()


class CallerInputRouter:
    """Own one real caller stdin and route it only to the currently attached bridge."""

    def __init__(self, caller_stdin: TextIO) -> None:
        self._caller_stdin = caller_stdin
        self._lock = threading.Lock()
        self._active_bridge: TransactionStreamBridge | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def attach(self, bridge: TransactionStreamBridge) -> None:
        with self._lock:
            if self._active_bridge is not None:
                raise RuntimeError("caller stdin already has an active transaction bridge")
            self._active_bridge = bridge

    def detach(self, bridge: TransactionStreamBridge) -> None:
        with self._lock:
            if self._active_bridge is bridge:
                self._active_bridge = None

    def _run(self) -> None:
        while True:
            try:
                data = self._caller_stdin.readline()
            except (OSError, ValueError):
                return

            if data == "":
                return

            with self._lock:
                bridge = self._active_bridge
                if bridge is not None:
                    bridge.route_caller_input(data)


_ROUTER_LOCK = threading.Lock()
_CALLER_INPUT_ROUTERS: dict[int, tuple[TextIO, CallerInputRouter]] = {}


def _get_caller_input_router(caller_stdin: TextIO) -> CallerInputRouter:
    """Return the sole router allowed to read this caller stdin object."""
    key = id(caller_stdin)
    with _ROUTER_LOCK:
        existing = _CALLER_INPUT_ROUTERS.get(key)
        if existing is not None and existing[0] is caller_stdin:
            return existing[1]

        router = CallerInputRouter(caller_stdin)
        _CALLER_INPUT_ROUTERS[key] = (caller_stdin, router)
        return router


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

    bridge = TransactionStreamBridge(recorder)
    router = _get_caller_input_router(caller_stdin)
    bridge.attach_outputs(caller_stdout, caller_stderr)
    router.attach(bridge)

    stdin_thread = threading.Thread(
        target=bridge.forward_input_to_child,
        args=(process.stdin,),
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=bridge.forward_child_output,
        args=(process.stdout, "stdout"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=bridge.forward_child_output,
        args=(process.stderr, "stderr"),
        daemon=True,
    )

    stdin_thread.start()
    stdout_thread.start()
    stderr_thread.start()

    try:
        process.wait()
    finally:
        router.detach(bridge)
        bridge.detach_outputs()
        bridge.stop_input()

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
