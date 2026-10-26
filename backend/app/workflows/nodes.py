from typing import Any
from app.workflows.state import QueryWorkflowState
from app.services.llm_service import classify_query_with_gemini, rewrite_query_with_gemini
from app.schemas.classification import ClassificationCategory

MAX_CLARIFICATION_LOOPS = 3


def classify_node(state: QueryWorkflowState) -> dict[str, Any]:
    """
    Classifies the current question against the authorized dataset schema.
    """
    question_to_classify = state.get("current_question") or state.get("original_question", "")
    dataset_name = state.get("dataset_name", "Dataset")
    schema_summary = state.get("schema_summary", [])
    previous_clarifications = state.get("previous_clarifications", [])

    result = classify_query_with_gemini(
        dataset_name=dataset_name,
        schema_summary=schema_summary,
        question=question_to_classify,
        previous_clarifications=previous_clarifications,
    )

    return {
        "category": result.category.value,
        "missing_fields": result.missing_fields,
        "ambiguities": result.ambiguities,
        "clarification_question": result.clarification_question,
        "clarification_options": result.clarification_options,
    }


def clarification_node(state: QueryWorkflowState) -> dict[str, Any]:
    """
    Handles ambiguous queries. If maximum cycles are exceeded, halts gracefully;
    otherwise transitions status to awaiting_clarification.
    """
    turns = state.get("clarification_turns", 0)
    if turns >= MAX_CLARIFICATION_LOOPS:
        return {
            "status": "rejected",
            "assistant_message": (
                f"We've reached the maximum number of clarification attempts ({MAX_CLARIFICATION_LOOPS}). "
                "Please submit a new question with specific column names or filtering criteria."
            ),
            "clarification_question": None,
            "clarification_options": None,
        }

    q_text = state.get("clarification_question") or "Your question has multiple interpretations. Please clarify which you prefer."
    return {
        "status": "awaiting_clarification",
        "assistant_message": q_text,
    }


def refusal_node(state: QueryWorkflowState) -> dict[str, Any]:
    """
    Generates tailored, safe, and helpful explanations for queries that cannot proceed to SQL generation.
    """
    category = state.get("category", "")
    dataset_name = state.get("dataset_name", "the selected dataset")
    schema_summary = state.get("schema_summary", [])
    available_cols = ", ".join(f"'{c.get('original_name') or c.get('internal_name')}'" for c in schema_summary)

    if category == ClassificationCategory.OUT_OF_SCOPE.value:
        msg = (
            f"This question appears to be outside the scope of {dataset_name}. "
            f"You can query information related to: {available_cols}."
        )
    elif category == ClassificationCategory.RELEVANT_UNANSWERABLE.value:
        missing = state.get("missing_fields", [])
        missing_str = ", ".join(f"'{m}'" for m in missing) if missing else "required fields"
        msg = (
            f"Your question is related to {dataset_name}, but the dataset does not contain "
            f"the requested information for {missing_str}. Available fields include: {available_cols}."
        )
    elif category == ClassificationCategory.NONSENSICAL.value:
        msg = "We couldn't understand this input as a data question. Please check for typos and rephrase your query."
    elif category == ClassificationCategory.IMPROPER_OR_UNSAFE.value:
        msg = (
            "This query was refused because it requests unauthorized database operations, data modification, "
            "or instruction overrides."
        )
    else:
        msg = "The query could not be processed."

    return {
        "status": "rejected",
        "assistant_message": msg,
        "clarification_question": None,
        "clarification_options": None,
    }


def ready_node(state: QueryWorkflowState) -> dict[str, Any]:
    """
    Marks a clear, validated query as ready_for_sql (ready for Phase 4).
    Phase 3 halts here without generating or executing SQL.
    """
    return {
        "status": "ready_for_sql",
        "assistant_message": "Question is clear and ready for SQL generation.",
        "clarification_question": None,
        "clarification_options": None,
    }
