import uuid
from typing import Optional
from fastapi import APIRouter, Depends, status, HTTPException, Response, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_owner_id
from app.schemas.query import (
    QueryCreateRequest,
    ClarificationAnswerRequest,
    QueryResponse,
    QueryHistoryListResponse,
)
from app.services.query_service import (
    create_and_classify_query,
    submit_clarification_answer,
    execute_ready_query,
    get_query_status,
    list_authorized_queries,
)
from app.services.query_execution_service import export_rows_to_safe_csv

router = APIRouter(prefix="/api/queries", tags=["queries"])


@router.post("", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def submit_query(
    payload: QueryCreateRequest,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Submits a natural language question against an authorized dataset.
    Runs initial deterministic safety checks, LangGraph classification, and
    executes clear queries through read-only SQL generation and execution.
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


@router.post("/{query_id}/execute", response_model=QueryResponse)
def execute_query(
    query_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Explicitly triggers canonical SQL generation, validation, and read-only execution
    for a query in 'ready_for_sql' state. Prevents duplicate concurrent executions.
    """
    return execute_ready_query(
        db=db,
        owner_id=owner_id,
        query_id=query_id,
    )



@router.get("", response_model=QueryHistoryListResponse)
def list_queries(
    dataset_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Lists paginated query history for the authenticated user.
    Supports filtering by dataset_id, status, category, and text search.
    """
    return list_authorized_queries(
        db=db,
        owner_id=owner_id,
        dataset_id=dataset_id,
        status_filter=status,
        category_filter=category,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/{query_id}", response_model=QueryResponse)
def get_query(
    query_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieves the query details, status, conversation turns, SQL, explanation, and results.
    """
    return get_query_status(
        db=db,
        owner_id=owner_id,
        query_id=query_id,
    )


@router.get("/{query_id}/export")
def export_query_results(
    query_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Exports completed query results as an RFC 4180 CSV file with
    protection against spreadsheet formula injection attacks.
    """
    query_data = get_query_status(db=db, owner_id=owner_id, query_id=query_id)
    if query_data.status != "completed" or not query_data.columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "NO_RESULTS_TO_EXPORT", "message": "Query has no completed results to export."}
        )

    csv_content = export_rows_to_safe_csv(
        columns=query_data.columns,
        rows=query_data.rows or [],
    )

    filename = f"query_{str(query_id)[:8]}_results.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
