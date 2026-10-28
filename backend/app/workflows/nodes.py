import logging
from typing import Any
from app.workflows.state import QueryWorkflowState
from app.services.llm_service import (
    classify_query_with_gemini,
    rewrite_query_with_gemini,
    generate_sql_with_gemini,
    repair_sql_with_gemini,
    generate_explanation_with_gemini,
)
from app.services.sql_validator import validate_sql_query, SqlValidationError
from app.services.sql_semantic_validator import validate_sql_semantics
from app.services.query_execution_service import execute_readonly_sql, QueryExecutionError
from app.schemas.classification import ClassificationCategory

logger = logging.getLogger(__name__)

MAX_CLARIFICATION_LOOPS = 3
MAX_SQL_REPAIR_ATTEMPTS = 2


def classify_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Classifies the current question against the authorized dataset schema."""
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
        "structured_intent": result.model_dump(),
    }


def clarification_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Handles ambiguous queries. Halts if maximum loops are exceeded."""
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
        "clarification_question": q_text,
        "clarification_options": state.get("clarification_options") or [],
    }


def refusal_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Generates tailored, safe explanations for queries that cannot proceed to SQL."""
    category = state.get("category", "")
    dataset_name = state.get("dataset_name", "the selected dataset")
    schema_summary = state.get("schema_summary", [])
    available_cols = ", ".join(f"'{c.get('original_name')}'" for c in schema_summary)

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
    """Marks query as ready for SQL generation (PRD handoff)."""
    return {
        "status": "ready_for_sql",
        "assistant_message": "Question is clear and ready for SQL generation.",
        "clarification_question": None,
        "clarification_options": None,
    }


def generate_sql_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Generates candidate PostgreSQL SELECT query using Gemini conditioned on structured intent."""
    question = state.get("current_question") or state.get("refined_question") or state.get("original_question", "")
    dataset_name = state.get("dataset_name", "Dataset")
    table_name = state.get("table_name", "")
    columns_metadata = state.get("columns_metadata", [])
    structured_intent = state.get("structured_intent")

    candidate_sql = generate_sql_with_gemini(
        dataset_name=dataset_name,
        table_name=table_name,
        columns=columns_metadata,
        question=question,
        structured_intent=structured_intent,
    )

    return {
        "candidate_sql": candidate_sql,
        "status": "validating_sql",
        "repair_attempts": state.get("repair_attempts", 0),
        "last_error": None,
    }


def validate_sql_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Validates candidate SQL using SQLGlot AST parsing, policy rules, and semantic intent checks."""
    candidate_sql = state.get("candidate_sql", "")
    table_name = state.get("table_name", "")
    columns_metadata = state.get("columns_metadata", [])
    allowed_columns = {c["internal_name"] for c in columns_metadata if "internal_name" in c}
    question = state.get("current_question") or state.get("refined_question") or state.get("original_question", "")
    structured_intent = state.get("structured_intent")

    try:
        # 1. Syntactic, schema, function, and AST safety validation
        normalized_sql = validate_sql_query(
            candidate_sql=candidate_sql,
            target_table_name=table_name,
            allowed_columns=allowed_columns,
        )

        # 2. Semantic intent validation: ensures SQL answers the user's question and preserves structured intent
        validate_sql_semantics(
            candidate_sql=normalized_sql,
            question=question,
            table_name=table_name,
            columns_metadata=columns_metadata,
            structured_intent=structured_intent,
        )

        return {
            "validated_sql": normalized_sql,
            "status": "executing",
            "last_error": None,
        }
    except SqlValidationError as e:
        logger.warning(f"SQL validation rejected query: [{e.error_code}] {e.message}")
        return {
            "last_error": e.message,
            "error_code": e.error_code,
            "validated_sql": None,
        }


def execute_sql_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Executes validated SQL query using readonly_user in PostgreSQL."""
    validated_sql = state.get("validated_sql", "")

    try:
        columns, rows, row_count, duration_ms = execute_readonly_sql(validated_sql)
        return {
            "result_columns": columns,
            "result_rows": rows,
            "result_row_count": row_count,
            "execution_duration_ms": duration_ms,
            "last_error": None,
        }
    except QueryExecutionError as e:
        logger.warning(f"SQL execution failed: [{e.error_code}] {e.message}")
        return {
            "last_error": e.message,
            "error_code": e.error_code,
        }


def repair_sql_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Prompts Gemini to correct invalid or failing SQL query."""
    attempts = state.get("repair_attempts", 0) + 1
    question = state.get("current_question") or state.get("refined_question") or state.get("original_question", "")
    dataset_name = state.get("dataset_name", "Dataset")
    table_name = state.get("table_name", "")
    columns_metadata = state.get("columns_metadata", [])
    failed_sql = state.get("candidate_sql", "")
    error_msg = state.get("last_error", "SQL validation failed")
    structured_intent = state.get("structured_intent")

    repaired_sql = repair_sql_with_gemini(
        dataset_name=dataset_name,
        table_name=table_name,
        columns=columns_metadata,
        question=question,
        failed_sql=failed_sql,
        error_message=error_msg,
        attempt=attempts,
        structured_intent=structured_intent,
    )

    return {
        "candidate_sql": repaired_sql,
        "repair_attempts": attempts,
        "status": "validating_sql",
        "last_error": None,
    }


def explain_results_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Generates natural language summary of the results."""
    question = state.get("current_question") or state.get("original_question", "")
    validated_sql = state.get("validated_sql", "")
    row_count = state.get("result_row_count", 0)

    explanation = generate_explanation_with_gemini(
        question=question,
        generated_sql=validated_sql,
        row_count=row_count,
    )

    return {
        "status": "completed",
        "explanation": explanation,
        "assistant_message": explanation,
    }


def fail_node(state: QueryWorkflowState) -> dict[str, Any]:
    """Terminates workflow with a clean failure state."""
    error_code = state.get("error_code") or "QUERY_FAILED"
    raw_error = state.get("last_error") or "Query execution failed."

    # User-safe explanation
    if error_code == "QUERY_TIMEOUT":
        user_msg = "The query took too long to execute and was halted to preserve database resources."
    elif error_code == "MISSING_REQUESTED_COLUMN":
        user_msg = f"The query could not be completed because the dataset does not contain the requested column. {raw_error}"
    elif error_code == "INCOMPATIBLE_COLUMN_TYPE":
        user_msg = f"The requested calculation is incompatible with the data type of the column. {raw_error}"
    elif error_code in ("UNAUTHORIZED_TABLE_ACCESS", "UNAUTHORIZED_COLUMN_ACCESS", "MUTATION_REJECTED"):
        user_msg = "The requested query attempted unauthorized database access or disallowed operations and was safely refused."
    else:
        orig_q = state.get("original_question", "your question")
        user_msg = f"We were unable to generate or execute a valid query to answer '{orig_q}' after multiple attempts. {raw_error}"

    return {
        "status": "failed",
        "error_code": error_code,
        "error_message": raw_error,
        "assistant_message": user_msg,
    }
