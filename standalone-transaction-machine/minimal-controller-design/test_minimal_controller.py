from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from minimal_controller import (
    ChildExecutionError,
    ChildOutcomeValidationError,
    ReceiptValidationError,
    do_transaction,
    validate_saved_receipt,
)


def emit(obj):
    return f"import json; print(json.dumps({obj!r}))"


class MinimalControllerTests(unittest.TestCase):
    def test_empty_do_transaction_halts_without_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(do_transaction(receipt_dir=tmp))
            self.assertEqual(list(Path(tmp).glob("*.json")), [])

    def test_script_chain_creates_two_verified_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            solution_script = emit({"result": "solved"})
            first_script = emit({"script": solution_script})
            self.assertEqual(
                do_transaction(first_script, receipt_dir=tmp),
                {"result": "solved"},
            )

            paths = sorted(Path(tmp).glob("*.json"))
            self.assertEqual(len(paths), 2)
            receipts = [validate_saved_receipt(path) for path in paths]
            self.assertTrue(all(r["receipt_sha256"] for r in receipts))
            self.assertEqual({r["metadata"]["depth"] for r in receipts}, {0, 1})

            first = next(r for r in receipts if r["metadata"]["depth"] == 0)
            second = next(r for r in receipts if r["metadata"]["depth"] == 1)
            self.assertEqual(second["metadata"]["parent_transaction_id"], first["transaction_id"])

    def test_child_outcome_allows_uninterpreted_extra_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            solution_script = emit({"result": 7, "artifacts": ["x"], "state": {"a": 1}})
            first_script = emit({"script": solution_script, "metadata": {"stage": "next"}})
            self.assertEqual(
                do_transaction(first_script, receipt_dir=tmp),
                {"result": 7, "artifacts": ["x"], "state": {"a": 1}},
            )

    def test_invalid_next_script_saves_failed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError) as caught:
                do_transaction(emit({"script": 3}), receipt_dir=tmp)
            path = Path(caught.exception.receipt_path)
            receipt = validate_saved_receipt(path)
            self.assertEqual(receipt["metadata"]["status"], "FAILED")
            self.assertEqual(receipt["result"], {"script": 3})

    def test_child_outcome_must_be_json_object_and_receipt_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ChildOutcomeValidationError) as caught:
                do_transaction("import json; print(json.dumps([1, 2, 3]))", receipt_dir=tmp)
            receipt = validate_saved_receipt(caught.exception.receipt_path)
            self.assertEqual(receipt["metadata"]["status"], "FAILED")

    def test_child_failure_is_reported_and_receipt_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ChildExecutionError) as caught:
                do_transaction("raise SystemExit(4)", receipt_dir=tmp)
            receipt = validate_saved_receipt(caught.exception.receipt_path)
            self.assertEqual(receipt["exit_code"], 4)
            self.assertEqual(receipt["metadata"]["status"], "FAILED")

    def test_tampered_saved_receipt_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            do_transaction(emit({"result": "done"}), receipt_dir=tmp)
            path = next(Path(tmp).glob("*.json"))
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["result"] = {"result": "tampered"}
            path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaises(ReceiptValidationError):
                validate_saved_receipt(path)


if __name__ == "__main__":
    unittest.main()
