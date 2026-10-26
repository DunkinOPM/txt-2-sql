import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class QueryCreateRequest(BaseModel):
    dataset_id: uuid.UUID = Field(..., description="ID of the authorized dataset to query.")
    question: str = Field(..., min_length=1, max_length=2000, description="User's natural language question.")


class ClarificationAnswerRequest(BaseModel):
    selected_option: Optional[str] = Field(None, max_length=500, description="Selected option from clarification options.")
    free_text_answer: Optional[str] = Field(None, max_length=1000, description="Optional free-text clarification response.")

    @model_validator(mode="after")
    def validate_answer(self):
        opt = (self.selected_option or "").strip()
        free = (self.free_text_answer or "").strip()
        if not opt and not free:
            raise ValueError("Either 'selected_option' or 'free_text_answer' must be provided.")
        return self


class QueryTurnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turn_number: int
    role: str
    turn_type: str
    content: str
    created_at: datetime


class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    original_question: str
    refined_question: Optional[str] = None
    category: Optional[str] = None
    status: str
    assistant_message: str
    clarification_question: Optional[str] = None
    clarification_options: Optional[List[str]] = None
    generated_sql: Optional[str] = None
    explanation: Optional[str] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    result_row_count: Optional[int] = None
    execution_duration_ms: Optional[int] = None
    turns: List[QueryTurnResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class QueryHistoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    original_question: str
    refined_question: Optional[str] = None
    category: Optional[str] = None
    status: str
    result_row_count: Optional[int] = None
    execution_duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class QueryHistoryListResponse(BaseModel):
    items: List[QueryHistoryItemResponse]
    total: int
    limit: int
    offset: int


class SuggestedQuestionsResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    questions: List[str]
