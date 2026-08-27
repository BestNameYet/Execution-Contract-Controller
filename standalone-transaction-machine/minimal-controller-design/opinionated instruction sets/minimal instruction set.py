from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, TextIO


HERE = Path(__file__).resolve().parent
INITIAL_PATH = HERE / "initial.py"
TRANSACTION_LAYER_PATH = HERE / "transaction_layer.py"
POST_EXECUTION_PATH = HERE / "post_execution.py"
INTERROGATION_RECEIPT_DIR = HERE / "interrogation-receipts"
EXECUTION_RECEIPT_DIR = HERE / "execution-receipts"
POST_EXECUTION_RECEIPT_DIR = HERE / "post-execution-receipts"
SOCKET_PATH = Path("/tmp/opinionated-instruction-set.sock")


def _load_transaction_layer():
    spec = importlib.util.spec_from_file_location(
        "simplified_transaction_layer",
        TRANSACTION_LAYER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load transaction layer: {TRANSACTION_LAYER_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Materialize the runtime into this process exactly once. These objects remain
# resident for the lifetime of the controller process and are reused for every
# later socket reconnection.
TRANSACTION_LAYER = _load_transaction_layer()
DO_TRANSACTION = TRANSACTION_LAYER.do_transaction
INITIAL_SCRIPT = INITIAL_PATH.read_text(encoding="utf-8")
POST_EXECUTION_SCRIPT = POST_EXECUTION_PATH.read_text(encoding="utf-8")


def read_receipt(receipt_path: Path) -> dict[str, Any]:
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("transaction receipt must be a JSON object")
    return value


def resolve_purpose_receipt_path(directory: Path, filename: str) -> Path:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename
    except OSError:
        return HERE / filename


def extract_generated_script(receipt: dict[str, Any]) -> str:
    """Mechanically return the final valid stdin JSON object's script field."""
    events = receipt.get("events")
    if not isinstance(events, list):
        raise TypeError("transaction receipt events must be a list")

    for event in reversed(events):
        if not isinstance(event, dict) or event.get("stream") != "stdin":
            continue
        try:
            value = json.loads(event["data"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if set(value.keys()) == {"script"} and isinstance(value["script"], str):
            return value["script"]

    raise RuntimeError("generated script was not found in interrogation receipt")


def extract_interrogation_context(receipt: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    events = receipt.get("events")
    if not isinstance(events, list):
        raise TypeError("transaction receipt events must be a list")

    desired_state: str | None = None
    qa1: list[dict[str, str]] = []
    pending_question: str | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            value = json.loads(event["data"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if event.get("stream") == "stdin":
            if set(value.keys()) == {"desired_state"} and isinstance(value["desired_state"], str):
                desired_state = value["desired_state"]
            elif set(value.keys()) == {"answer"} and isinstance(value["answer"], str) and pending_question is not None:
                qa1.append({"question": pending_question, "answer": value["answer"]})
                pending_question = None
        elif event.get("stream") == "stdout" and isinstance(value.get("return_schema"), dict):
            if value["return_schema"] == {"answer": "<answer>"} and isinstance(value.get("instruction"), str):
                pending_question = value["instruction"]

    if desired_state is None:
        raise RuntimeError("desired state was not found in interrogation receipt")
    return desired_state, qa1


def build_post_execution_script(context: dict[str, Any]) -> str:
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "import json\n"
        f"POST_EXECUTION_CONTEXT = json.loads({context_json!r})\n"
        + POST_EXECUTION_SCRIPT
    )


def run_transaction(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    run_id = uuid.uuid4().hex

    interrogation_receipt_path = resolve_purpose_receipt_path(
        INTERROGATION_RECEIPT_DIR,
        f"interrogation_{run_id}.json",
    )
    execution_receipt_path = resolve_purpose_receipt_path(
        EXECUTION_RECEIPT_DIR,
        f"execution_{run_id}.json",
    )
    post_execution_receipt_path = resolve_purpose_receipt_path(
        POST_EXECUTION_RECEIPT_DIR,
        f"post_execution_{run_id}.json",
    )

    DO_TRANSACTION(
        INITIAL_SCRIPT,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        receipt_file=interrogation_receipt_path,
    )

    interrogation_receipt = read_receipt(interrogation_receipt_path)
    generated_script = extract_generated_script(interrogation_receipt)
    desired_state, qa1 = extract_interrogation_context(interrogation_receipt)

    DO_TRANSACTION(
        generated_script,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        receipt_file=execution_receipt_path,
    )
    execution_receipt = read_receipt(execution_receipt_path)
    post_execution_script = build_post_execution_script(
        {
            "desired_state": desired_state,
            "qa1": qa1,
            "execution_script": generated_script,
            "execution_receipt": execution_receipt,
        }
    )
    DO_TRANSACTION(
        post_execution_script,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        receipt_file=post_execution_receipt_path,
    )
    TRANSACTION_LAYER.retire_caller_input_router(stdin)


def serve() -> None:
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)
        server.listen(1)

        # The controller process remains alive indefinitely. Connections may
        # disappear and later models may reconnect without recreating this
        # process or rematerializing its runtime dependencies.
        while True:
            connection, _ = server.accept()
            try:
                reader = connection.makefile("r", encoding="utf-8", newline="\n")
                writer = connection.makefile("w", encoding="utf-8", newline="\n")
                try:
                    run_transaction(
                        stdin=reader,
                        stdout=writer,
                        stderr=sys.stderr,
                    )
                finally:
                    writer.flush()
                    writer.close()
                    reader.close()
            except Exception as exc:
                try:
                    connection.sendall(
                        (
                            json.dumps(
                                {
                                    "error": str(exc),
                                    "error_type": type(exc).__name__,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
                except OSError:
                    pass
            finally:
                connection.close()
    finally:
        server.close()
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    serve()
