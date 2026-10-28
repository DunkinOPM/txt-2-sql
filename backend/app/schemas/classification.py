from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel, Field, model_validator


class ClassificationCategory(str, Enum):
    RELEVANT_CLEAR = "RELEVANT_CLEAR"
    RELEVANT_AMBIGUOUS = "RELEVANT_AMBIGUOUS"
    RELEVANT_UNANSWERABLE = "RELEVANT_UNANSWERABLE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NONSENSICAL = "NONSENSICAL"
    IMPROPER_OR_UNSAFE = "IMPROPER_OR_UNSAFE"


class QueryUnderstandingResult(BaseModel):
    """
    Structured natural-language query understanding result produced by Gemini.
    Combines categorization, intent extraction, target columns, aggregations,
    filters, sorting/ranking, row limits, and clarification details.
    """
    classification: ClassificationCategory = Field(
        ...,
        description="The primary classification category for the user query."
    )
    intent_summary: str = Field(
        default="",
        description="Concise 1-sentence summary of user's analytical goal."
    )
    requested_outputs: List[str] = Field(
        default_factory=list,
        description="Specific columns or attributes requested to be projected/returned."
    )
    measures: List[str] = Field(
        default_factory=list,
        description="Aggregations or quantitative metrics requested, e.g. 'AVG(age)', 'COUNT(*)'."
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filtering predicates or conditions requested by the user."
    )
    grouping: List[str] = Field(
        default_factory=list,
        description="Columns or dimensions to group by."
    )
    sorting_and_ranking: Optional[str] = Field(
        default=None,
        description="Ordering or ranking specification, e.g. 'gpa DESC', 'salary ASC'."
    )
    result_limit: Optional[int] = Field(
        default=None,
        description="Maximum number of rows requested (e.g. 1 for top 1, 5 for top 5)."
    )
    referenced_columns: List[str] = Field(
        default_factory=list,
        description="Dataset schema column names referenced directly or indirectly."
    )
    missing_information: List[str] = Field(
        default_factory=list,
        description="Information, columns, or metrics requested but absent from the dataset schema."
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="A targeted clarifying question if classification is RELEVANT_AMBIGUOUS."
    )
    clarification_options: Optional[List[str]] = Field(
        default=None,
        description="2-4 concrete, mutually exclusive options for the user to choose from."
    )
    reason: str = Field(
        default="",
        description="Detailed plain-English reasoning behind the classification."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification (advisory)."
    )

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map legacy 'category' to 'classification'
            if "category" in data and "classification" not in data:
                data["classification"] = data["category"]
            elif "classification" in data and "category" not in data:
                data["category"] = data["classification"]

            # Map legacy 'missing_fields' to 'missing_information'
            if "missing_fields" in data and "missing_information" not in data:
                data["missing_information"] = data["missing_fields"]
            elif "missing_information" in data and "missing_fields" not in data:
                data["missing_fields"] = data["missing_information"]
        return data

    @property
    def category(self) -> ClassificationCategory:
        return self.classification

    @property
    def missing_fields(self) -> List[str]:
        return self.missing_information

    @property
    def ambiguities(self) -> List[str]:
        if self.clarification_question:
            return [self.clarification_question]
        return []


# ClassificationResult is an alias to QueryUnderstandingResult for backward compatibility
ClassificationResult = QueryUnderstandingResult
