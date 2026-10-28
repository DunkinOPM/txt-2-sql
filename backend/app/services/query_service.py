import uuid
from typing import Optional, List, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.metadata import (
    AppDataset,
    AppDatasetTable,
    AppDatasetColumn,
    AppQuery,
    AppQueryTurn,
)
from sqlalchemy import or_
from app.schemas.query import (
    QueryResponse,
    QueryTurnResponse,
    ClarificationAnswerRequest,
    QueryHistoryItemResponse,
    QueryHistoryListResponse,
    SuggestedQuestionsResponse,
)
from app.workflows.state import QueryWorkflowState
from app.workflows.graph import query_graph, sql_execution_graph
import logging
from app.services.llm_service import (
    classify_query_with_gemini,
    rewrite_query_with_gemini,
    generate_suggested_questions_with_gemini,
)

logger = logging.getLogger(__name__)

MAX_CLARIFICATION_LIMIT = 3


def _fetch_authorized_dataset(db: Session, dataset_id: uuid.UUID, owner_id: str) -> AppDataset:
    dataset = (
        db.query(AppDataset)
        .filter(AppDataset.id == dataset_id, AppDataset.owner_id == owner_id)
        .first()
    )
    if not dataset or dataset.status == "deleting":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DATASET_NOT_FOUND", "message": "Dataset not found or access denied."}
        )
    return dataset


def _fetch_authorized_query(
    db: Session,
    query_id: uuid.UUID,
    owner_id: str,
    for_update: bool = False
) -> AppQuery:
    query = db.query(AppQuery).filter(AppQuery.id == query_id, AppQuery.owner_id == owner_id)
    if for_update:
        query = query.with_for_update()
    query_record = query.first()
    if not query_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "QUERY_NOT_FOUND", "message": "Query not found or access denied."}
        )
    return query_record


def _get_dataset_table_name(db: Session, dataset_id: uuid.UUID) -> str:
    table_rec = (
        db.query(AppDatasetTable)
        .filter(AppDatasetTable.dataset_id == dataset_id)
        .first()
    )
    if not table_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TABLE_NOT_FOUND", "message": "Registered physical table not found for dataset."}
        )
    return table_rec.table_name


def _build_schema_summary(db: Session, dataset_id: uuid.UUID) -> list[dict[str, Any]]:
    """Builds minimal column summary for classification prompting."""
    columns = (
        db.query(AppDatasetColumn)
        .filter(AppDatasetColumn.dataset_id == dataset_id)
        .order_by(AppDatasetColumn.ordinal_position.asc())
        .all()
    )
    return [
        {
            "original_name": c.original_name,
            "internal_name": c.internal_name,
            "inferred_type": c.inferred_type,
            "nullable": c.nullable,
            "sample_values": c.sample_values,
        }
        for c in columns
    ]


def _build_columns_metadata(db: Session, dataset_id: uuid.UUID) -> list[dict[str, Any]]:
    """Builds authorized column mapping for SQL generation and column allowlisting."""
    columns = (
        db.query(AppDatasetColumn)
        .filter(AppDatasetColumn.dataset_id == dataset_id)
        .order_by(AppDatasetColumn.ordinal_position.asc())
        .all()
    )
    return [
        {
            "original_name": c.original_name,
            "internal_name": c.internal_name,
            "inferred_type": c.inferred_type,
            "nullable": c.nullable,
            "sample_values": c.sample_values,
        }
        for c in columns
    ]


