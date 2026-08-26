from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from transaction_layer import do_transaction


INVOCATIONS_PER_STREAM = 10


def build_child_script(count: int = INVOCATIONS_PER_STREAM) -> str:
    return f'''import sys
for i in range({count}):
    incoming = sys.stdin.readline()
    if incoming == "":
        raise RuntimeError(f"stdin closed before iteration {{i}}")
    sys.stdout.write(f"stdout-{{i}}:{{incoming.strip()}}\\n")
    sys.stdout.flush()
    sys.stderr.write(f"stderr-{{i}}:{{incoming.strip()}}\\n")
    sys.stderr.flush()
'''


def run_test() -> dict:
    caller_stdin = io.StringIO(
        "".join(f"stdin-{i}\\n" for i in range(INVOCATIONS_PER_STREAM))
    )
    caller_stdout = io.StringIO()
    caller_stderr = io.StringIO()

    with tempfile.TemporaryDirectory(prefix="transaction-stream-test-") as tmpdir:
        receipt_path = Path(tmpdir) / "receipt.json"
        receipt = do_transaction(
            build_child_script(),
            stdin=caller_stdin,
            stdout=caller_stdout,
            stderr=caller_stderr,
            receipt_file=receipt_path,
        )

        persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert persisted == receipt

        events = receipt["events"]
        stdin_events = [event for event in events if event["stream"] == "stdin"]
        stdout_events = [event for event in events if event["stream"] == "stdout"]
        stderr_events = [event for event in events if event["stream"] == "stderr"]

        assert len(stdin_events) == INVOCATIONS_PER_STREAM
        assert len(stdout_events) == INVOCATIONS_PER_STREAM
        assert len(stderr_events) == INVOCATIONS_PER_STREAM
        assert len(events) == INVOCATIONS_PER_STREAM * 3
        assert [event["sequence"] for event in events] == list(
            range(1, len(events) + 1)
        )

        expected_stdout = "".join(
            f"stdout-{i}:stdin-{i}\\n" for i in range(INVOCATIONS_PER_STREAM)
        )
        expected_stderr = "".join(
            f"stderr-{i}:stdin-{i}\\n" for i in range(INVOCATIONS_PER_STREAM)
        )
        assert caller_stdout.getvalue() == expected_stdout
        assert caller_stderr.getvalue() == expected_stderr

        return {
            "passed": True,
            "stdin_events": len(stdin_events),
            "stdout_events": len(stdout_events),
            "stderr_events": len(stderr_events),
            "total_events": len(events),
            "receipt_verified": persisted == receipt,
        }


if __name__ == "__main__":
    print(json.dumps(run_test(), sort_keys=True))
