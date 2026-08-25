from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from initial import INSTRUCTION_1, INSTRUCTION_2, INSTRUCTION_3, StageValidationError, capture_1, capture_2, run_initial


def emit(obj):
    return f"import json; print(json.dumps({obj!r}))"


class InitialPipelineTests(unittest.TestCase):
    def test_normal_path_builds_script_then_executes_it(self):
        requests = []
        responses = iter(
            [
                {"questions": ["What result should be produced?"]},
                {
                    "qa": [
                        {
                            "question": "What result should be produced?",
                            "answer": "done",
                        }
                    ]
                },
                {"script": emit({"result": "done"})},
            ]
        )

        def model_call(request):
            requests.append(request)
            return next(responses)

        with tempfile.TemporaryDirectory() as tmp:
            result = run_initial("Produce the requested result", model_call, receipt_dir=tmp)
            self.assertEqual(result, {"result": "done"})
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 1)

        self.assertEqual([request["instruction"] for request in requests], [INSTRUCTION_1, INSTRUCTION_2, INSTRUCTION_3])
        self.assertIn("user_prompt", requests[0]["payload"])
        self.assertIn("timestamp", requests[0]["payload"])
        self.assertIn("sha256", requests[0]["payload"])
        self.assertEqual(
            requests[1]["payload"],
            {"questions": ["What result should be produced?"]},
        )
        self.assertEqual(
            requests[2]["payload"],
            {
                "qa": [
                    {
                        "question": "What result should be produced?",
                        "answer": "done",
                    }
                ]
            },
        )

    def test_question_mismatch_restarts_at_a_and_creates_new_question_set(self):
        requests = []
        responses = iter(
            [
                {"questions": ["Old question?"]},
                {"qa": [{"question": "Changed question?", "answer": "bad"}]},
                {"questions": ["New question?"]},
                {"qa": [{"question": "New question?", "answer": "good"}]},
                {"script": emit({"result": "good"})},
            ]
        )

        def model_call(request):
            requests.append(request)
            return next(responses)

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                run_initial("Solve this", model_call, receipt_dir=tmp),
                {"result": "good"},
            )

        self.assertEqual(
            [request["instruction"] for request in requests],
            [INSTRUCTION_1, INSTRUCTION_2, INSTRUCTION_1, INSTRUCTION_2, INSTRUCTION_3],
        )
        self.assertEqual(requests[1]["payload"], {"questions": ["Old question?"]})
        self.assertEqual(requests[3]["payload"], {"questions": ["New question?"]})
        self.assertNotEqual(
            requests[0]["payload"]["sha256"],
            requests[2]["payload"]["sha256"],
        )

    def test_snapshot_tampering_is_rejected(self):
        state = capture_1({"user_prompt": "x", "attempt": 1})
        state["prompt_snapshot"]["user_prompt"] = "tampered"
        state["model_response"] = {"questions": ["Q?"]}
        with self.assertRaises(StageValidationError):
            capture_2(state)


if __name__ == "__main__":
    unittest.main()
