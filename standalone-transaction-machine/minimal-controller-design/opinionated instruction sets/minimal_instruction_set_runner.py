from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "runtime-manifest.json"
MANIFEST_SCHEMA = "minimal-instruction-set-runtime-manifest-v1"
CONTROLLER_ID = "minimal-instruction-set"
CANONICAL_AUTHORITY = "/Control_Authorities/CONTROL_REGISTRY.md"
DEPENDENCY_ROLES = ("initial", "post_execution", "transaction_layer")


def fail_preflight(
    error: str,
    *,
    detail: str | None = None,
    missing_files: list[str] | None = None,
) -> NoReturn:
    message: dict[str, Any] = {
        "type": "RUNNER_PREFLIGHT_ERROR",
        "controller_id": CONTROLLER_ID,
        "error": error,
        "canonical_authority": CANONICAL_AUTHORITY,
        "instruction": (
            "Read the canonical authority, locate this controller's "
            "Pre-initiation sequence location, and follow its installation instructions."
        ),
    }
    if detail is not None:
        message["detail"] = detail
    if missing_files:
        message["missing_files"] = missing_files

    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    raise SystemExit(78)


def require_local_filename(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        fail_preflight(
            "invalid_runtime_manifest",
            detail=f"{field} must be one local filename",
        )
    return value


def load_manifest() -> dict[str, Any]:
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail_preflight(
            "missing_runtime_manifest",
            missing_files=[MANIFEST_PATH.name],
        )
    except (OSError, json.JSONDecodeError) as exc:
        fail_preflight(
            "invalid_runtime_manifest",
            detail=str(exc),
        )

    if not isinstance(value, dict):
        fail_preflight(
            "invalid_runtime_manifest",
            detail="manifest root must be a JSON object",
        )
    return value


def validate_runtime_unit(manifest: dict[str, Any]) -> Path:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        fail_preflight(
            "invalid_runtime_manifest",
            detail=f"schema must equal {MANIFEST_SCHEMA}",
        )
    if manifest.get("controller_id") != CONTROLLER_ID:
        fail_preflight(
            "invalid_runtime_manifest",
            detail=f"controller_id must equal {CONTROLLER_ID}",
        )
    if manifest.get("canonical_installation_authority") != CANONICAL_AUTHORITY:
        fail_preflight(
            "invalid_runtime_manifest",
            detail="canonical_installation_authority does not match the runner authority",
        )

    runner_name = require_local_filename(manifest.get("runner"), "runner")
    if runner_name != Path(__file__).name:
        fail_preflight(
            "invalid_runtime_manifest",
            detail="runner does not identify the executing runner file",
        )

    entry_point = require_local_filename(manifest.get("entry_point"), "entry_point")
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, dict) or set(dependencies) != set(DEPENDENCY_ROLES):
        fail_preflight(
            "invalid_runtime_manifest",
            detail=f"dependencies must contain exactly {list(DEPENDENCY_ROLES)}",
        )

    dependency_names = [
        require_local_filename(dependencies[role], f"dependencies.{role}")
        for role in DEPENDENCY_ROLES
    ]
    required_names = [entry_point, *dependency_names]
    if len(set(required_names)) != len(required_names):
        fail_preflight(
            "invalid_runtime_manifest",
            detail="entry point and dependency filenames must be distinct",
        )

    missing = [name for name in required_names if not (HERE / name).is_file()]
    if missing:
        fail_preflight(
            "missing_runtime_dependencies",
            missing_files=missing,
        )

    return HERE / entry_point


def main() -> None:
    entry_point = validate_runtime_unit(load_manifest())
    try:
        os.execv(sys.executable, [sys.executable, str(entry_point)])
    except OSError as exc:
        fail_preflight(
            "runtime_start_failed",
            detail=str(exc),
        )


if __name__ == "__main__":
    main()
