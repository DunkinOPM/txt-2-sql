from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class ClassificationCategory(str, Enum):
    RELEVANT_CLEAR = "RELEVANT_CLEAR"
    RELEVANT_AMBIGUOUS = "RELEVANT_AMBIGUOUS"
    RELEVANT_UNANSWERABLE = "RELEVANT_UNANSWERABLE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NONSENSICAL = "NONSENSICAL"
    IMPROPER_OR_UNSAFE = "IMPROPER_OR_UNSAFE"


class ClassificationResult(BaseModel):
    category: ClassificationCategory = Field(
        ...,
        description="The primary classification category for the user query."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification (advisory)."
    )
    reason: str = Field(
        ...,
        description="Detailed plain-English reasoning behind the classification."
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="List of requested columns or fields that do not exist in the dataset."
    )
    ambiguities: List[str] = Field(
        default_factory=list,
        description="Identified points of ambiguity that require clarification."
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="A targeted clarifying question if category is RELEVANT_AMBIGUOUS."
    )
    clarification_options: Optional[List[str]] = Field(
        default=None,
        description="2-4 concrete, mutually exclusive options for the user to choose from."
    )
