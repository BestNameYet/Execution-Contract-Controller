#!/usr/bin/env python3
"""Level-1 execution transaction runtime.

The builder dialogue produces a minimal contract:

    {
      "execution_script": "<python source>",
      "return_schema": { ... JSON Schema subset ... }
    }

This module consumes that contract, executes the model-authored Python in a
fresh child process, captures stdout/stderr/exit status, parses stdout as one
JSON value, validates that value against return_schema, and returns either the
contract result or the full Level-1 transaction record.

The execution script contract is intentionally simple:
- stdout is reserved for exactly one terminal JSON value.
- stderr is available for diagnostics.
- a non-zero process exit is execution failure.
- successful stdout must satisfy return_schema.

No inspection or virtualization of internal Python state is performed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


class ContractError(ValueError):
    pass


class ExecutionError(RuntimeError):
    pass


class ReturnValidationError(ValueError):
    pass


def _load_contract(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError(f"contract is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ContractError("contract must be a JSON object")

    script = value.get("execution_script")
    schema = value.get("return_schema")

    if not isinstance(script, str) or not script.strip():
        raise ContractError("execution_script must be a non-empty string")
    if not isinstance(schema, dict):
        raise ContractError("return_schema must be a JSON object")

    return value


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
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ReturnValidationError(f"unsupported schema type: {expected!r}")


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the small JSON-Schema subset needed by V0 contracts.

    Supported keywords:
      type, required, properties, additionalProperties,
      items, minItems, maxItems, uniqueItems,
      minLength, maxLength, enum, const, anyOf, oneOf.
    """

    if "const" in schema and value != schema["const"]:
        raise ReturnValidationError(f"{path}: value does not equal const")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list):
            raise ReturnValidationError(f"{path}: schema enum must be an array")
        if value not in enum:
            raise ReturnValidationError(f"{path}: value is not in enum")

    if "anyOf" in schema:
        options = schema["anyOf"]
        if not isinstance(options, list) or not options:
            raise ReturnValidationError(f"{path}: anyOf must be a non-empty array")
        errors = []
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                _validate(value, option, path)
                break
            except ReturnValidationError as exc:
                errors.append(str(exc))
        else:
            raise ReturnValidationError(f"{path}: value satisfies no anyOf branch")

    if "oneOf" in schema:
        options = schema["oneOf"]
        if not isinstance(options, list) or not options:
            raise ReturnValidationError(f"{path}: oneOf must be a non-empty array")
        matches = 0
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                _validate(value, option, path)
                matches += 1
            except ReturnValidationError:
                pass
        if matches != 1:
            raise ReturnValidationError(f"{path}: value must satisfy exactly one oneOf branch")

    expected = schema.get("type")
    if expected is not None:
        if isinstance(expected, str):
            allowed_types = [expected]
        elif isinstance(expected, list) and all(isinstance(x, str) for x in expected):
            allowed_types = expected
        else:
            raise ReturnValidationError(f"{path}: schema type must be a string or string array")
        if not any(_type_matches(value, item) for item in allowed_types):
            raise ReturnValidationError(
                f"{path}: expected type {'|'.join(allowed_types)}, got {type(value).__name__}"
            )

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
            raise ReturnValidationError(f"{path}: required must be an array of strings")
        for key in required:
            if key not in value:
                raise ReturnValidationError(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ReturnValidationError(f"{path}: properties must be an object")
        for key, child_schema in properties.items():
            if key in value:
                if not isinstance(child_schema, dict):
                    raise ReturnValidationError(f"{path}.{key}: property schema must be an object")
                _validate(value[key], child_schema, f"{path}.{key}")

        if schema.get("additionalProperties") is False:
            extras = [key for key in value if key not in properties]
            if extras:
                raise ReturnValidationError(
                    f"{path}: additional properties not allowed: {', '.join(sorted(extras))}"
                )

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            raise ReturnValidationError(f"{path}: fewer than minItems={min_items}")
        if isinstance(max_items, int) and len(value) > max_items:
            raise ReturnValidationError(f"{path}: more than maxItems={max_items}")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(set(encoded)) != len(encoded):
                raise ReturnValidationError(f"{path}: array items must be unique")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, dict):
                raise ReturnValidationError(f"{path}: items must be a schema object")
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            raise ReturnValidationError(f"{path}: shorter than minLength={min_length}")
        if isinstance(max_length, int) and len(value) > max_length:
            raise ReturnValidationError(f"{path}: longer than maxLength={max_length}")


def validate_return(value: Any, schema: dict[str, Any]) -> None:
    _validate(value, schema)


def execute_contract_record(
    contract_json: dict[str, Any] | str,
    *,
    timeout: float | None = None,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    """Execute a minimal model-authored contract and return its Level-1 record."""

    contract = _load_contract(contract_json)
    script = contract["execution_script"]
    return_schema = contract["return_schema"]

    try:
        completed = subprocess.run(
            [python_executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExecutionError(f"execution script exceeded timeout={timeout}") from exc

    record: dict[str, Any] = {
        "contract": contract,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "result": None,
        "return_schema_valid": False,
    }

    if completed.returncode != 0:
        raise ExecutionError(
            "execution script exited non-zero "
            f"({completed.returncode}); stderr={completed.stderr!r}"
        )

    stdout = completed.stdout.strip()
    if not stdout:
        raise ExecutionError("execution script produced no stdout JSON result")

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExecutionError(
            "execution script stdout must contain exactly one JSON value; "
            f"parse failed at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc

    validate_return(result, return_schema)

    record["result"] = result
    record["return_schema_valid"] = True
    return record


def execute_contract(
    contract_json: dict[str, Any] | str,
    *,
    timeout: float | None = None,
    python_executable: str = sys.executable,
) -> Any:
    """Execute a contract and return only its validated terminal JSON value."""

    return execute_contract_record(
        contract_json,
        timeout=timeout,
        python_executable=python_executable,
    )["result"]


# Short alias when this module is used as the execution transaction primitive.
transaction = execute_contract_record


if __name__ == "__main__":
    raw = sys.stdin.read()
    try:
        record = execute_contract_record(raw)
    except (ContractError, ExecutionError, ReturnValidationError) as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(2)
    sys.stdout.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