def _apply_final_state_to_query(
    db: Session,
    query_record: AppQuery,
    final_state: dict[str, Any],
    next_turn_no: int,
) -> None:
    """Applies workflow final state to AppQuery and persists corresponding conversational turn."""
    st = final_state.get("status", "failed")
    query_record.status = st
    query_record.category = final_state.get("category") or query_record.category

    if st == "completed":
        query_record.generated_sql = final_state.get("validated_sql")
        query_record.explanation = final_state.get("explanation")
        query_record.result_columns = final_state.get("result_columns")
        query_record.result_rows = final_state.get("result_rows")
        query_record.result_row_count = final_state.get("result_row_count")
        query_record.execution_duration_ms = final_state.get("execution_duration_ms")
        query_record.error_code = None

        turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_record.id,
            turn_number=next_turn_no,
            role="assistant",
            turn_type="explanation",
            content=final_state.get("explanation") or "Query executed successfully.",
            clarification_options=None,
        )
        db.add(turn)

    elif st == "ready_for_sql":
        turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_record.id,
            turn_number=next_turn_no,
            role="assistant",
            turn_type="explanation",
            content=final_state.get("assistant_message") or "Question is clear and ready for SQL generation.",
            clarification_options=None,
        )
        db.add(turn)

    elif st == "awaiting_clarification":
        turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_record.id,
            turn_number=next_turn_no,
            role="assistant",
            turn_type="clarification",
            content=final_state.get("assistant_message") or "Please clarify your request.",
            clarification_options=final_state.get("clarification_options"),
        )
        db.add(turn)

    elif st == "failed":
        query_record.error_code = final_state.get("error_code") or "QUERY_FAILED"
        turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_record.id,
            turn_number=next_turn_no,
            role="assistant",
            turn_type="explanation",
            content=final_state.get("assistant_message") or "Query execution failed.",
            clarification_options=None,
        )
        db.add(turn)

    else:  # rejected
        turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_record.id,
            turn_number=next_turn_no,
            role="assistant",
            turn_type="explanation",
            content=final_state.get("assistant_message") or "Query cannot be processed.",
            clarification_options=None,
        )
        db.add(turn)

    db.commit()
    db.refresh(query_record)


def create_and_classify_query(
    db: Session,
    owner_id: str,
    dataset_id: uuid.UUID,
    question: str,
) -> QueryResponse:
    """
    Creates a new query record, runs end-to-end workflow through LangGraph:
    - If clear: generates SQL, validates AST & policies, executes via readonly_user, explains results.
    - If ambiguous: halts at awaiting_clarification.
    - If out of scope/unsafe: halts at rejected.
    """
    clean_question = question.strip()
    if not clean_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "EMPTY_QUESTION", "message": "Question cannot be empty."}
        )

    # 1. Authorize dataset and retrieve table/column mapping
    dataset = _fetch_authorized_dataset(db, dataset_id, owner_id)
    table_name = _get_dataset_table_name(db, dataset_id)
    schema_summary = _build_schema_summary(db, dataset_id)
    columns_metadata = _build_columns_metadata(db, dataset_id)

    # 2. Persist initial query record
    query_id = uuid.uuid4()
    query_record = AppQuery(
        id=query_id,
        dataset_id=dataset_id,
        owner_id=owner_id,
        original_question=clean_question,
        refined_question=None,
        category=None,
        status="classifying",
    )
    db.add(query_record)

    # Record Turn 1: user question
    turn_1 = AppQueryTurn(
        id=uuid.uuid4(),
        query_id=query_id,
        turn_number=1,
        role="user",
        turn_type="question",
        content=clean_question,
    )
    db.add(turn_1)
    db.commit()

    # 3. Prepare initial state for LangGraph workflow
    initial_state: QueryWorkflowState = {
        "query_id": str(query_id),
        "dataset_id": str(dataset_id),
        "owner_id": owner_id,
        "dataset_name": dataset.display_name,
        "table_name": table_name,
        "schema_summary": schema_summary,
        "columns_metadata": columns_metadata,
        "original_question": clean_question,
        "current_question": clean_question,
        "clarification_turns": 0,
        "previous_clarifications": [],
        "missing_fields": [],
        "ambiguities": [],
        "repair_attempts": 0,
    }

    try:
        final_state = query_graph.invoke(initial_state)
    except Exception as e:
        query_record.status = "failed"
        query_record.error_code = "WORKFLOW_FAILED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "WORKFLOW_FAILED", "message": "Query processing workflow failed. Please try again later."}
        )

    # 4. Apply final state and persist Turn 2
    _apply_final_state_to_query(db, query_record, final_state, next_turn_no=2)
    return _build_query_response(query_record, final_state)


