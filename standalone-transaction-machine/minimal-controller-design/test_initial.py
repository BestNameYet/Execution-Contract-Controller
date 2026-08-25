from __future__ import annotations

import unittest

from initial import (
    INSTRUCTION_1,
    INSTRUCTION_2,
    INSTRUCTION_3,
    StageValidationError,
    capture_1,
    capture_2,
    capture_3,
    capture_4,
)


class InitialPipelineTests(unittest.TestCase):
    def test_stage_sequence_produces_solution_script(self):
        state = capture_1({"user_prompt": "Produce the requested result", "attempt": 1})
        self.assertEqual(state["model_request"]["instruction"], INSTRUCTION_1)

        state["model_response"] = {"questions": ["What result should be produced?"]}
        state = capture_2(state)
        self.assertEqual(state["model_request"]["instruction"], INSTRUCTION_2)
        self.assertEqual(
            state["model_request"]["payload"],
            {"questions": ["What result should be produced?"]},
        )

        state["model_response"] = {
            "qa": [
                {
                    "question": "What result should be produced?",
                    "answer": "done",
                }
            ]
        }
        state = capture_3(state)
        self.assertEqual(state["model_request"]["instruction"], INSTRUCTION_3)

        state["model_response"] = {"script": "print('done')"}
        state = capture_4(state)
        self.assertEqual(state["script"], "print('done')")

    def test_question_mismatch_returns_restart_at_a(self):
        state = capture_1({"user_prompt": "Solve this", "attempt": 1})
        state["model_response"] = {"questions": ["Old question?"]}
        state = capture_2(state)
        state["model_response"] = {
            "qa": [{"question": "Changed question?", "answer": "bad"}]
        }
        state = capture_3(state)

        self.assertEqual(
            state,
            {
                "restart_at": "capture_1",
                "reason": "question_mismatch",
                "attempt": 2,
                "user_prompt": "Solve this",
            },
        )

    def test_snapshot_tampering_is_rejected(self):
        state = capture_1({"user_prompt": "x", "attempt": 1})
        state["prompt_snapshot"]["user_prompt"] = "tampered"
        state["model_response"] = {"questions": ["Q?"]}
        with self.assertRaises(StageValidationError):
            capture_2(state)


if __name__ == "__main__":
    unittest.main()
