from typing import TypedDict, Optional, List, Any


class QueryWorkflowState(TypedDict, total=False):
    query_id: str
    dataset_id: str
    owner_id: str
    dataset_name: str
    schema_summary: List[dict[str, Any]]
    original_question: str
    refined_question: Optional[str]
    current_question: str
    clarification_turns: int
    previous_clarifications: List[dict[str, str]]
    category: Optional[str]
    status: str
    assistant_message: str
    clarification_question: Optional[str]
    clarification_options: Optional[List[str]]
    missing_fields: List[str]
    ambiguities: List[str]
    error_code: Optional[str]
    error_message: Optional[str]
