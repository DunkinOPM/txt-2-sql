import io
import uuid
from typing import Tuple, List, Dict, Any
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal
from app.models.metadata import AppDatasetTable
from app.schemas.classification import ClassificationResult, ClassificationCategory
from app.services import llm_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_mock_handlers():
    """Ensure mock handlers are cleared after each test."""
    yield
    llm_service.set_mock_classifier(None)
    llm_service.set_mock_rewriter(None)
    llm_service.set_mock_sql_generator(None)
    llm_service.set_mock_sql_repairer(None)
    llm_service.set_mock_explanation(None)
    llm_service.set_mock_suggested_questions(None)


def create_test_dataset(user_id: str, filename: str = "students.csv") -> Tuple[str, str]:
    """Helper to upload a test dataset fixture and return (dataset_id, table_name)."""
    csv_data = (
        "Student Name, Department , CGPA , Enrollment Year\n"
        "Alice Smith, Computer Science, 3.85, 2022\n"
        "Bob Jones, Mathematics, 3.40, 2021\n"
        "Charlie Brown, Computer Science, 3.90, 2023\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": (filename, io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
        headers={"X-User-ID": user_id},
    )
    assert res.status_code == 201, res.text
    dataset_id = res.json()["id"]

    db = SessionLocal()
    try:
        table_rec = db.query(AppDatasetTable).filter(AppDatasetTable.dataset_id == uuid.UUID(dataset_id)).first()
        assert table_rec is not None
        table_name = table_rec.table_name
    finally:
        db.close()

    return dataset_id, table_name


# =============================================================================
# 1. Ownership Isolation Tests
# =============================================================================

def test_query_history_strict_ownership_isolation():
    """
    Verifies that User A and User B query histories are completely isolated.
    User A cannot see queries created by User B, and vice versa.
    """
    user_a = f"user_history_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_history_b_{uuid.uuid4().hex[:6]}"

    ds_a, tbl_a = create_test_dataset(user_a, "dataset_a.csv")
    ds_b, tbl_b = create_test_dataset(user_b, "dataset_b.csv")

    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.98,
        reason="Clear question.",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT student_name FROM uploaded_data.{tbl_a} LIMIT 10'
    ))

    # User A creates 2 queries
    res_a1 = client.post(
        "/api/queries",
        json={"dataset_id": ds_a, "question": "Show all students for user A"},
        headers={"X-User-ID": user_a},
    )
    assert res_a1.status_code == 201
    q_a1_id = res_a1.json()["id"]

    res_a2 = client.post(
        "/api/queries",
        json={"dataset_id": ds_a, "question": "Count students for user A"},
        headers={"X-User-ID": user_a},
    )
    assert res_a2.status_code == 201
    q_a2_id = res_a2.json()["id"]

    # User B creates 1 query
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT student_name FROM uploaded_data.{tbl_b} LIMIT 10'
    ))
    res_b1 = client.post(
        "/api/queries",
        json={"dataset_id": ds_b, "question": "Show all students for user B"},
        headers={"X-User-ID": user_b},
    )
    assert res_b1.status_code == 201
    q_b1_id = res_b1.json()["id"]

    # Request history as User A
    history_a = client.get("/api/queries", headers={"X-User-ID": user_a})
    assert history_a.status_code == 200
    data_a = history_a.json()
    assert data_a["total"] == 2
    ids_a = [item["id"] for item in data_a["items"]]
    assert q_a1_id in ids_a
    assert q_a2_id in ids_a
    assert q_b1_id not in ids_a

    # Request history as User B
    history_b = client.get("/api/queries", headers={"X-User-ID": user_b})
    assert history_b.status_code == 200
    data_b = history_b.json()
    assert data_b["total"] == 1
    ids_b = [item["id"] for item in data_b["items"]]
    assert q_b1_id in ids_b
    assert q_a1_id not in ids_b
    assert q_a2_id not in ids_b