def submit_clarification_answer(
    db: Session,
    owner_id: str,
    query_id: uuid.UUID,
    req: ClarificationAnswerRequest,
) -> QueryResponse:
    """
    Submits a clarification response, rewrites the question, re-classifies the query,
    enforces loop bounds (max 3), and executes through completion if resolved to clear.
    Uses row-level locking (with_for_update) to prevent concurrency races.
    """
    query_record = _fetch_authorized_query(db, query_id, owner_id, for_update=True)

    if query_record.status != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_QUERY_STATE",
                "message": f"Query is in '{query_record.status}' state and is not awaiting clarification."
            }
        )

    dataset = _fetch_authorized_dataset(db, query_record.dataset_id, owner_id)
    table_name = _get_dataset_table_name(db, query_record.dataset_id)
    schema_summary = _build_schema_summary(db, query_record.dataset_id)
    columns_metadata = _build_columns_metadata(db, query_record.dataset_id)

    # Fetch existing turns to track cycle count
    existing_turns = (
        db.query(AppQueryTurn)
        .filter(AppQueryTurn.query_id == query_id)
        .order_by(AppQueryTurn.turn_number.asc())
        .all()
    )

    prior_answers = [t for t in existing_turns if t.turn_type == "clarification_answer"]
    current_cycle = len(prior_answers) + 1

    opt = (req.selected_option or "").strip()
    free = (req.free_text_answer or "").strip()
    user_answer = f"{opt}: {free}" if opt and free else (opt or free)

    # Record User Clarification Turn
    next_turn_no = len(existing_turns) + 1
    user_turn = AppQueryTurn(
        id=uuid.uuid4(),
        query_id=query_id,
        turn_number=next_turn_no,
        role="user",
        turn_type="clarification_answer",
        content=user_answer,
    )
    db.add(user_turn)

    # Check clarification loop bounds
    if current_cycle > MAX_CLARIFICATION_LIMIT:
        query_record.status = "rejected"
        msg = (
            f"Maximum clarification attempts ({MAX_CLARIFICATION_LIMIT}) reached. "
            "Please start a new query with specific column names or filtering requirements."
        )
        assistant_turn = AppQueryTurn(
            id=uuid.uuid4(),
            query_id=query_id,
            turn_number=next_turn_no + 1,
            role="assistant",
            turn_type="explanation",
            content=msg,
        )
        db.add(assistant_turn)
        db.commit()
        db.refresh(query_record)
        return _build_query_response(query_record, {"assistant_message": msg})

    # Retrieve last clarification question
    last_clarification = next(
        (t.content for t in reversed(existing_turns) if t.turn_type == "clarification"),
        ""
    )

    try:
        base_q = query_record.refined_question or query_record.original_question
        refined_q = rewrite_query_with_gemini(base_q, last_clarification, user_answer)
        query_record.refined_question = refined_q

        prev_clarifications = [
            {"question": last_clarification, "answer": user_answer}
        ]

        state: QueryWorkflowState = {
            "query_id": str(query_id),
            "dataset_id": str(query_record.dataset_id),
            "owner_id": owner_id,
            "dataset_name": dataset.display_name,
            "table_name": table_name,
            "schema_summary": schema_summary,
            "columns_metadata": columns_metadata,
            "original_question": query_record.original_question,
            "refined_question": refined_q,
            "current_question": refined_q,
            "clarification_turns": current_cycle,
            "previous_clarifications": prev_clarifications,
            "missing_fields": [],
            "ambiguities": [],
            "repair_attempts": 0,
        }

        final_state = query_graph.invoke(state)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "CLARIFICATION_PROCESSING_FAILED", "message": f"Clarification processing failed: {str(e)}"}
        )

    _apply_final_state_to_query(db, query_record, final_state, next_turn_no=next_turn_no + 1)
    return _build_query_response(query_record, final_state)


