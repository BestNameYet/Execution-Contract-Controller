#!/usr/bin/env python3
"""Generic V0 transaction runtime.

The runtime maintains three independent planes:

DATA PLANE
    outcome.result -- validated by the active transaction return schema; this is
    the only terminal transaction result exposed to the model.

CONTROL PLANE
    outcome.transition -- consumed by the higher-level mode controller and not
    included in the terminal result.

RECORD PLANE
    outcome.receipt -- complete Level-1 transaction record. If
    TRANSACTION_RECEIPT_FD is supplied, the receipt is also written there as
    one JSON line. It is never written to the model-visible stdout channel.

Dialogue transactions reference a dialogue script and declare their fixed
return_schema. Execution transactions carry the model-authored contract intact:

    {
      "execution_script": "<python source>",
      "return_schema": { ... },
      "kb_items": ["canonical.kb.id", ...]
    }

For execution, that embedded contract is authoritative. Immediately before the
script starts, any associated kb_items are resolved to their full canonical KB
records and broadcast once to the model-visible channel. This broadcast is
context injection only: it does not request or consume a model response.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

RECEIPT_FD_ENV = "TRANSACTION_RECEIPT_FD"
META_FD_ENV = "TRANSACTION_META_FD"
HERE = Path(__file__).resolve().parent
DEFAULT_EXECUTION_KB = HERE / "execution_knowledge_base.json"


class TransactionError(RuntimeError):
    pass


class DefinitionError(TransactionError):
    pass


class ResultValidationError(TransactionError):
    pass


@dataclass
class TransactionOutcome:
    result: Any
    transition: str | None
    receipt: dict[str, Any]


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ResultValidationError(f"unsupported schema type: {expected!r}")


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the JSON-Schema subset used by V0 transaction definitions."""
    if not isinstance(schema, dict):
        raise ResultValidationError(f"{path}: schema must be an object")

    if "const" in schema and value != schema["const"]:
        raise ResultValidationError(f"{path}: value does not equal const")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            raise ResultValidationError(f"{path}: value is not in enum")

    expected = schema.get("type")
    if expected is not None:
        allowed = [expected] if isinstance(expected, str) else expected
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ResultValidationError(f"{path}: schema type must be string or string array")
        if not any(_type_matches(value, item) for item in allowed):
            raise ResultValidationError(f"{path}: value has wrong type")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ResultValidationError(f"{path}: required must be an array of strings")
        for key in required:
            if key not in value:
                raise ResultValidationError(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ResultValidationError(f"{path}: properties must be an object")
        for key, child_schema in properties.items():
            if key in value:
                validate(value[key], child_schema, f"{path}.{key}")

        if schema.get("additionalProperties") is False:
            extras = [key for key in value if key not in properties]
            if extras:
                raise ResultValidationError(f"{path}: additional properties not allowed: {extras}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            raise ResultValidationError(f"{path}: fewer than minItems={min_items}")
        if isinstance(max_items, int) and len(value) > max_items:
            raise ResultValidationError(f"{path}: more than maxItems={max_items}")
        if schema.get("uniqueItems") is True:
            encoded = [compact(item) for item in value]
            if len(set(encoded)) != len(encoded):
                raise ResultValidationError(f"{path}: array items must be unique")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, dict):
                raise ResultValidationError(f"{path}: items must be a schema object")
            for index, item in enumerate(value):
                validate(item, item_schema, f"{path}[{index}]")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            raise ResultValidationError(f"{path}: shorter than minLength={min_length}")
        if isinstance(max_length, int) and len(value) > max_length:
            raise ResultValidationError(f"{path}: longer than maxLength={max_length}")


def _load_definition(value: dict[str, Any] | str | Path) -> tuple[dict[str, Any], Path]:
    if isinstance(value, Path):
        path = value.resolve()
        definition = json.loads(path.read_text(encoding="utf-8"))
        return definition, path.parent

    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith("{"):
            definition = json.loads(value)
            return definition, HERE
        path = Path(value).resolve()
        definition = json.loads(path.read_text(encoding="utf-8"))
        return definition, path.parent

    if isinstance(value, dict):
        return value, HERE

    raise DefinitionError("transaction definition must be a dict, JSON string, or path")


def _validate_execution_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise DefinitionError("execution definition requires contract object")
    if set(contract.keys()) != {"execution_script", "return_schema", "kb_items"}:
        raise DefinitionError(
            "execution contract must contain exactly execution_script, return_schema, and kb_items"
        )
    script = contract.get("execution_script")
    schema = contract.get("return_schema")
    kb_items = contract.get("kb_items")
    if not isinstance(script, str) or not script.strip():
        raise DefinitionError("execution contract requires non-empty execution_script")
    if not isinstance(schema, dict):
        raise DefinitionError("execution contract requires return_schema object")
    if not isinstance(kb_items, list) or not all(isinstance(item, str) and item for item in kb_items):
        raise DefinitionError("execution contract kb_items must be an array of non-empty canonical IDs")
    if len(set(kb_items)) != len(kb_items):
        raise DefinitionError("execution contract kb_items must be unique")
    return contract


def _validate_definition(definition: dict[str, Any]) -> None:
    if definition.get("schema") != "transaction-definition-v1":
        raise DefinitionError("schema must be transaction-definition-v1")
    kind = definition.get("kind")
    if kind not in {"dialogue", "execution"}:
        raise DefinitionError("kind must be dialogue or execution")

    if kind == "dialogue":
        if not isinstance(definition.get("script"), dict):
            raise DefinitionError("dialogue script must be an object")
        script = definition["script"]
        has_ref = isinstance(script.get("ref"), str) and bool(script["ref"].strip())
        has_source = isinstance(script.get("source"), str) and bool(script["source"].strip())
        if has_ref == has_source:
            raise DefinitionError("dialogue script must contain exactly one of ref or source")
        if not isinstance(definition.get("return_schema"), dict):
            raise DefinitionError("dialogue return_schema must be a JSON Schema object")
        return

    _validate_execution_contract(definition.get("contract"))


def _dialogue_command(definition: dict[str, Any], base_dir: Path, python_executable: str) -> list[str]:
    script = definition["script"]
    if "ref" in script:
        return [python_executable, str((base_dir / script["ref"]).resolve())]
    return [python_executable, "-c", script["source"]]


def _execution_command(definition: dict[str, Any], python_executable: str) -> list[str]:
    contract = _validate_execution_contract(definition.get("contract"))
    return [python_executable, "-c", contract["execution_script"]]


def _emit_receipt(receipt: dict[str, Any]) -> None:
    raw_fd = os.environ.get(RECEIPT_FD_ENV)
    if raw_fd is None:
        return
    try:
        os.write(int(raw_fd), (compact(receipt) + "\n").encode("utf-8"))
    except Exception:
        return


def _drain_text(stream: TextIO, sink: list[str]) -> None:
    try:
        for line in stream:
            sink.append(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _drain_metadata(fd: int, sink: list[Any]) -> None:
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            for line in stream:
                raw = line.rstrip("\n")
                try:
                    sink.append(json.loads(raw))
                except json.JSONDecodeError:
                    sink.append({"unparsed": raw})
    except Exception:
        return


def _resolve_execution_kb(definition: dict[str, Any], base_dir: Path) -> tuple[list[str], list[dict[str, Any]]]:
    contract = _validate_execution_contract(definition.get("contract"))
    ids = contract["kb_items"]
    if not ids:
        return [], []

    resources = definition.get("resources") if isinstance(definition.get("resources"), dict) else {}
    kb_ref = resources.get("execution_kb", "execution_knowledge_base.json")
    if not isinstance(kb_ref, str) or not kb_ref:
        raise DefinitionError("execution resources.execution_kb must be a file reference")
    kb_path = (base_dir / kb_ref).resolve()
    if not kb_path.exists() and kb_ref == "execution_knowledge_base.json":
        kb_path = DEFAULT_EXECUTION_KB

    try:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TransactionError(f"execution KB file not found: {kb_path}") from exc
    except json.JSONDecodeError as exc:
        raise TransactionError(f"execution KB is invalid JSON: {exc.msg}") from exc

    records = kb.get("records") if isinstance(kb, dict) else None
    if not isinstance(records, list):
        raise TransactionError("execution KB must contain a records array")
    by_id = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    missing = [item for item in ids if item not in by_id]
    if missing:
        raise TransactionError("contract references missing KB items: " + ", ".join(missing))
    return ids, [by_id[item] for item in ids]


def _broadcast_execution_context(
    definition: dict[str, Any],
    base_dir: Path,
    *,
    model_stdout: TextIO,
) -> dict[str, Any] | None:
    ids, records = _resolve_execution_kb(definition, base_dir)
    if not ids:
        return None
    broadcast = {
        "stage": "EXECUTION_CONTEXT",
        "message": "Associated KB context for the execution transaction. The script begins immediately after this broadcast; no response is requested.",
        "kb_items": ids,
        "kb_context": records,
        "requires_response": False,
    }
    model_stdout.write(compact(broadcast) + "\n")
    model_stdout.flush()
    return broadcast


def _run_dialogue(
    definition: dict[str, Any],
    base_dir: Path,
    *,
    model_stdin: TextIO,
    model_stdout: TextIO,
    python_executable: str,
) -> TransactionOutcome:
    command = _dialogue_command(definition, base_dir, python_executable)

    meta_read, meta_write = os.pipe()
    env = dict(os.environ)
    env[META_FD_ENV] = str(meta_write)

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        pass_fds=(meta_write,),
    )
    os.close(meta_write)
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    stderr_lines: list[str] = []
    metadata: list[Any] = []
    stderr_thread = threading.Thread(target=_drain_text, args=(proc.stderr, stderr_lines), daemon=True)
    metadata_thread = threading.Thread(target=_drain_metadata, args=(meta_read, metadata), daemon=True)
    stderr_thread.start()
    metadata_thread.start()

    model_messages: list[Any] = []
    model_responses: list[Any] = []

    try:
        for child_line in proc.stdout:
            raw_message = child_line.rstrip("\n")
            try:
                parsed_message = json.loads(raw_message)
            except json.JSONDecodeError as exc:
                raise TransactionError(f"dialogue stdout is not JSON: {exc.msg}") from exc
            model_messages.append(parsed_message)

            model_stdout.write(child_line)
            model_stdout.flush()

            response_line = model_stdin.readline()
            if response_line == "":
                raise TransactionError("model input closed before dialogue completed")
            try:
                parsed_response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                raise TransactionError(f"model response is not JSON: {exc.msg}") from exc
            model_responses.append(parsed_response)
            proc.stdin.write(response_line if response_line.endswith("\n") else response_line + "\n")
            proc.stdin.flush()
    except Exception:
        proc.terminate()
        raise
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    exit_code = proc.wait()
    stderr_thread.join(timeout=1)
    metadata_thread.join(timeout=1)

    if exit_code != 0:
        raise TransactionError(
            f"dialogue transaction exited non-zero ({exit_code}); stderr={''.join(stderr_lines)!r}"
        )
    if not model_responses:
        raise TransactionError("dialogue transaction completed without model responses")

    completion = model_responses[-1]
    if not isinstance(completion, dict) or set(completion.keys()) != {"result", "transition"}:
        raise TransactionError("dialogue terminal response must contain exactly result and transition")

    result = completion["result"]
    transition = completion["transition"]
    validate(result, definition["return_schema"])

    allowed = definition.get("allowed_transitions", [])
    if not isinstance(allowed, list) or transition not in allowed:
        raise TransactionError(f"transition {transition!r} is not allowed by transaction definition")

    receipt = {
        "transaction_id": definition.get("id"),
        "kind": "dialogue",
        "definition": definition,
        "model_messages": model_messages,
        "model_responses": model_responses,
        "metadata": metadata,
        "stderr": "".join(stderr_lines),
        "exit_code": exit_code,
        "result": result,
        "transition": transition,
        "return_schema_valid": True,
    }
    _emit_receipt(receipt)
    return TransactionOutcome(result=result, transition=transition, receipt=receipt)


def _run_execution(
    definition: dict[str, Any],
    base_dir: Path,
    *,
    model_stdout: TextIO,
    python_executable: str,
    timeout: float | None,
) -> TransactionOutcome:
    contract = _validate_execution_contract(definition.get("contract"))
    context_broadcast = _broadcast_execution_context(
        definition,
        base_dir,
        model_stdout=model_stdout,
    )
    command = _execution_command(definition, python_executable)

    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TransactionError(f"execution transaction exceeded timeout={timeout}") from exc

    if completed.returncode != 0:
        raise TransactionError(
            f"execution transaction exited non-zero ({completed.returncode}); stderr={completed.stderr!r}"
        )

    stdout = completed.stdout.strip()
    if not stdout:
        raise TransactionError("execution transaction produced no stdout JSON result")
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise TransactionError(
            "execution stdout must contain exactly one JSON value; "
            f"parse failed at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc

    validate(result, contract["return_schema"])
    receipt = {
        "transaction_id": definition.get("id"),
        "kind": "execution",
        "definition": definition,
        "contract": contract,
        "pre_execution_context_broadcast": context_broadcast,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
        "result": result,
        "transition": None,
        "return_schema_valid": True,
    }
    _emit_receipt(receipt)
    return TransactionOutcome(result=result, transition=None, receipt=receipt)


def transaction(
    definition_json: dict[str, Any] | str | Path,
    *,
    model_stdin: TextIO = sys.stdin,
    model_stdout: TextIO = sys.stdout,
    python_executable: str = sys.executable,
    timeout: float | None = None,
) -> TransactionOutcome:
    """Run any V0 transaction definition and return its internal outcome."""
    definition, base_dir = _load_definition(definition_json)
    _validate_definition(definition)
    if definition["kind"] == "dialogue":
        return _run_dialogue(
            definition,
            base_dir,
            model_stdin=model_stdin,
            model_stdout=model_stdout,
            python_executable=python_executable,
        )
    return _run_execution(
        definition,
        base_dir,
        model_stdout=model_stdout,
        python_executable=python_executable,
        timeout=timeout,
    )


def execution_definition(contract: dict[str, Any]) -> dict[str, Any]:
    """Convert a CREATE result into an execution transaction definition.

    The original model-authored contract is retained intact and remains the
    authority for the execution script, its model-facing return schema, and all
    KB items associated with execution.
    """
    contract = _validate_execution_contract(contract)
    return {
        "schema": "transaction-definition-v1",
        "id": "execute",
        "title": "Execute model-authored contract",
        "kind": "execution",
        "contract": contract,
        "resources": {
            "execution_kb": "execution_knowledge_base.json"
        },
        "completion": {"source": "contract_execution_script_stdout_json"},
        "pre_execution": {
            "broadcast_contract_kb_items": True,
            "requires_model_response": False,
        },
        "allowed_transitions": [],
    }


def initial_transaction() -> Path:
    """CREATE is automatic; no prior transition is required."""
    return HERE / "create_dialogue.json"


if __name__ == "__main__":
    definition_arg = sys.argv[1] if len(sys.argv) > 1 else str(initial_transaction())
    outcome = transaction(definition_arg)
    sys.stdout.write(compact(outcome.result) + "\n")
    sys.stdout.flush()
