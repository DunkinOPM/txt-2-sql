import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_owner_id
from app.schemas.query import (
    QueryCreateRequest,
    ClarificationAnswerRequest,
    QueryResponse,
)
from app.services.query_service import (
    create_and_classify_query,
    submit_clarification_answer,
    get_query_status,
)

router = APIRouter(prefix="/api/queries", tags=["queries"])


@router.post("", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def submit_query(
    payload: QueryCreateRequest,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Submits a natural language question against an authorized dataset.
    Runs initial deterministic safety checks and LangGraph classification.
    """
    return create_and_classify_query(
        db=db,
        owner_id=owner_id,
        dataset_id=payload.dataset_id,
        question=payload.question,
    )


@router.post("/{query_id}/clarifications", response_model=QueryResponse)
def submit_clarification(
    query_id: uuid.UUID,
    payload: ClarificationAnswerRequest,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Submits user clarification answer for an ambiguous query.
    Rewrites the question, re-evaluates through the LangGraph workflow, and persists the turn.
    """
    return submit_clarification_answer(
        db=db,
        owner_id=owner_id,
        query_id=query_id,
        req=payload,
    )


@router.get("/{query_id}", response_model=QueryResponse)
def get_query(
    query_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieves the query details, status, and conversation turns for an authorized owner.
    """
    return get_query_status(
        db=db,
        owner_id=owner_id,
        query_id=query_id,
    )