def execute_ready_query(
    db: Session,
    owner_id: str,
    query_id: uuid.UUID,
) -> QueryResponse:
    """
    Canonical execution service for executing queries in 'ready_for_sql' status.
    Uses row-level locking (with_for_update) to serialize executions and prevent race conditions.
    """
    query_record = _fetch_authorized_query(db, query_id, owner_id, for_update=True)

    # If already completed, return existing result without re-executing
    if query_record.status == "completed":
        return _build_query_response(query_record)

    # Detect concurrent execution in progress
    if query_record.status in ("generating_sql", "validating_sql", "executing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EXECUTION_IN_PROGRESS",
                "message": f"Query execution is currently in progress (status: {query_record.status})."
            }
        )

    if query_record.status != "ready_for_sql":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_QUERY_STATE",
                "message": f"Query is in '{query_record.status}' state and cannot be executed."
            }
        )

    dataset = _fetch_authorized_dataset(db, query_record.dataset_id, owner_id)
    table_name = _get_dataset_table_name(db, query_record.dataset_id)
    schema_summary = _build_schema_summary(db, query_record.dataset_id)
    columns_metadata = _build_columns_metadata(db, query_record.dataset_id)

    # Transition status to generating_sql atomically within the locked transaction
    query_record.status = "generating_sql"
    db.flush()

    q_text = query_record.refined_question or query_record.original_question

    # Reconstruct previous clarification turns if any
    prev_clarifs = []
    if query_record.turns:
        for i in range(len(query_record.turns) - 1):
            t1 = query_record.turns[i]
            t2 = query_record.turns[i + 1]
            if t1.turn_type == "clarification" and t2.turn_type == "clarification_answer":
                prev_clarifs.append({"question": t1.content, "answer": t2.content})

    structured_intent = None
    try:
        understanding = classify_query_with_gemini(
            dataset_name=dataset.display_name,
            schema_summary=schema_summary,
            question=q_text,
            previous_clarifications=prev_clarifs,
        )
        structured_intent = understanding.model_dump()
    except Exception as e:
        logger.warning(f"Could not derive structured_intent in execute_ready_query: {e}")

    state: QueryWorkflowState = {
        "query_id": str(query_id),
        "dataset_id": str(query_record.dataset_id),
        "owner_id": owner_id,
        "dataset_name": dataset.display_name,
        "table_name": table_name,
        "schema_summary": schema_summary,
        "columns_metadata": columns_metadata,
        "original_question": query_record.original_question,
        "refined_question": query_record.refined_question,
        "current_question": q_text,
        "category": query_record.category or "RELEVANT_CLEAR",
        "structured_intent": structured_intent,
        "repair_attempts": 0,
    }

    try:
        final_state = sql_execution_graph.invoke(state)
    except Exception as e:
        query_record.status = "failed"
        query_record.error_code = "SQL_EXECUTION_PIPELINE_FAILED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "SQL_EXECUTION_PIPELINE_FAILED", "message": "SQL execution pipeline encountered an unexpected error. Please try again later."}
        )

    next_turn_no = len(query_record.turns) + 1
    _apply_final_state_to_query(db, query_record, final_state, next_turn_no=next_turn_no)
    return _build_query_response(query_record, final_state)


def get_query_status(db: Session, owner_id: str, query_id: uuid.UUID) -> QueryResponse:
    """Retrieves an authorized query along with its full turn history, SQL, and executed results."""
    query_record = _fetch_authorized_query(db, query_id, owner_id)
    return _build_query_response(query_record)


def _build_query_response(
    query_record: AppQuery,
    final_state: Optional[dict[str, Any]] = None
) -> QueryResponse:
    turns = [
        QueryTurnResponse(
            id=t.id,
            turn_number=t.turn_number,
            role=t.role,
            turn_type=t.turn_type,
            content=t.content,
            clarification_options=t.clarification_options,
            created_at=t.created_at,
        )
        for t in query_record.turns
    ]

    last_assistant_turn = next(
        (t for t in reversed(query_record.turns) if t.role == "assistant"),
        None
    )
    assistant_message = (
        final_state.get("assistant_message")
        if final_state and "assistant_message" in final_state
        else (last_assistant_turn.content if last_assistant_turn else "")
    )

    clarification_question = None
    clarification_options = None
    if query_record.status == "awaiting_clarification":
        if final_state:
            clarification_question = final_state.get("clarification_question")
            clarification_options = final_state.get("clarification_options")
        if not clarification_question and last_assistant_turn:
            clarification_question = last_assistant_turn.content
        if not clarification_options and last_assistant_turn:
            clarification_options = getattr(last_assistant_turn, "clarification_options", None)

    # Extract execution results
    generated_sql = (
        final_state.get("validated_sql")
        if final_state and "validated_sql" in final_state
        else query_record.generated_sql
    )
    explanation = (
        final_state.get("explanation")
        if final_state and "explanation" in final_state
        else query_record.explanation
    )
    columns = (
        final_state.get("result_columns")
        if final_state and "result_columns" in final_state
        else query_record.result_columns
    )
    rows = (
        final_state.get("result_rows")
        if final_state and "result_rows" in final_state
        else query_record.result_rows
    )
    row_count = (
        final_state.get("result_row_count")
        if final_state and "result_row_count" in final_state
        else query_record.result_row_count
    )
    duration_ms = (
        final_state.get("execution_duration_ms")
        if final_state and "execution_duration_ms" in final_state
        else query_record.execution_duration_ms
    )

    error_message = None
    if query_record.status == "failed":
        if final_state and final_state.get("error_message"):
            error_message = final_state.get("error_message")
        elif last_assistant_turn:
            error_message = last_assistant_turn.content

    return QueryResponse(
        id=query_record.id,
        dataset_id=query_record.dataset_id,
        original_question=query_record.original_question,
        refined_question=query_record.refined_question,
        category=query_record.category,
        status=query_record.status,
        assistant_message=assistant_message,
        clarification_question=clarification_question,
        clarification_options=clarification_options,
        generated_sql=generated_sql,
        explanation=explanation,
        columns=columns,
        rows=rows,
        result_row_count=row_count,
        execution_duration_ms=duration_ms,
        turns=turns,
        created_at=query_record.created_at,
        updated_at=query_record.updated_at,
        error_code=query_record.error_code,
        error_message=error_message,
    )
