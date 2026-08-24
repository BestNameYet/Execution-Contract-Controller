#!/usr/bin/env python3
"""CREATE dialogue v3 with contract KB provenance and post-draft association.

The dialogue constructs a contract draft, records which supplied KB items actually
informed the draft, inspects the drafted script for additional KB associations,
and finalizes contract.kb_items as the deduplicated union.

The final model stdin object is:
    {"result": <finalized contract>, "transition": "execute|revise|exit"}
No stdout is emitted after that terminal response is accepted.
"""

from __future__ import annotations

from typing import Any

from create_dialogue_v2 import (
    DEFINITION_PATH,
    EXECUTION_KB_PATH,
    CONTEXT_KB_PATH,
    compact,
    context_entry,
    emit_metadata,
    emit_model,
    fail,
    load_object,
    read_object,
    require_string,
    require_string_list,
    resolve_selected,
    search_topics,
)


def require_string_array(
    obj: dict[str, Any],
    key: str,
    *,
    stage: str,
    max_items: int = 32,
) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list) or len(value) > max_items:
        fail(
            "INVALID_FIELD",
            f"'{key}' must be an array of at most {max_items} strings.",
            stage=stage,
            path=f"$.{key}",
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        fail(
            "INVALID_FIELD",
            f"'{key}' must contain only non-empty strings.",
            stage=stage,
            path=f"$.{key}",
        )
    if len(set(value)) != len(value):
        fail(
            "INVALID_FIELD",
            f"'{key}' must contain unique strings.",
            stage=stage,
            path=f"$.{key}",
        )
    return value


def validate_draft(
    obj: dict[str, Any],
    *,
    selected_topics: list[str],
    stage: str,
) -> tuple[str, dict[str, Any], list[str]]:
    if set(obj.keys()) != {"execution_script", "return_schema", "used_kb_items"}:
        fail(
            "INVALID_DRAFT_SHAPE",
            "Draft must contain exactly execution_script, return_schema, and used_kb_items.",
            stage=stage,
        )
    script = obj.get("execution_script")
    schema = obj.get("return_schema")
    if not isinstance(script, str) or not script.strip():
        fail("INVALID_DRAFT", "execution_script must be a non-empty string.", stage=stage)
    if not isinstance(schema, dict):
        fail("INVALID_DRAFT", "return_schema must be a JSON object.", stage=stage)
    used = require_string_array(obj, "used_kb_items", stage=stage, max_items=max(32, len(selected_topics)))
    selected_set = set(selected_topics)
    invalid = [item for item in used if item not in selected_set]
    if invalid:
        fail(
            "INVALID_KB_USAGE",
            "used_kb_items must be IDs from the full KB records supplied to the drafting step.",
            stage=stage,
            path="$.used_kb_items",
        )
    return script, schema, used


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def main() -> None:
    definition = load_object(DEFINITION_PATH)
    execution_kb = load_object(EXECUTION_KB_PATH)
    context_kb = load_object(CONTEXT_KB_PATH)
    create_return_schema = definition.get("return_schema")
    allowed_transitions = definition.get("allowed_transitions")
    if not isinstance(create_return_schema, dict):
        fail("INVALID_DEFINITION", "CREATE definition must contain return_schema.")
    if not isinstance(allowed_transitions, list) or not all(isinstance(x, str) for x in allowed_transitions):
        fail("INVALID_DEFINITION", "CREATE definition must contain allowed_transitions.")

    emit_metadata(
        "DIALOGUE_STARTED",
        dialogue="create_dialogue_v3",
        definition_id=definition.get("id"),
        context_kb_version=context_kb.get("version"),
    )

    seq = emit_model(
        {
            "stage": "WELCOME_AND_USER_PROMPT",
            "message": "Welcome. This mode constructs an executable transaction from the current user request. Return only the JSON object required at each step.",
            "request": "Return the exact current user prompt without rewriting it.",
            "return_schema": {
                "type": "object",
                "required": ["user_prompt"],
                "properties": {"user_prompt": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "acquire_user_prompt"},
    )
    user_prompt = require_string(
        read_object(stage="WELCOME_AND_USER_PROMPT", responding_to=seq),
        "user_prompt",
        stage="WELCOME_AND_USER_PROMPT",
    )

    prompt_to_goal = context_entry(context_kb, "context.prompt-to-goal")
    seq = emit_model(
        {
            "stage": "PROMPT_TO_GOAL",
            "user_prompt": user_prompt,
            "mandatory_context": prompt_to_goal,
            "request": "Convert the user prompt to its execution goal.",
            "return_schema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "prompt_to_goal", "mandatory_context_ids": [prompt_to_goal["id"]]},
    )
    goal = require_string(
        read_object(stage="PROMPT_TO_GOAL", responding_to=seq),
        "goal",
        stage="PROMPT_TO_GOAL",
    )

    goal_to_query = context_entry(context_kb, "context.goal-to-query")
    seq = emit_model(
        {
            "stage": "GOAL_TO_QUERY",
            "goal": goal,
            "mandatory_context": goal_to_query,
            "request": "Return the execution-KB queries needed to retrieve useful context for this goal.",
            "return_schema": {
                "type": "object",
                "required": ["queries"],
                "properties": {
                    "queries": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1},
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={"semantic_operation": "goal_to_queries", "mandatory_context_ids": [goal_to_query["id"]]},
    )
    queries = require_string_list(
        read_object(stage="GOAL_TO_QUERY", responding_to=seq),
        "queries",
        stage="GOAL_TO_QUERY",
    )

    candidates, retrieval_eval = search_topics(execution_kb, queries)
    select_topics = context_entry(context_kb, "context.select-topics")
    seq = emit_model(
        {
            "stage": "TOPIC_SELECTION",
            "goal": goal,
            "queries": queries,
            "candidate_topics": candidates,
            "mandatory_context": select_topics,
            "request": "Select the candidate KB topics whose full records should ground construction of the solver instruction.",
            "return_schema": {
                "type": "object",
                "required": ["selected_topics"],
                "properties": {
                    "selected_topics": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "enum": [item["id"] for item in candidates]},
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "select_execution_context",
            "mandatory_context_ids": [select_topics["id"]],
            "retrieval": retrieval_eval,
        },
    )
    selected_topics = require_string_list(
        read_object(stage="TOPIC_SELECTION", responding_to=seq),
        "selected_topics",
        stage="TOPIC_SELECTION",
        max_items=max(1, len(candidates)),
    )
    candidate_ids = {item["id"] for item in candidates}
    if len(set(selected_topics)) != len(selected_topics) or any(item not in candidate_ids for item in selected_topics):
        fail("INVALID_SELECTION", "selected_topics must be unique IDs from candidate_topics.", stage="TOPIC_SELECTION")
    selected_context = resolve_selected(execution_kb, selected_topics)

    synthesize = context_entry(context_kb, "context.synthesize-solver-instruction")
    seq = emit_model(
        {
            "stage": "SYNTHESIZE_SOLVER_INSTRUCTION",
            "user_prompt": user_prompt,
            "goal": goal,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
            "mandatory_context": synthesize,
            "request": "Construct the complete instruction that should be followed to solve this goal under the supplied KB context. Do not solve the goal yet.",
            "return_schema": {
                "type": "object",
                "required": ["instruction"],
                "properties": {"instruction": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "synthesize_solver_instruction",
            "mandatory_context_ids": [synthesize["id"]],
            "selected_topic_ids": selected_topics,
        },
    )
    solver_instruction = require_string(
        read_object(stage="SYNTHESIZE_SOLVER_INSTRUCTION", responding_to=seq),
        "instruction",
        stage="SYNTHESIZE_SOLVER_INSTRUCTION",
    )

    apply_instruction = context_entry(context_kb, "context.apply-solver-instruction")
    seq = emit_model(
        {
            "stage": "DRAFT_EXECUTION_CONTRACT",
            "user_prompt": user_prompt,
            "goal": goal,
            "selected_topics": selected_topics,
            "selected_context": selected_context,
            "solver_instruction": solver_instruction,
            "mandatory_context": apply_instruction,
            "request": "Execute solver_instruction semantically now. Draft the executable contract and report which supplied KB records actually informed the draft.",
            "return_schema": {
                "type": "object",
                "required": ["execution_script", "return_schema", "used_kb_items"],
                "properties": {
                    "execution_script": {"type": "string", "minLength": 1},
                    "return_schema": {"type": "object"},
                    "used_kb_items": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "enum": selected_topics},
                    },
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "draft_execution_contract",
            "mandatory_context_ids": [apply_instruction["id"]],
            "selected_topic_ids": selected_topics,
            "solver_instruction_chars": len(solver_instruction),
        },
    )
    draft_msg = read_object(stage="DRAFT_EXECUTION_CONTRACT", responding_to=seq)
    execution_script, execution_return_schema, used_kb_items = validate_draft(
        draft_msg,
        selected_topics=selected_topics,
        stage="DRAFT_EXECUTION_CONTRACT",
    )

    inspect_associations = context_entry(context_kb, "context.inspect-contract-kb-associations")
    seq = emit_model(
        {
            "stage": "POST_DRAFT_KB_QUERY",
            "goal": goal,
            "execution_script": execution_script,
            "used_kb_items": used_kb_items,
            "mandatory_context": inspect_associations,
            "request": "Inspect the drafted script and return KB retrieval queries for any additional topics that should be associated with the contract because of actions the script will perform. Return an empty array if none are needed.",
            "return_schema": {
                "type": "object",
                "required": ["queries"],
                "properties": {
                    "queries": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1},
                    }
                },
                "additionalProperties": False,
            },
        },
        metadata={
            "semantic_operation": "identify_post_draft_kb_queries",
            "mandatory_context_ids": [inspect_associations["id"]],
            "used_to_draft_kb_items": used_kb_items,
        },
    )
    post_query_msg = read_object(stage="POST_DRAFT_KB_QUERY", responding_to=seq)
    post_queries = require_string_array(post_query_msg, "queries", stage="POST_DRAFT_KB_QUERY", max_items=8)

    additional_kb_items: list[str] = []
    additional_context: list[dict[str, Any]] = []
    post_retrieval_eval: list[dict[str, Any]] = []

    if post_queries:
        post_candidates, post_retrieval_eval = search_topics(execution_kb, post_queries)
        used_set = set(used_kb_items)
        post_candidates = [item for item in post_candidates if item["id"] not in used_set]

        select_associations = context_entry(context_kb, "context.select-contract-kb-associations")
        seq = emit_model(
            {
                "stage": "POST_DRAFT_KB_SELECTION",
                "goal": goal,
                "execution_script": execution_script,
                "used_kb_items": used_kb_items,
                "queries": post_queries,
                "candidate_topics": post_candidates,
                "mandatory_context": select_associations,
                "request": "Select any additional candidate KB topics that should be associated with this contract because of concrete actions in execution_script. An empty selection is valid.",
                "return_schema": {
                    "type": "object",
                    "required": ["additional_kb_items"],
                    "properties": {
                        "additional_kb_items": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": [item["id"] for item in post_candidates]},
                        }
                    },
                    "additionalProperties": False,
                },
            },
            metadata={
                "semantic_operation": "select_post_draft_kb_associations",
                "mandatory_context_ids": [select_associations["id"]],
                "retrieval": post_retrieval_eval,
                "used_to_draft_kb_items": used_kb_items,
            },
        )
        selection_msg = read_object(stage="POST_DRAFT_KB_SELECTION", responding_to=seq)
        additional_kb_items = require_string_array(
            selection_msg,
            "additional_kb_items",
            stage="POST_DRAFT_KB_SELECTION",
            max_items=max(32, len(post_candidates)),
        )
        valid_additional = {item["id"] for item in post_candidates}
        if any(item not in valid_additional for item in additional_kb_items):
            fail(
                "INVALID_ASSOCIATION",
                "additional_kb_items must be IDs from candidate_topics.",
                stage="POST_DRAFT_KB_SELECTION",
            )
        additional_context = resolve_selected(execution_kb, additional_kb_items)

    final_kb_items = dedupe(used_kb_items + additional_kb_items)
    finalized_contract = {
        "execution_script": execution_script,
        "return_schema": execution_return_schema,
        "kb_items": final_kb_items,
    }

    finalize_context = context_entry(context_kb, "context.finalize-contract")
    terminal_schema = {
        "type": "object",
        "required": ["result", "transition"],
        "properties": {
            "result": create_return_schema,
            "transition": {"type": "string", "enum": allowed_transitions},
        },
        "additionalProperties": False,
    }
    seq = emit_model(
        {
            "stage": "FINALIZE_CONTRACT",
            "goal": goal,
            "finalized_contract": finalized_contract,
            "associated_kb_context": resolve_selected(execution_kb, final_kb_items) if final_kb_items else [],
            "mandatory_context": finalize_context,
            "request": "Return finalized_contract exactly as result and choose the next transaction transition.",
            "return_schema": terminal_schema,
        },
        metadata={
            "semantic_operation": "finalize_contract_and_choose_transition",
            "mandatory_context_ids": [finalize_context["id"]],
            "used_to_draft_kb_items": used_kb_items,
            "associated_for_execution_kb_items": additional_kb_items,
            "final_kb_items": final_kb_items,
            "additional_context_count": len(additional_context),
            "terminal_response": True,
        },
    )
    terminal = read_object(stage="FINALIZE_CONTRACT", responding_to=seq)
    if set(terminal.keys()) != {"result", "transition"}:
        fail("INVALID_TERMINAL_SHAPE", "Terminal response must contain exactly result and transition.", stage="FINALIZE_CONTRACT")
    if terminal.get("result") != finalized_contract:
        fail(
            "CONTRACT_MUTATED_DURING_FINALIZATION",
            "result must equal finalized_contract exactly.",
            stage="FINALIZE_CONTRACT",
            path="$.result",
        )
    transition = terminal.get("transition")
    if transition not in allowed_transitions:
        fail("INVALID_TRANSITION", "transition is not allowed for CREATE.", stage="FINALIZE_CONTRACT")

    emit_metadata(
        "DIALOGUE_COMPLETED",
        dialogue="create_dialogue_v3",
        final_message_sequence=seq,
        transition=transition,
        used_to_draft_kb_items=used_kb_items,
        associated_for_execution_kb_items=additional_kb_items,
        final_kb_items=final_kb_items,
        execution_script_chars=len(execution_script),
    )


if __name__ == "__main__":
    main()
