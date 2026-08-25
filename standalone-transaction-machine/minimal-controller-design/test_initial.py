from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from initial import (
    INSTRUCTION_1,
    INSTRUCTION_2,
    INSTRUCTION_3,
    StageValidationError,
    capture_1,
    capture_2,
    resume_initial,
    start_initial,
)


def emit(obj):
    return f"import json; print(json.dumps({obj!r}))"


class InitialPipelineTests(unittest.TestCase):
    def test_normal_path_builds_script_then_executes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = start_initial("Produce the requested result", receipt_dir=tmp)
            self.assertEqual(machine["type"], "MODEL_REQUEST")
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_1)
            self.assertIn("user_prompt", machine["state"]["model_request"]["payload"])
            self.assertIn("timestamp", machine["state"]["model_request"]["payload"])
            self.assertIn("sha256", machine["state"]["model_request"]["payload"])

            machine = resume_initial(
                machine,
                {"questions": ["What result should be produced?"]},
            )
            self.assertEqual(machine["type"], "MODEL_REQUEST")
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_2)
            self.assertEqual(
                machine["state"]["model_request"]["payload"],
                {"questions": ["What result should be produced?"]},
            )

            machine = resume_initial(
                machine,
                {
                    "qa": [
                        {
                            "question": "What result should be produced?",
                            "answer": "done",
                        }
                    ]
                },
            )
            self.assertEqual(machine["type"], "MODEL_REQUEST")
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_3)
            self.assertEqual(
                machine["state"]["model_request"]["payload"],
                {
                    "qa": [
                        {
                            "question": "What result should be produced?",
                            "answer": "done",
                        }
                    ]
                },
            )

            complete = resume_initial(
                machine,
                {"script": emit({"result": "done"})},
            )
            self.assertEqual(complete["type"], "COMPLETE")
            self.assertEqual(complete["result"], {"result": "done"})
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 1)

    def test_question_mismatch_restarts_at_a_and_creates_new_question_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = start_initial("Solve this", receipt_dir=tmp)
            first_prompt_snapshot = dict(machine["state"]["model_request"]["payload"])

            machine = resume_initial(machine, {"questions": ["Old question?"]})
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_2)
            self.assertEqual(
                machine["state"]["model_request"]["payload"],
                {"questions": ["Old question?"]},
            )

            machine = resume_initial(
                machine,
                {"qa": [{"question": "Changed question?", "answer": "bad"}]},
            )
            self.assertEqual(machine["type"], "MODEL_REQUEST")
            self.assertEqual(machine["state"]["attempt"], 2)
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_1)
            self.assertEqual(machine["state"]["model_request"]["payload"]["user_prompt"], "Solve this")
            second_prompt_snapshot = dict(machine["state"]["model_request"]["payload"])
            self.assertNotEqual(first_prompt_snapshot["sha256"], second_prompt_snapshot["sha256"])

            machine = resume_initial(machine, {"questions": ["New question?"]})
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_2)
            self.assertEqual(
                machine["state"]["model_request"]["payload"],
                {"questions": ["New question?"]},
            )

            machine = resume_initial(
                machine,
                {"qa": [{"question": "New question?", "answer": "good"}]},
            )
            self.assertEqual(machine["state"]["model_request"]["instruction"], INSTRUCTION_3)

            complete = resume_initial(
                machine,
                {"script": emit({"result": "good"})},
            )
            self.assertEqual(complete["type"], "COMPLETE")
            self.assertEqual(complete["result"], {"result": "good"})

    def test_snapshot_tampering_is_rejected(self):
        state = capture_1({"user_prompt": "x", "attempt": 1})
        state["prompt_snapshot"]["user_prompt"] = "tampered"
        state["model_response"] = {"questions": ["Q?"]}
        with self.assertRaises(StageValidationError):
            capture_2(state)


if __name__ == "__main__":
    unittest.main()
