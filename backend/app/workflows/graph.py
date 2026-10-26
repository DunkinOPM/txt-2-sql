from langgraph.graph import StateGraph, START, END
from app.workflows.state import QueryWorkflowState
from app.workflows.nodes import (
    classify_node,
    clarification_node,
    refusal_node,
    ready_node,
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


query_graph = build_query_workflow()
