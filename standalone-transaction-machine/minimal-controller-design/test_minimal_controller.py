from __future__ import annotations

import unittest

from minimal_controller import (
    ChildExecutionError,
    ChildOutcomeValidationError,
    do_transaction,
)


def emit(obj):
    return f"import json; print(json.dumps({obj!r}))"


class MinimalControllerTests(unittest.TestCase):
    def test_empty_do_transaction_halts(self):
        self.assertIsNone(do_transaction())

    def test_script_generates_next_script_then_terminal_outcome(self):
        solution_script = emit({"result": "solved"})
        first_script = emit({"script": solution_script})
        self.assertEqual(do_transaction(first_script), {"result": "solved"})

    def test_child_outcome_allows_uninterpreted_extra_fields(self):
        solution_script = emit({"result": 7, "artifacts": ["x"], "state": {"a": 1}})
        first_script = emit({"script": solution_script, "metadata": {"stage": "next"}})
        self.assertEqual(
            do_transaction(first_script),
            {"result": 7, "artifacts": ["x"], "state": {"a": 1}},
        )

    def test_script_field_must_be_non_empty_string(self):
        with self.assertRaises(TypeError):
            do_transaction(emit({"script": 3}))
        with self.assertRaises(ValueError):
            do_transaction(emit({"script": ""}))

    def test_child_outcome_must_be_json_object(self):
        with self.assertRaises(ChildOutcomeValidationError):
            do_transaction("import json; print(json.dumps([1, 2, 3]))")

    def test_child_failure_is_reported(self):
        with self.assertRaises(ChildExecutionError):
            do_transaction("raise SystemExit(4)")


if __name__ == "__main__":
    unittest.main()