def test_cross_user_dataset_filter_returns_404():
    """
    Verifies that filtering queries by another user's dataset_id returns 404 DATASET_NOT_FOUND.
    """
    user_a = f"user_filter_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_filter_b_{uuid.uuid4().hex[:6]}"

    ds_a, _ = create_test_dataset(user_a)
    ds_b, _ = create_test_dataset(user_b)

    # User A filters by User B's dataset
    res = client.get(f"/api/queries?dataset_id={ds_b}", headers={"X-User-ID": user_a})
    assert res.status_code == 404
    body = res.json()
    assert body.get("error_code") == "DATASET_NOT_FOUND"

    # User A filters by non-existent dataset UUID
    res_fake = client.get(f"/api/queries?dataset_id={uuid.uuid4()}", headers={"X-User-ID": user_a})
    assert res_fake.status_code == 404
    assert res_fake.json().get("error_code") == "DATASET_NOT_FOUND"


# =============================================================================
# 2. Filter Validation (Status & Category)
# =============================================================================

def test_invalid_status_filter_returns_400():
    user = f"user_filt_val_{uuid.uuid4().hex[:6]}"
    res = client.get("/api/queries?status=super_invalid_status", headers={"X-User-ID": user})
    assert res.status_code == 400
    body = res.json()
    assert body["error_code"] == "INVALID_STATUS_FILTER"


def test_invalid_category_filter_returns_400():
    user = f"user_cat_val_{uuid.uuid4().hex[:6]}"
    res = client.get("/api/queries?category=NON_EXISTENT_CAT", headers={"X-User-ID": user})
    assert res.status_code == 400
    body = res.json()
    assert body["error_code"] == "INVALID_CATEGORY_FILTER"


def test_filter_by_status_and_category():
    """
    Creates multiple queries with different categories/statuses and tests filtering.
    """
    user = f"user_filter_types_{uuid.uuid4().hex[:6]}"
    ds_id, tbl = create_test_dataset(user)

    # 1. Clear query (transition to ready_for_sql, then execute to completed)
    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT student_name FROM uploaded_data.{tbl} LIMIT 5'
    ))
    llm_service.set_mock_explanation(lambda *args, **kwargs: "Retrieved student names.")

    res1 = client.post(
        "/api/queries",
        json={"dataset_id": ds_id, "question": "List student names"},
        headers={"X-User-ID": user},
    )
    assert res1.status_code == 201
    assert res1.json()["status"] == "ready_for_sql"
    q1_id = res1.json()["id"]

    exec1 = client.post(f"/api/queries/{q1_id}/execute", headers={"X-User-ID": user})
    assert exec1.status_code == 200
    assert exec1.json()["status"] == "completed"

    # 2. Ambiguous query (awaiting_clarification)
    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_AMBIGUOUS,
        confidence=0.85,
        reason="Ambiguous metric",
        missing_fields=[],
        ambiguities=["Which metric?"],
        clarification_question="Which metric do you mean?",
        clarification_options=["Option A", "Option B"],
    ))
    res2 = client.post(
        "/api/queries",
        json={"dataset_id": ds_id, "question": "Who is the best student?"},
        headers={"X-User-ID": user},
    )
    assert res2.status_code == 201
    assert res2.json()["status"] == "awaiting_clarification"

    # 3. Improper/Unsafe query (rejected)
    res3 = client.post(
        "/api/queries",
        json={"dataset_id": ds_id, "question": "DROP TABLE students;"},
        headers={"X-User-ID": user},
    )
    assert res3.status_code == 201
    assert res3.json()["status"] == "rejected"
    assert res3.json()["category"] == "IMPROPER_OR_UNSAFE"

    # Test filtering status=completed
    res_completed = client.get("/api/queries?status=completed", headers={"X-User-ID": user})
    assert res_completed.status_code == 200
    comp_items = res_completed.json()["items"]
    assert len(comp_items) == 1
    assert comp_items[0]["id"] == q1_id

    # Test filtering status=awaiting_clarification
    res_awaiting = client.get("/api/queries?status=awaiting_clarification", headers={"X-User-ID": user})
    assert res_awaiting.status_code == 200
    await_items = res_awaiting.json()["items"]
    assert len(await_items) == 1
    assert await_items[0]["id"] == res2.json()["id"]

    # Test filtering category=IMPROPER_OR_UNSAFE
    res_unsafe = client.get("/api/queries?category=IMPROPER_OR_UNSAFE", headers={"X-User-ID": user})
    assert res_unsafe.status_code == 200
    unsafe_items = res_unsafe.json()["items"]
    assert len(unsafe_items) == 1
    assert unsafe_items[0]["id"] == res3.json()["id"]


