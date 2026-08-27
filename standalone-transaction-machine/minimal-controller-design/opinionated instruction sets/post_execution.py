import json
import sys
from typing import Any, Callable


try:
    POST_EXECUTION_CONTEXT
except NameError as exc:
    raise RuntimeError("POST_EXECUTION_CONTEXT was not supplied") from exc


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read_json_object() -> tuple[dict[str, Any] | None, str | None]:
    line = sys.stdin.readline()
    if line == "":
        raise RuntimeError("stdin closed before post-execution interrogation completed")
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None, "stdin response must be valid JSON"
    if not isinstance(value, dict):
        return None, "stdin response must be a JSON object"
    return value, None


def receive_valid(
    previous_message: dict[str, Any],
    validator: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    while True:
        value, error = _read_json_object()
        if error is None and value is not None:
            error = validator(value)
        if error is None and value is not None:
            return value
        emit({"error": error, "repeat": previous_message})


def validate_q2(value: dict[str, Any]) -> str | None:
    if set(value.keys()) != {"q2"}:
        return "stdin response keys must be exactly ['q2']"
    q2 = value["q2"]
    if not isinstance(q2, list):
        return "q2 must be a JSON array"
    if not 12 <= len(q2) <= 30:
        return "q2 must contain between 12 and 30 questions"
    if not all(isinstance(question, str) and question.strip() for question in q2):
        return "every q2 item must be a nonempty string"
    if len(set(q2)) != len(q2):
        return "q2 questions must be unique"
    return None


def validate_answer(value: dict[str, Any]) -> str | None:
    if set(value.keys()) != {"answer"}:
        return "stdin response keys must be exactly ['answer']"
    if not isinstance(value["answer"], str):
        return "answer must be a string"
    return None


def main() -> None:
    context = POST_EXECUTION_CONTEXT
    if not isinstance(context, dict):
        raise TypeError("POST_EXECUTION_CONTEXT must be a JSON object")

    question_request = {
        "instruction": (
            "Create a dense list of post-execution questions q2 that would assist a solver such as "
            "yourself in understanding and evaluating the execution result. Consider the achieved "
            "state, supporting evidence, discrepancies, constraint preservation, side effects, "
            "failures, and unresolved conditions. Return only the required return schema."
        ),
        **context,
        "return_schema": {"q2": ["<post-execution question>"]},
    }
    emit(question_request)
    question_response = receive_valid(question_request, validate_q2)

    qa2: list[dict[str, str]] = []
    for question in question_response["q2"]:
        answer_request = {
            "instruction": question,
            "desired_state": context["desired_state"],
            "execution_receipt": context["execution_receipt"],
            "return_schema": {"answer": "<answer>"},
        }
        emit(answer_request)
        answer_response = receive_valid(answer_request, validate_answer)
        qa2.append({"question": question, "answer": answer_response["answer"]})

    emit({"message": "Post-execution interrogation complete.", "qa2": qa2})


if __name__ == "__main__":
    main()
