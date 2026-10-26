from langgraph.graph import StateGraph, START, END
from app.workflows.state import QueryWorkflowState
from app.workflows.nodes import (
    classify_node,
    clarification_node,
    refusal_node,
    ready_node,
    generate_sql_node,
    validate_sql_node,
    execute_sql_node,
    repair_sql_node,
    explain_results_node,
    fail_node,
    MAX_SQL_REPAIR_ATTEMPTS,
)
from app.schemas.classification import ClassificationCategory


def route_after_classification(state: QueryWorkflowState) -> str:
    """Conditional router based on classification category."""
    category = state.get("category")
    if category == ClassificationCategory.RELEVANT_CLEAR.value:
        return "ready"
    elif category == ClassificationCategory.RELEVANT_AMBIGUOUS.value:
        return "clarify"
    else:
        return "refuse"


def route_after_validation(state: QueryWorkflowState) -> str:
    """Routes to execution if valid; otherwise bounded repair or failure."""
    if not state.get("last_error"):
        return "execute_sql"

    attempts = state.get("repair_attempts", 0)
    if attempts < MAX_SQL_REPAIR_ATTEMPTS:
        return "repair_sql"
    return "fail_query"


def route_after_execution(state: QueryWorkflowState) -> str:
    """Routes to explanation on success; otherwise bounded repair or failure."""
    if not state.get("last_error"):
        return "explain_results"

    err_code = state.get("error_code")
    # Timeouts and permission denials should not be repaired in a loop
    if err_code in ("QUERY_TIMEOUT", "PERMISSION_DENIED"):
        return "fail_query"

    attempts = state.get("repair_attempts", 0)
    if attempts < MAX_SQL_REPAIR_ATTEMPTS:
        return "repair_sql"
    return "fail_query"


def build_query_workflow():
    """Builds and compiles the LangGraph classification and clarification workflow."""
    builder = StateGraph(QueryWorkflowState)

    builder.add_node("classify", classify_node)
    builder.add_node("clarify", clarification_node)
    builder.add_node("refuse", refusal_node)
    builder.add_node("ready", ready_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classification,
        {
            "ready": "ready",
            "clarify": "clarify",
            "refuse": "refuse",
        },
    )

    builder.add_edge("ready", END)
    builder.add_edge("clarify", END)
    builder.add_edge("refuse", END)

    return builder.compile()


def build_sql_execution_subgraph():
    """Builds and compiles the sub-graph for SQL generation, validation, execution, and repair."""
    builder = StateGraph(QueryWorkflowState)
    builder.add_node("generate_sql", generate_sql_node)
    builder.add_node("validate_sql", validate_sql_node)
    builder.add_node("execute_sql", execute_sql_node)
    builder.add_node("repair_sql", repair_sql_node)
    builder.add_node("explain_results", explain_results_node)
    builder.add_node("fail_query", fail_node)

    builder.add_edge(START, "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges(
        "validate_sql",
        route_after_validation,
        {
            "execute_sql": "execute_sql",
            "repair_sql": "repair_sql",
            "fail_query": "fail_query",
        },
    )
    builder.add_conditional_edges(
        "execute_sql",
        route_after_execution,
        {
            "explain_results": "explain_results",
            "repair_sql": "repair_sql",
            "fail_query": "fail_query",
        },
    )
    builder.add_edge("repair_sql", "validate_sql")
    builder.add_edge("explain_results", END)
    builder.add_edge("fail_query", END)
    return builder.compile()


query_graph = build_query_workflow()
sql_execution_graph = build_sql_execution_subgraph()