# =============================================================================
# 3. Question Text Search Tests (ILIKE)
# =============================================================================

def test_query_search_case_insensitive():
    """
    Verifies that search query matches keywords in original_question or refined_question.
    """
    user = f"user_search_{uuid.uuid4().hex[:6]}"
    ds_id, tbl = create_test_dataset(user)

    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT student_name FROM uploaded_data.{tbl} LIMIT 5'
    ))

    # Query 1
    client.post(
        "/api/queries",
        json={"dataset_id": ds_id, "question": "What is the enrollment year distribution?"},
        headers={"X-User-ID": user},
    )

    # Query 2
    client.post(
        "/api/queries",
        json={"dataset_id": ds_id, "question": "Show computer science grade averages"},
        headers={"X-User-ID": user},
    )

    # Search for "ENROLLMENT" (uppercase)
    res_search1 = client.get("/api/queries?search=ENROLLMENT", headers={"X-User-ID": user})
    assert res_search1.status_code == 200
    data1 = res_search1.json()
    assert data1["total"] == 1
    assert "enrollment" in data1["items"][0]["original_question"].lower()

    # Search for "grade"
    res_search2 = client.get("/api/queries?search=grade", headers={"X-User-ID": user})
    assert res_search2.status_code == 200
    data2 = res_search2.json()
    assert data2["total"] == 1
    assert "grade" in data2["items"][0]["original_question"].lower()

    # Search with no match
    res_search3 = client.get("/api/queries?search=NonExistentKeywordXYZ", headers={"X-User-ID": user})
    assert res_search3.status_code == 200
    data3 = res_search3.json()
    assert data3["total"] == 0
    assert len(data3["items"]) == 0


# =============================================================================
# 4. Pagination & Ordering Tests
# =============================================================================

def test_pagination_and_stable_newest_first_ordering():
    """
    Submits 5 queries and verifies pagination slices, accurate total count,
    and strict newest-first ordering.
    """
    user = f"user_page_{uuid.uuid4().hex[:6]}"
    ds_id, tbl = create_test_dataset(user)

    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT "student_name" FROM "uploaded_data"."{tbl}" LIMIT 5;',
        "Names"
    ))

    created_ids = []
    for i in range(5):
        res = client.post(
            "/api/queries",
            json={"dataset_id": ds_id, "question": f"Numbered query index {i}"},
            headers={"X-User-ID": user},
        )
        assert res.status_code == 201
        created_ids.append(res.json()["id"])

    # In newest-first order, the latest created query (index 4) should come first
    expected_order = list(reversed(created_ids))

    # Page 1: limit 2, offset 0
    p1 = client.get("/api/queries?limit=2&offset=0", headers={"X-User-ID": user}).json()
    assert p1["total"] == 5
    assert len(p1["items"]) == 2
    assert p1["items"][0]["id"] == expected_order[0]
    assert p1["items"][1]["id"] == expected_order[1]

    # Page 2: limit 2, offset 2
    p2 = client.get("/api/queries?limit=2&offset=2", headers={"X-User-ID": user}).json()
    assert p2["total"] == 5
    assert len(p2["items"]) == 2
    assert p2["items"][0]["id"] == expected_order[2]
    assert p2["items"][1]["id"] == expected_order[3]

    # Page 3: limit 2, offset 4
    p3 = client.get("/api/queries?limit=2&offset=4", headers={"X-User-ID": user}).json()
    assert p3["total"] == 5
    assert len(p3["items"]) == 1
    assert p3["items"][0]["id"] == expected_order[4]


# =============================================================================
# 5. Suggested Questions Endpoint Tests
# =============================================================================

