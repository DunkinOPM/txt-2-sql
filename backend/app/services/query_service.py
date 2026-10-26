import uuid
from typing import Optional, List, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.metadata import AppDataset, AppDatasetColumn, AppQuery, AppQueryTurn
from app.schemas.query import (
    QueryResponse,
    QueryTurnResponse,
    ClarificationAnswerRequest,
)
from app.workflows.state import QueryWorkflowState
from app.workflows.graph import query_graph
from app.services.llm_service import rewrite_query_with_gemini

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


def _build_schema_summary(db: Session, dataset_id: uuid.UUID) -> list[dict[str, Any]]:
    """
    Builds minimal column summary for LLM grounding.
    Excludes internal physical column names and uploaded rows.
    """
    columns = (
        db.query(AppDatasetColumn)
        .filter(AppDatasetColumn.dataset_id == dataset_id)
        .order_by(AppDatasetColumn.ordinal_position.asc())
        .all()
    )
    return [
        {
            "original_name": c.original_name,
            "inferred_type": c.inferred_type,
            "nullable": c.nullable,
            "sample_values": c.sample_values,
        }
        for c in columns
    ]


def create_and_classify_query(
    db: Session,
    owner_id: str,
    dataset_id: uuid.UUID,
    question: str,
) -> QueryResponse:
    """
    Creates a new query record, runs initial classification through LangGraph,
    persists conversational turns, and returns the current state.
    """
    clean_question = question.strip()
    if not clean_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "EMPTY_QUESTION", "message": "Question cannot be empty."}
        )

    # 1. Authorize dataset
    dataset = _fetch_authorized_dataset(db, dataset_id, owner_id)
    schema_summary = _build_schema_summary(db, dataset_id)

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

    # 3. Invoke LangGraph workflow
    initial_state: QueryWorkflowState = {
        "query_id": str(query_id),
        "dataset_id": str(dataset_id),
        "owner_id": owner_id,
        "dataset_name": dataset.display_name,
        "schema_summary": schema_summary,
        "original_question": clean_question,
        "current_question": clean_question,
        "clarification_turns": 0,
        "previous_clarifications": [],
        "missing_fields": [],
        "ambiguities": [],
    }

    try:
        final_state = query_graph.invoke(initial_state)
    except Exception as e:
        query_record.status = "failed"
        query_record.error_code = "CLASSIFICATION_FAILED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "CLASSIFICATION_FAILED", "message": f"Workflow failed: {str(e)}"}
        )

    # 4. Update query state & record Turn 2: assistant response
    query_record.category = final_state.get("category")
    query_record.status = final_state.get("status", "failed")
    assistant_msg = final_state.get("assistant_message", "")

    turn_type = "clarification" if query_record.status == "awaiting_clarification" else "explanation"
    turn_options = final_state.get("clarification_options") if query_record.status == "awaiting_clarification" else None
    turn_2 = AppQueryTurn(
        id=uuid.uuid4(),
        query_id=query_id,
        turn_number=2,
        role="assistant",
        turn_type=turn_type,
        content=assistant_msg,
        clarification_options=turn_options,
    )
    db.add(turn_2)
    db.commit()
    db.refresh(query_record)

    return _build_query_response(query_record, final_state)


def submit_clarification_answer(
    db: Session,
    owner_id: str,
    query_id: uuid.UUID,
    req: ClarificationAnswerRequest,
) -> QueryResponse:
    """
    Submits a clarification response, rewrites the question, re-classifies the query,
    enforces loop bounds (max 3), and records conversational turns.
    Uses database row-level locking (with_for_update) to prevent race conditions
    or duplicate turns from concurrent submissions.
    """
    # 1. Fetch query with exclusive row lock
    query_record = _fetch_authorized_query(db, query_id, owner_id, for_update=True)

    # 2. Verify query is still awaiting clarification
    if query_record.status != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_QUERY_STATE",
                "message": f"Query is in '{query_record.status}' state and is not awaiting clarification."
            }
        )

    dataset = _fetch_authorized_dataset(db, query_record.dataset_id, owner_id)
    schema_summary = _build_schema_summary(db, query_record.dataset_id)

    # Fetch existing turns to track cycle count
    existing_turns = (
        db.query(AppQueryTurn)
        .filter(AppQueryTurn.query_id == query_id)
        .order_by(AppQueryTurn.turn_number.asc())
        .all()
    )

    prior_answers = [t for t in existing_turns if t.turn_type == "clarification_answer"]
    current_cycle = len(prior_answers) + 1

    # Format user answer
    opt = (req.selected_option or "").strip()
    free = (req.free_text_answer or "").strip()
    user_answer = f"{opt}: {free}" if opt and free else (opt or free)

    # Record User Turn
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

    # Check loop bound limit
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
        # Rewrite query incorporating user clarification
        base_q = query_record.refined_question or query_record.original_question
        refined_q = rewrite_query_with_gemini(base_q, last_clarification, user_answer)
        query_record.refined_question = refined_q

        # Gather history of previous clarifications for prompt grounding
        prev_clarifications = [
            {"question": last_clarification, "answer": user_answer}
        ]

        # Re-classify refined query
        state: QueryWorkflowState = {
            "query_id": str(query_id),
            "dataset_id": str(query_record.dataset_id),
            "owner_id": owner_id,
            "dataset_name": dataset.display_name,
            "schema_summary": schema_summary,
            "original_question": query_record.original_question,
            "refined_question": refined_q,
            "current_question": refined_q,
            "clarification_turns": current_cycle,
            "previous_clarifications": prev_clarifications,
            "missing_fields": [],
            "ambiguities": [],
        }

        final_state = query_graph.invoke(state)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "CLARIFICATION_PROCESSING_FAILED", "message": f"Clarification processing failed: {str(e)}"}
        )

    query_record.category = final_state.get("category")
    query_record.status = final_state.get("status", "failed")
    assistant_msg = final_state.get("assistant_message", "")

    turn_type = "clarification" if query_record.status == "awaiting_clarification" else "explanation"
    turn_options = final_state.get("clarification_options") if query_record.status == "awaiting_clarification" else None
    assistant_turn = AppQueryTurn(
        id=uuid.uuid4(),
        query_id=query_id,
        turn_number=next_turn_no + 1,
        role="assistant",
        turn_type=turn_type,
        content=assistant_msg,
        clarification_options=turn_options,
    )
    db.add(assistant_turn)
    db.commit()
    db.refresh(query_record)

    return _build_query_response(query_record, final_state)


def get_query_status(db: Session, owner_id: str, query_id: uuid.UUID) -> QueryResponse:
    """Retrieves an authorized query along with its full turn history."""
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
        turns=turns,
        created_at=query_record.created_at,
        updated_at=query_record.updated_at,
        error_code=query_record.error_code,
        error_message=getattr(query_record, "error_message", None),
    )