VALID_QUERY_STATUSES = {
    "classifying",
    "awaiting_clarification",
    "ready_for_sql",
    "generating_sql",
    "validating_sql",
    "executing",
    "completed",
    "rejected",
    "failed",
}

VALID_QUERY_CATEGORIES = {
    "RELEVANT_CLEAR",
    "RELEVANT_AMBIGUOUS",
    "RELEVANT_UNANSWERABLE",
    "OUT_OF_SCOPE",
    "NONSENSICAL",
    "IMPROPER_OR_UNSAFE",
}


def list_authorized_queries(
    db: Session,
    owner_id: str,
    dataset_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> QueryHistoryListResponse:
    """
    Lists paginated query history belonging strictly to owner_id.
    Validates status and category filters.
    If dataset_id is provided, verifies user ownership of that dataset.
    Supports case-insensitive search across question text.
    Orders with stable newest-first sorting.
    """
    if status_filter is not None:
        if status_filter not in VALID_QUERY_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_STATUS_FILTER", "message": f"Invalid status filter '{status_filter}'."}
            )

    if category_filter is not None:
        if category_filter not in VALID_QUERY_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_CATEGORY_FILTER", "message": f"Invalid category filter '{category_filter}'."}
            )

    if dataset_id is not None:
        _fetch_authorized_dataset(db, dataset_id, owner_id)

    query = (
        db.query(AppQuery, AppDataset.display_name.label("dataset_name"))
        .join(AppDataset, AppQuery.dataset_id == AppDataset.id)
        .filter(AppQuery.owner_id == owner_id)
    )

    if dataset_id is not None:
        query = query.filter(AppQuery.dataset_id == dataset_id)

    if status_filter is not None:
        query = query.filter(AppQuery.status == status_filter)

    if category_filter is not None:
        query = query.filter(AppQuery.category == category_filter)

    if search:
        clean_search = search.strip()
        if clean_search:
            search_pattern = f"%{clean_search}%"
            query = query.filter(
                or_(
                    AppQuery.original_question.ilike(search_pattern),
                    AppQuery.refined_question.ilike(search_pattern),
                )
            )

    total_count = query.count()

    records = (
        query.order_by(AppQuery.created_at.desc(), AppQuery.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = [
        QueryHistoryItemResponse(
            id=q.id,
            dataset_id=q.dataset_id,
            dataset_name=d_name,
            original_question=q.original_question,
            refined_question=q.refined_question,
            category=q.category,
            status=q.status,
            result_row_count=q.result_row_count,
            execution_duration_ms=q.execution_duration_ms,
            error_code=q.error_code,
            created_at=q.created_at,
            updated_at=q.updated_at,
        )
        for q, d_name in records
    ]

    return QueryHistoryListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


def get_suggested_questions(
    db: Session,
    owner_id: str,
    dataset_id: uuid.UUID,
) -> SuggestedQuestionsResponse:
    """
    Generates suggested questions for an authorized dataset grounded ONLY in its schema.
    """
    dataset = _fetch_authorized_dataset(db, dataset_id, owner_id)
    columns_meta = _build_columns_metadata(db, dataset_id)
    minimal_cols = [
        {"original_name": c["original_name"], "inferred_type": c["inferred_type"]}
        for c in columns_meta
    ]

    questions = generate_suggested_questions_with_gemini(
        dataset_name=dataset.display_name,
        columns=minimal_cols,
    )

    return SuggestedQuestionsResponse(
        dataset_id=dataset.id,
        dataset_name=dataset.display_name,
        questions=questions,
    )
