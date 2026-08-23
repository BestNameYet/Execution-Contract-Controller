#!/usr/bin/env python3
"""Invoke the controller and synchronously persist each finalized invocation in the carrier."""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

import execution_contract_controller as controller
import runtime_client

CARRIER_EVENT_RECEIPT_SCHEMA = "execution-runtime-carrier-event-receipt-v1"


def _event_from_output(output: dict[str, Any]) -> dict[str, Any]:
    state = output.get("state")
    if not isinstance(state, dict):
        raise ValueError("controller output does not carry state")
    history = controller.req_list(state.get("transport_history"), "transport_history")
    times = controller.req_list(state.get("transport_times"), "transport_times")
    if len(history) != len(times) or len(history) < 2 or len(history) % 2:
        raise ValueError("controller transport history does not end in a complete invocation")
    input_data = controller._transport_snapshot(controller.req_dict(history[-2], "latest input"))
    output_data = controller._transport_snapshot(controller.req_dict(history[-1], "latest output"))
    timestamp_started = controller.req_text(times[-2], "timestamp_started")
    timestamp_completed = controller.req_text(times[-1], "timestamp_completed")
    turn_id = controller.req_text(state.get("turn_id"), "turn_id")
    identity = {
        "timestamp_started": timestamp_started,
        "timestamp_completed": timestamp_completed,
        "turn_id": turn_id,
        "input": input_data,
        "output": output_data,
    }
    event_id = "invoke_" + hashlib.sha256(controller.canon(identity).encode("utf-8")).hexdigest()[:16]
    exception = None
    if output_data.get("authority") == "PROTOCOL_ERROR":
        exception = {
            "type": str(output_data.get("error_type", "ProtocolError")),
            "message": str(output_data.get("error", "protocol error")),
        }
    return {
        "schema": controller.INVOCATION_EVENT_SCHEMA,
        "event_id": event_id,
        "timestamp_started": timestamp_started,
        "timestamp_completed": timestamp_completed,
        "turn_id": turn_id,
        "project": controller.PROJECT_NAME,
        "source": {"component": "execution_contract_controller.py", "method": "dispatch"},
        "invocation": {"input": input_data, "output": output_data, "exception": exception},
    }


def _sheet_cell(value: str) -> dict[str, Any]:
    return {"userEnteredValue": {"stringValue": value}}


def _backlog_recording_instruction(events_get: dict[str, Any]) -> dict[str, Any] | None:
    events = events_get.get("events", [])
    if not events:
        return None
    rows = [controller.event_row(event) for event in events]
    through_sequence = max(int(event["sequence"]) for event in events)
    return {
        "schema": controller.RECORDING_DIRECTIVE_SCHEMA,
        "type": "RECORD_EVENTS",
        "operation": "APPEND_EVENT_ROWS",
        "execution_scope": "OUT_OF_BAND",
        "affects_controller_state": False,
        "affects_execution_evaluation": False,
        "must_not_enter_semantic_chain": True,
        "provider": "GOOGLE_DRIVE",
        "tool": "Google_Drive.batch_update_spreadsheet",
        "target": {
            "folder_id": controller.PROJECT_RECORD_FOLDER_ID,
            "folder_name": controller.PROJECT_RECORD_FOLDER_NAME,
            "spreadsheet_id": controller.PROJECT_RECORD_SPREADSHEET_ID,
            "worksheet": controller.PROJECT_RECORD_WORKSHEET,
            "sheet_id": controller.PROJECT_RECORD_SHEET_ID,
        },
        "column_schema": [
            "schema_version", "event_id", "timestamp_started", "timestamp_completed", "duration_ms",
            "turn_id", "method", "input_type", "protocol", "authority", "outcome",
            "exception_type", "exception_text", "input_json", "output_json",
        ],
        "event_count": len(events),
        "carrier_sequence_start": min(int(event["sequence"]) for event in events),
        "carrier_sequence_end": through_sequence,
        "api_call": {
            "spreadsheet_id": controller.PROJECT_RECORD_SPREADSHEET_ID,
            "requests": [{
                "appendCells": {
                    "sheetId": controller.PROJECT_RECORD_SHEET_ID,
                    "rows": [{"values": [_sheet_cell(value) for value in row]} for row in rows],
                    "fields": "userEnteredValue",
                }
            }],
        },
        "carrier_ack": {"op": "EVENTS_MARK_RECORDED", "through_sequence": through_sequence},
        "execution_rules": [
            "The carrier event queue is the durable source of truth; the Sheet is its append-only projection.",
            "Invoke Google_Drive.batch_update_spreadsheet exactly once using api_call as its arguments.",
            "Only after that append succeeds, invoke the local carrier with carrier_ack exactly once.",
            "Do not feed the recording instruction, Sheet result, or carrier acknowledgement into the controller semantic chain.",
        ],
    }


def run(inp: Any) -> tuple[dict[str, Any], bool]:
    output = controller.dispatch(inp)
    persisted = False
    if isinstance(output.get("state"), dict):
        try:
            event = _event_from_output(output)
            receipt = runtime_client.call("EVENT_APPEND", event=event)
            if receipt.get("ok") is not True:
                raise RuntimeError(str(receipt.get("error", "carrier append failed")))
            output["recording_event"] = {
                "schema": CARRIER_EVENT_RECEIPT_SCHEMA,
                "event_id": receipt["event_id"],
                "sequence": receipt["sequence"],
                "parent_event_id": receipt.get("parent_event_id"),
                "state_version": receipt["state_version"],
            }
            persisted = True
            terminal = output.get("authority") == "FINAL_RESPONSE" and output.get("directive") in {"COMPLETE", "IMPASSE"}
            failed = output.get("authority") == "PROTOCOL_ERROR"
            if terminal or failed:
                context = runtime_client.call("EVENTS_GET", after_sequence=0)
                if context.get("ok") is not True:
                    raise RuntimeError(str(context.get("error", "carrier backlog read failed")))
                after = int(context.get("sheet_recorded_through", 0))
                pending = runtime_client.call("EVENTS_GET", after_sequence=after)
                if pending.get("ok") is not True:
                    raise RuntimeError(str(pending.get("error", "carrier pending read failed")))
                instruction = _backlog_recording_instruction(pending)
                if instruction is not None:
                    output["recording_instruction"] = instruction
        except Exception as exc:
            output["recording_event"] = {
                "schema": CARRIER_EVENT_RECEIPT_SCHEMA,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    return output, persisted


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"error": "expected one JSON line on stdin"}))
        return 2
    try:
        inp = json.loads(line)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}, separators=(",", ":")))
        return 2
    output, persisted = run(inp)
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    if not persisted and isinstance(output.get("state"), dict):
        return 3
    return 1 if output.get("authority") == "PROTOCOL_ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