def test_suggested_questions_grounded_in_schema():
    """
    Verifies that GET /api/datasets/{dataset_id}/suggested-questions:
    1. Returns 3-4 suggestions grounded in column names.
    2. Does not pass raw uploaded row data or physical table names to LLM generator.
    3. Handles non-owner access properly with 404.
    """
    user_owner = f"user_sugg_owner_{uuid.uuid4().hex[:6]}"
    user_intruder = f"user_sugg_intruder_{uuid.uuid4().hex[:6]}"

    ds_id, tbl = create_test_dataset(user_owner, "finance.csv")

    captured_prompt_args: List[Dict[str, Any]] = []

    def mock_suggested(dataset_name: str, cols: list[dict[str, Any]]) -> list[str]:
        captured_prompt_args.append({
            "dataset_name": dataset_name,
            "columns": cols,
        })
        return [
            f"What is the average CGPA across all departments in {dataset_name}?",
            f"Which department has the highest enrollment?",
            f"How many students enrolled in 2022?",
        ]

    llm_service.set_mock_suggested_questions(mock_suggested)

    # Intruder access should fail with 404
    res_intruder = client.get(
        f"/api/datasets/{ds_id}/suggested-questions",
        headers={"X-User-ID": user_intruder},
    )
    assert res_intruder.status_code == 404
    assert res_intruder.json().get("error_code") == "DATASET_NOT_FOUND"

    # Owner access succeeds
    res_owner = client.get(
        f"/api/datasets/{ds_id}/suggested-questions",
        headers={"X-User-ID": user_owner},
    )
    assert res_owner.status_code == 200
    data = res_owner.json()
    assert data["dataset_id"] == ds_id
    assert len(data["questions"]) == 3
    assert "average CGPA" in data["questions"][0]

    # Verify captured arguments to ensure no leaked raw row values or table name
    assert len(captured_prompt_args) == 1
    call_info = captured_prompt_args[0]
    col_names = [c["original_name"] for c in call_info["columns"]]
    assert "Student Name" in col_names
    assert "CGPA" in col_names
    for c in call_info["columns"]:
        assert "sample_values" not in c
        assert "rows" not in c
        assert tbl not in str(c)


def test_suggested_questions_heuristic_fallback():
    """
    Verifies that when no LLM key/mock is present, the deterministic heuristic fallback
    generates valid questions without failing.
    """
    user = f"user_fallback_{uuid.uuid4().hex[:6]}"
    ds_id, _ = create_test_dataset(user)

    llm_service.set_mock_suggested_questions(None)

    res = client.get(
        f"/api/datasets/{ds_id}/suggested-questions",
        headers={"X-User-ID": user},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["questions"]) >= 1
    assert any("total number of records" in q.lower() or "cgpa" in q.lower() for q in data["questions"])


# =============================================================================
# 6. Query Detail Inspection Privacy & No-Execution Invariant
# =============================================================================

def test_query_detail_read_only_and_privacy():
    """
    Verifies:
    1. GET /api/queries/{query_id} returns full conversation turns, SQL, rows.
    2. Opening/inspecting a query never triggers re-execution or status change.
    3. User B cannot inspect User A's query (returns 404 QUERY_NOT_FOUND).
    """
    user_a = f"user_detail_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_detail_b_{uuid.uuid4().hex[:6]}"

    ds_a, tbl_a = create_test_dataset(user_a)

    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f'SELECT student_name, cgpa FROM uploaded_data.{tbl_a} ORDER BY cgpa DESC LIMIT 2'
    ))
    llm_service.set_mock_explanation(lambda *args, **kwargs: "Found 2 students with top CGPA.")

    # User A creates a query
    res = client.post(
        "/api/queries",
        json={"dataset_id": ds_a, "question": "Show top 2 students by CGPA"},
        headers={"X-User-ID": user_a},
    )
    assert res.status_code == 201
    query_id = res.json()["id"]
    assert res.json()["status"] == "ready_for_sql"

    # User A executes the query
    exec_res = client.post(f"/api/queries/{query_id}/execute", headers={"X-User-ID": user_a})
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "completed"

    # User B tries to inspect User A's query -> 404
    intruder_res = client.get(
        f"/api/queries/{query_id}",
        headers={"X-User-ID": user_b},
    )
    assert intruder_res.status_code == 404
    assert intruder_res.json().get("error_code") == "QUERY_NOT_FOUND"

    # User A inspects the query multiple times (asserting read-only stability)
    for _ in range(3):
        detail_res = client.get(
            f"/api/queries/{query_id}",
            headers={"X-User-ID": user_a},
        )
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["id"] == query_id
        assert detail["status"] == "completed"
        assert detail["result_row_count"] == 2
        assert len(detail["rows"]) == 2
        assert len(detail["turns"]) >= 2
        assert detail["generated_sql"] is not None
