import io
import uuid
from typing import Tuple, List, Dict, Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.database import SessionLocal, readonly_engine
from app.models.metadata import AppDatasetTable
from app.schemas.classification import ClassificationResult, ClassificationCategory
from app.services import llm_service
from app.services.sql_validator import validate_sql_query, SqlValidationError
from app.services.sql_semantic_validator import (
    validate_sql_semantics,
    generate_semantic_sql,
    repair_semantic_sql,
    extract_query_intent,
)
from app.services.query_execution_service import execute_readonly_sql

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_cleanup_mock_handlers():
    """Ensure mock classifier defaults to RELEVANT_CLEAR and is cleaned up after each test."""
    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question for semantic test",
        missing_fields=[],
        ambiguities=[],
    ))
    yield
    llm_service.set_mock_classifier(None)
    llm_service.set_mock_rewriter(None)
    llm_service.set_mock_sql_generator(None)
    llm_service.set_mock_sql_repairer(None)
    llm_service.set_mock_explanation(None)


def create_students_dataset(user_id: str) -> Tuple[str, str]:
    """
    Creates a rich student dataset fixture where:
    - Column 0 is StudentID (BIGINT)
    - Column 1 is Student Name (TEXT)
    - Column 2 is Age (BIGINT)
    - Column 3 is Department (TEXT)
    - Column 4 is Marks (BIGINT)
    This fixture explicitly reproduces the exact schema structure of the bug report.
    """
    csv_data = (
        "StudentID,Student Name,Age,Department,Marks\n"
        "101,Alice Smith,20,Computer Science,85\n"
        "102,Bob Jones,22,Mathematics,78\n"
        "103,Charlie Brown,21,Computer Science,92\n"
        "104,Diana Prince,23,Physics,88\n"
        "105,Ethan Hunt,24,Mathematics,95\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("students_performance.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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
# 1. Primary Bug Verification: "What is the average Age?"
# =============================================================================

def test_average_age_scenario_resolves_avg_not_first_column():
    """
    Verifies fix for observed bug:
    "What is the average Age?" MUST NOT generate 'SELECT studentid ... LIMIT 10'.
    It MUST generate an AVG(age) aggregation, pass semantic validation, and execute to completion.
    """
    user_id = f"test_avg_bug_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        # Step 1: Submit query "What is the average Age?"
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the average Age?"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        q_data = res.json()
        assert q_data["category"] == "RELEVANT_CLEAR"
        assert q_data["status"] == "ready_for_sql"
        query_id = q_data["id"]

        # Step 2: Execute query
        exec_res = client.post(f"/api/queries/{query_id}/execute", headers={"X-User-ID": user_id})
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        generated_sql = exec_data["generated_sql"]
        assert generated_sql is not None

        # Verify semantic assertions on generated SQL
        assert "AVG" in generated_sql.upper()
        assert "age" in generated_sql.lower()
        # Ensure it NEVER falls back to selecting only the first column (studentid) with LIMIT 10
        assert "limit 10" not in generated_sql.lower()

        # Verify executed results: (20 + 22 + 21 + 23 + 24) / 5 = 110 / 5 = 22.0
        assert exec_data["result_row_count"] == 1
        first_row = exec_data["rows"][0]
        avg_val = float(list(first_row.values())[0])
        assert avg_val == pytest.approx(22.0, abs=0.01)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 2. Semantic Aggregations: SUM, MIN, MAX, COUNT
# =============================================================================

def test_semantic_aggregations_sum_min_max_count():
    """
    Tests that SUM, MIN, MAX, and COUNT questions produce semantically correct SQL and results.
    """
    user_id = f"test_aggs_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    test_cases = [
        # (question, expected_func, expected_col, expected_val)
        ("What is the total Marks?", "SUM", "marks", 85 + 78 + 92 + 88 + 95),  # 438
        ("What is the minimum Age?", "MIN", "age", 20),
        ("What is the maximum Marks?", "MAX", "marks", 95),
        ("How many students are enrolled?", "COUNT", None, 5),
    ]

    try:
        for question, func, col, expected_val in test_cases:
            res = client.post(
                "/api/queries",
                json={"dataset_id": dataset_id, "question": question},
                headers={"X-User-ID": user_id},
            )
            assert res.status_code == 201, f"Failed on {question}: {res.text}"
            qid = res.json()["id"]

            exec_res = client.post(f"/api/queries/{qid}/execute", headers={"X-User-ID": user_id})
            assert exec_res.status_code == 200, f"Execution failed on {question}: {exec_res.text}"
            exec_data = exec_res.json()

            assert exec_data["status"] == "completed", f"Status not completed for {question}: {exec_data}"
            sql = exec_data["generated_sql"]
            assert func in sql.upper(), f"Expected {func} in {sql}"
            if col:
                assert col in sql.lower(), f"Expected {col} in {sql}"

            assert exec_data["result_row_count"] == 1
            first_row = exec_data["rows"][0]
            result_val = float(list(first_row.values())[0])
            assert result_val == pytest.approx(float(expected_val), abs=0.01)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 3. Filtering: Numeric and String Filters
# =============================================================================

def test_semantic_filters_numeric_and_string():
    """
    Verifies that numeric filter phrases (older than 21) and string filters
    (in Physics department) generate correct WHERE clauses and return expected row counts.
    """
    user_id = f"test_filters_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        # Numeric filter: older than 21 -> Bob(22), Diana(23), Ethan(24) -> 3 students
        res1 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show students older than 21"},
            headers={"X-User-ID": user_id},
        )
        assert res1.status_code == 201
        exec1 = client.post(f"/api/queries/{res1.json()['id']}/execute", headers={"X-User-ID": user_id})
        assert exec1.status_code == 200
        data1 = exec1.json()
        assert data1["status"] == "completed"
        assert "WHERE" in data1["generated_sql"].upper()
        assert "age" in data1["generated_sql"].lower()
        assert data1["result_row_count"] == 3

        # String filter: in Physics department -> Diana Prince -> 1 student
        res2 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show students in Physics department"},
            headers={"X-User-ID": user_id},
        )
        assert res2.status_code == 201
        exec2 = client.post(f"/api/queries/{res2.json()['id']}/execute", headers={"X-User-ID": user_id})
        assert exec2.status_code == 200
        data2 = exec2.json()
        assert data2["status"] == "completed"
        assert "WHERE" in data2["generated_sql"].upper()
        assert "department" in data2["generated_sql"].lower()
        assert data2["result_row_count"] == 1
        assert any("Diana Prince" in str(v) for row in data2["rows"] for v in row.values())

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 4. Sorting, Limits, and Grouping
# =============================================================================

def test_semantic_sorting_limit_and_group_by():
    """
    Verifies:
    1. Top N sorting generates ORDER BY ... DESC LIMIT N.
    2. Group By aggregation generates GROUP BY ... with aggregate function.
    """
    user_id = f"test_sort_group_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        # Top 2 students sorted by marks -> Ethan(95), Charlie(92)
        res_top = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Top 2 students sorted by marks"},
            headers={"X-User-ID": user_id},
        )
        assert res_top.status_code == 201
        exec_top = client.post(f"/api/queries/{res_top.json()['id']}/execute", headers={"X-User-ID": user_id})
        assert exec_top.status_code == 200
        data_top = exec_top.json()
        assert data_top["status"] == "completed"
        assert "ORDER BY" in data_top["generated_sql"].upper()
        assert "LIMIT 2" in data_top["generated_sql"].upper()
        assert data_top["result_row_count"] == 2

        # Average marks by department -> 3 departments (Computer Science, Mathematics, Physics)
        res_grp = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Average marks by department"},
            headers={"X-User-ID": user_id},
        )
        assert res_grp.status_code == 201
        exec_grp = client.post(f"/api/queries/{res_grp.json()['id']}/execute", headers={"X-User-ID": user_id})
        assert exec_grp.status_code == 200
        data_grp = exec_grp.json()
        assert data_grp["status"] == "completed"
        assert "GROUP BY" in data_grp["generated_sql"].upper()
        assert "AVG" in data_grp["generated_sql"].upper()
        assert data_grp["result_row_count"] == 3

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 5. Missing Column and Incompatible Type Refusals
# =============================================================================

def test_semantic_missing_column_and_incompatible_type_rejection():
    """
    Verifies that requests referencing absent columns or requesting invalid aggregations
    (e.g., AVG on TEXT) are refused with clear error codes prior to SQL execution.
    """
    user_id = f"test_refusals_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        # 1. Missing column validation in generate_semantic_sql
        cols_meta = [
            {"original_name": "StudentID", "internal_name": "studentid", "inferred_type": "BIGINT"},
            {"original_name": "Student Name", "internal_name": "student_name", "inferred_type": "TEXT"},
            {"original_name": "Age", "internal_name": "age", "inferred_type": "BIGINT"},
        ]
        with pytest.raises(SqlValidationError) as exc_m:
            generate_semantic_sql("What is the average salary?", table_name, cols_meta, "Students")
        assert exc_m.value.error_code == "MISSING_REQUESTED_COLUMN"
        assert "salary" in exc_m.value.message.lower()

        # 2. Incompatible column type validation in generate_semantic_sql (AVG on Student Name)
        with pytest.raises(SqlValidationError) as exc_i:
            generate_semantic_sql("What is the average student name?", table_name, cols_meta, "Students")
        assert exc_i.value.error_code == "INCOMPATIBLE_COLUMN_TYPE"
        assert "TEXT" in exc_i.value.message

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 6. Semantic Repair Preserves Original Intent
# =============================================================================

def test_semantic_repair_preserves_original_intent():
    """
    Verifies that when initial SQL generation violates semantics (e.g., forgets AVG(age)),
    the repair loop feeds the semantic failure into the repair prompt and fixes the query
    without losing the user's intended operation.
    """
    user_id = f"test_repair_intent_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    # Initial generator produces an incorrect non-aggregating query
    faulty_sql = f"SELECT student_name FROM uploaded_data.{table_name} LIMIT 1"
    # Repaired generator produces the semantically correct AVG query
    fixed_sql = f"SELECT AVG(age) AS avg_age FROM uploaded_data.{table_name}"

    try:
        llm_service.set_mock_classifier(lambda *args: ClassificationResult(
            category=ClassificationCategory.RELEVANT_CLEAR,
            confidence=0.98,
            reason="Clear average request",
            missing_fields=[],
            ambiguities=[],
        ))
        llm_service.set_mock_sql_generator(lambda *args: faulty_sql)
        llm_service.set_mock_sql_repairer(lambda *args: fixed_sql)

        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the average Age?"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201
        qid = res.json()["id"]

        exec_res = client.post(f"/api/queries/{qid}/execute", headers={"X-User-ID": user_id})
        assert exec_res.status_code == 200
        data = exec_res.json()

        assert data["status"] == "completed"
        assert "AVG(age)" in data["generated_sql"] or "avg(age)" in data["generated_sql"].lower()
        first_row = data["rows"][0]
        assert float(list(first_row.values())[0]) == pytest.approx(22.0)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 7. AST & Semantic Validator Unit Tests
# =============================================================================

def test_semantic_validator_unit_checks():
    """
    Direct unit tests on validate_sql_semantics to verify all validation constraints:
    - Intent mismatch for aggregation (AVG requested, query lacks AVG)
    - Intent mismatch for column reference (age requested, query references marks)
    - Group by mismatch
    - Limit mismatch
    - SQL injection and mutation rejection
    """
    columns_meta = [
        {"original_name": "StudentID", "internal_name": "studentid", "inferred_type": "BIGINT"},
        {"original_name": "Student Name", "internal_name": "student_name", "inferred_type": "TEXT"},
        {"original_name": "Age", "internal_name": "age", "inferred_type": "BIGINT"},
        {"original_name": "Department", "internal_name": "department", "inferred_type": "TEXT"},
        {"original_name": "Marks", "internal_name": "marks", "inferred_type": "BIGINT"},
    ]
    tbl = "dataset_test123"

    # 1. Missing AVG when average requested
    bad_query = f"SELECT studentid FROM uploaded_data.{tbl} LIMIT 10"
    with pytest.raises(SqlValidationError) as exc:
        validate_sql_semantics(bad_query, "What is the average Age?", tbl, columns_meta)
    assert exc.value.error_code == "INTENT_MISMATCH_AGGREGATION"

    # 2. Applying AVG to wrong column (marks instead of age)
    wrong_col_query = f"SELECT AVG(marks) FROM uploaded_data.{tbl}"
    with pytest.raises(SqlValidationError) as exc:
        validate_sql_semantics(wrong_col_query, "What is the average Age?", tbl, columns_meta)
    assert exc.value.error_code == "INTENT_MISMATCH_COLUMN"

    # 3. Missing GROUP BY when grouped aggregation requested
    no_grp_query = f"SELECT department, AVG(marks) FROM uploaded_data.{tbl}"
    with pytest.raises(SqlValidationError) as exc:
        validate_sql_semantics(no_grp_query, "Average marks by department", tbl, columns_meta)
    assert exc.value.error_code == "INTENT_MISMATCH_GROUPING"

    # 4. Valid semantic query passes
    valid_query = f"SELECT AVG(age) AS avg_age FROM uploaded_data.{tbl}"
    # Should not raise
    validate_sql_semantics(valid_query, "What is the average Age?", tbl, columns_meta)

    # 5. Injection rejection in validate_sql_query
    injection = f"SELECT AVG(age) FROM uploaded_data.{tbl}; DROP TABLE app.app_queries;"
    with pytest.raises(SqlValidationError):
        validate_sql_query(injection, tbl, {c["internal_name"] for c in columns_meta})


# =============================================================================
# 8. Safe Common Table Expressions (CTEs)
# =============================================================================

def test_safe_cte_execution():
    """
    Verifies that safe, read-only CTEs with analytical functions execute cleanly and accurately.
    """
    user_id = f"test_cte_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    cte_sql = (
        f"WITH top_students AS ("
        f"  SELECT student_name, marks FROM uploaded_data.{table_name} WHERE marks >= 90"
        f") "
        f"SELECT student_name, marks FROM top_students ORDER BY marks DESC"
    )

    try:
        # Validate AST
        allowed_cols = {"studentid", "student_name", "age", "department", "marks"}
        norm_sql = validate_sql_query(cte_sql, table_name, allowed_cols)

        # Execute read-only SQL
        cols, rows, count, dur = execute_readonly_sql(norm_sql)
        assert count == 2  # Charlie Brown (92), Ethan Hunt (95)
        assert rows[0]["student_name"] == "Ethan Hunt"
        assert rows[1]["student_name"] == "Charlie Brown"

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

# =============================================================================
# 9. Regression Suite: Ambiguity Handling & Schema-Grounded Classification
# =============================================================================

def create_evaluative_test_dataset(user_id: str) -> Tuple[str, str]:
    """
    Creates a student dataset fixture with multiple candidate metrics:
    - StudentID (BIGINT)
    - Student Name (TEXT)
    - GPA (NUMERIC)
    - Exam Marks (BIGINT)
    - Attendance (BIGINT)
    """
    csv_data = (
        "StudentID,Student Name,GPA,Exam Marks,Attendance\n"
        "101,Alice Smith,3.85,85,90\n"
        "102,Bob Jones,3.40,95,70\n"
        "103,Charlie Brown,3.90,88,85\n"
        "104,Diana Prince,3.60,92,65\n"
        "105,Ethan Hunt,3.95,78,95\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("students_evaluative.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def create_non_metric_test_dataset(user_id: str) -> Tuple[str, str]:
    """
    Creates a student dataset fixture with NO performance metrics:
    - StudentID (BIGINT)
    - Student Name (TEXT)
    - Department (TEXT)
    """
    csv_data = (
        "StudentID,Student Name,Department\n"
        "101,Alice Smith,Computer Science\n"
        "102,Bob Jones,Mathematics\n"
        "103,Charlie Brown,Physics\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("students_no_metrics.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def test_ambiguity_top_performing_student_requires_clarification():
    """
    Scenario 1:
    "Give me the student ID of the top-performing student"
    When multiple performance metrics exist (GPA, Exam Marks, Attendance),
    the workflow MUST pause in awaiting_clarification, ask a targeted question
    with options, and NEVER generate or execute arbitrary SQL.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_ambig_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "give me the student id of top performing student"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_AMBIGUOUS"
        assert data["status"] == "awaiting_clarification"
        assert data["clarification_question"] is not None
        assert any(w in data["clarification_question"].lower() for w in ("metric", "determine", "define", "measure", "rank", "criteria"))
        assert data["clarification_options"] is not None
        assert len(data["clarification_options"]) >= 2
        # Check that options are grounded in schema
        for opt in data["clarification_options"]:
            assert opt in ("GPA", "Exam Marks", "Attendance")

        # Guarantee no SQL was executed or returned
        assert data["generated_sql"] is None
        assert data["rows"] is None
        assert data["columns"] is None

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

def test_clear_highest_gpa_query_proceeds_to_sql():
    """
    Scenario 2:
    "Give me the student ID of the student with the highest GPA"
    Clear if compatible GPA column exists in the schema.
    Must classify as RELEVANT_CLEAR, transition to ready_for_sql,
    and execute to completion returning the correct student ID.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_clear_gpa_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Give me the student ID of the student with the highest GPA"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_CLEAR"
        assert data["status"] == "ready_for_sql"
        query_id = data["id"]

        # Execute
        exec_res = client.post(
            f"/api/queries/{query_id}/execute",
            headers={"X-User-ID": user_id},
        )
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        assert exec_data["generated_sql"] is not None
        sql = exec_data["generated_sql"].lower()
        assert "order by" in sql
        assert "gpa" in sql
        assert "desc" in sql
        assert "limit 1" in sql

        # Ethan Hunt has the highest GPA (3.95) with StudentID 105
        assert exec_data["result_row_count"] == 1
        rows = exec_data["rows"]
        assert len(rows) == 1
        assert list(rows[0].values())[0] in (105, "105")

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

def test_clear_attendance_filter_query_proceeds_to_sql():
    """
    Scenario 3:
    "Show students with attendance below 75%"
    Clear if attendance column exists.
    Must classify as RELEVANT_CLEAR, transition to ready_for_sql,
    and filter correctly on attendance < 75.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_clear_att_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show students with attendance below 75%"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_CLEAR"
        assert data["status"] == "ready_for_sql"
        query_id = data["id"]

        # Execute
        exec_res = client.post(
            f"/api/queries/{query_id}/execute",
            headers={"X-User-ID": user_id},
        )
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        sql = exec_data["generated_sql"].lower()
        assert "attendance" in sql
        assert "<" in sql
        assert "75" in sql

        # Students with attendance < 75%: Bob Jones (70), Diana Prince (65) -> 2 rows
        assert exec_data["result_row_count"] == 2
        assert len(exec_data["rows"]) == 2
        for r in exec_data["rows"]:
            att_val = r.get("attendance")
            if att_val is not None:
                assert int(att_val) < 75

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

def test_ambiguity_find_best_student_multiple_metrics():
    """
    Scenario 4:
    "Find the best student"
    Clarification required when multiple metrics are plausible in the schema.
    Must pause in awaiting_clarification and offer candidate metrics.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_best_stud_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Find the best student"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_AMBIGUOUS"
        assert data["status"] == "awaiting_clarification"
        assert data["clarification_question"] is not None
        assert data["clarification_options"] is not None
        assert len(data["clarification_options"]) >= 2
        assert data["generated_sql"] is None

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

def test_missing_metric_columns_informative_rejection_never_arbitrary_sql():
    """
    Scenario 5:
    Missing metric columns (dataset with only StudentID, Student Name, Department):
    "Give me the student ID of the top-performing student"
    Must be rejected with informative RELEVANT_UNANSWERABLE explanation,
    and NEVER execute SELECT * or return arbitrary rows.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_no_metric_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_non_metric_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Give me the student ID of the top-performing student"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_UNANSWERABLE"
        assert data["status"] == "rejected"
        msg = data["assistant_message"].lower()
        assert "performance metric" in msg or "does not contain" in msg
        assert "available" in msg

        # Strict guarantee: NEVER fallback to SELECT * or return rows
        assert data["generated_sql"] is None
        assert data["rows"] is None
        assert data["columns"] is None

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})

def test_clarification_answer_resumes_workflow_and_generates_correct_sql():
    """
    Scenario 6:
    Multi-turn clarification resolution:
    1. User asks "give me the student id of top performing student" -> halts in awaiting_clarification.
    2. User submits clarification "GPA".
    3. Workflow re-classifies as RELEVANT_CLEAR, transitions to ready_for_sql.
    4. Execution generates SELECT studentid FROM ... ORDER BY gpa DESC LIMIT 1 and returns correct row.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_clar_resolve_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        # Step 1: Initial ambiguous query
        res1 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "give me the student id of top performing student"},
            headers={"X-User-ID": user_id},
        )
        assert res1.status_code == 201, res1.text
        data1 = res1.json()
        assert data1["status"] == "awaiting_clarification"
        query_id = data1["id"]

        # Step 2: Submit clarification answer "GPA"
        res2 = client.post(
            f"/api/queries/{query_id}/clarifications",
            json={"selected_option": "GPA", "free_text_answer": None},
            headers={"X-User-ID": user_id},
        )
        assert res2.status_code == 200, res2.text
        data2 = res2.json()

        assert data2["category"] == "RELEVANT_CLEAR"
        assert data2["status"] == "ready_for_sql"
        assert data2["refined_question"] is not None
        assert "gpa" in data2["refined_question"].lower()

        # Step 3: Execute resolved query
        exec_res = client.post(
            f"/api/queries/{query_id}/execute",
            headers={"X-User-ID": user_id},
        )
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        sql = exec_data["generated_sql"].lower()
        assert "studentid" in sql
        assert "gpa" in sql
        assert "order by" in sql
        assert "desc" in sql
        assert "limit 1" in sql

        assert exec_data["result_row_count"] == 1
        rows = exec_data["rows"]
        assert len(rows) == 1
        # Ethan Hunt has highest GPA (3.95), StudentID 105
        assert list(rows[0].values())[0] in (105, "105")

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})
# =============================================================================
# 7. Cross-Schema Parameterized Regression Tests (Sales, Employees, Inventory)
# =============================================================================

def create_sales_dataset(user_id: str) -> Tuple[str, str]:
    csv_data = (
        "Order ID,Customer Name,Product Category,Units Sold,Unit Price,Discount Rate,Total Revenue\n"
        "1001,Acme Corp,Electronics,150,299.99,0.05,42748.58\n"
        "1002,Beta LLC,Furniture,45,450.00,0.10,18225.00\n"
        "1003,Gamma Inc,Electronics,300,199.99,0.00,59997.00\n"
        "1004,Delta Co,Office Supplies,500,12.50,0.15,5312.50\n"
        "1005,Epsilon Ltd,Furniture,80,620.00,0.08,45632.00\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("sales_orders.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def create_employees_dataset(user_id: str) -> Tuple[str, str]:
    csv_data = (
        "Employee ID,Full Name,Department,Monthly Salary,Performance Rating,Years at Company\n"
        "501,Alice Johnson,Engineering,8500,4.8,5\n"
        "502,Bob Smith,Marketing,6200,3.9,3\n"
        "503,Carol White,Engineering,9200,4.9,7\n"
        "504,David Lee,Sales,7100,4.2,4\n"
        "505,Emma Davis,Marketing,6800,4.5,6\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("employees_hr.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def create_inventory_dataset(user_id: str) -> Tuple[str, str]:
    csv_data = (
        "SKU,Item Name,Warehouse Location,Quantity on Hand,Unit Cost\n"
        "SKU-001,Widget A,North,120,15.50\n"
        "SKU-002,Widget B,South,15,45.00\n"
        "SKU-003,Gadget X,East,8,95.00\n"
        "SKU-004,Gadget Y,North,250,5.25\n"
        "SKU-005,Tool Z,West,18,65.00\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("warehouse_inventory.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def test_sales_schema_average_aggregation_and_top_n():
    """Verifies that sales schema queries correctly generate AVG, ORDER BY, and LIMIT operations."""
    user_id = f"test_sales_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_sales_dataset(user_id)

    try:
        # Query 1: "What is the average Total Revenue?"
        res1 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the average Total Revenue?"},
            headers={"X-User-ID": user_id},
        )
        assert res1.status_code == 201, res1.text
        data1 = res1.json()
        assert data1["status"] == "ready_for_sql"
        q1_id = data1["id"]

        exec1 = client.post(f"/api/queries/{q1_id}/execute", headers={"X-User-ID": user_id})
        assert exec1.status_code == 200, exec1.text
        exec1_data = exec1.json()
        assert exec1_data["status"] == "completed"
        sql1 = exec1_data["generated_sql"].lower()
        assert "avg" in sql1
        assert "total_revenue" in sql1
        assert exec1_data["result_row_count"] == 1

        # Query 2: "Top 3 orders by Total Revenue"
        res2 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Top 3 orders by Total Revenue"},
            headers={"X-User-ID": user_id},
        )
        assert res2.status_code == 201, res2.text
        data2 = res2.json()
        assert data2["status"] == "ready_for_sql"
        q2_id = data2["id"]

        exec2 = client.post(f"/api/queries/{q2_id}/execute", headers={"X-User-ID": user_id})
        assert exec2.status_code == 200, exec2.text
        exec2_data = exec2.json()
        assert exec2_data["status"] == "completed"
        sql2 = exec2_data["generated_sql"].lower()
        assert "order by" in sql2
        assert "total_revenue" in sql2
        assert "desc" in sql2
        assert "limit 3" in sql2
        assert exec2_data["result_row_count"] == 3

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_sales_schema_ambiguity_detection_and_options():
    """Verifies that 'top performing order' in sales domain is flagged ambiguous with sales metrics."""
    llm_service.set_mock_classifier(None)
    user_id = f"test_sales_ambig_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_sales_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Give me the top performing order"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["category"] == "RELEVANT_AMBIGUOUS"
        assert data["status"] == "awaiting_clarification"
        assert data["generated_sql"] is None
        # Candidate metrics in sales schema: Units Sold, Unit Price, Total Revenue, Discount Rate
        # Order ID is an identifier and should NOT be suggested
        options = data["clarification_options"]
        assert options is not None and len(options) >= 2
        assert any("revenue" in opt.lower() or "units" in opt.lower() for opt in options)
        assert not any("order id" == opt.lower() for opt in options)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_employees_schema_average_and_ambiguity():
    """Verifies HR schema correctly computes averages and detects ambiguity for 'best employee'."""
    llm_service.set_mock_classifier(None)
    user_id = f"test_emp_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_employees_dataset(user_id)

    try:
        # Query 1: "What is the average Monthly Salary?"
        res1 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the average Monthly Salary?"},
            headers={"X-User-ID": user_id},
        )
        assert res1.status_code == 201, res1.text
        data1 = res1.json()
        assert data1["status"] == "ready_for_sql"
        q1_id = data1["id"]

        exec1 = client.post(f"/api/queries/{q1_id}/execute", headers={"X-User-ID": user_id})
        assert exec1.status_code == 200, exec1.text
        exec1_data = exec1.json()
        assert exec1_data["status"] == "completed"
        sql1 = exec1_data["generated_sql"].lower()
        assert "avg" in sql1
        assert "monthly_salary" in sql1
        assert exec1_data["result_row_count"] == 1

        # Query 2: "Find the best employee" (evaluative concept without explicit metric)
        res2 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Find the best employee"},
            headers={"X-User-ID": user_id},
        )
        assert res2.status_code == 201, res2.text
        data2 = res2.json()
        assert data2["category"] == "RELEVANT_AMBIGUOUS"
        assert data2["status"] == "awaiting_clarification"
        options2 = data2["clarification_options"]
        assert options2 is not None and len(options2) >= 2
        # Performance Rating, Monthly Salary, Years at Company should be candidate metrics; Employee ID should NOT be
        assert any("rating" in opt.lower() or "salary" in opt.lower() for opt in options2)
        assert not any("employee id" == opt.lower() for opt in options2)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_inventory_schema_filter_and_categories():
    """Verifies Inventory schema handles numeric filtering, out-of-scope, nonsensical, and unsafe queries."""
    llm_service.set_mock_classifier(None)
    user_id = f"test_inv_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_inventory_dataset(user_id)

    try:
        # Query 1: Filtered query
        res1 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show items with Quantity on Hand below 20"},
            headers={"X-User-ID": user_id},
        )
        assert res1.status_code == 201, res1.text
        data1 = res1.json()
        assert data1["status"] == "ready_for_sql"
        q1_id = data1["id"]

        exec1 = client.post(f"/api/queries/{q1_id}/execute", headers={"X-User-ID": user_id})
        assert exec1.status_code == 200, exec1.text
        exec1_data = exec1.json()
        assert exec1_data["status"] == "completed"
        sql1 = exec1_data["generated_sql"].lower()
        assert "quantity_on_hand" in sql1
        assert "<" in sql1
        # Rows with Qty < 20: SKU-002 (15), SKU-003 (8), SKU-005 (18) -> 3 rows
        assert exec1_data["result_row_count"] == 3

        # Query 2: Out of Scope
        res2 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the capital of France?"},
            headers={"X-User-ID": user_id},
        )
        assert res2.status_code == 201, res2.text
        data2 = res2.json()
        assert data2["category"] == "OUT_OF_SCOPE"
        assert data2["status"] == "rejected"
        assert data2["generated_sql"] is None

        # Query 3: Nonsensical
        res3 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "asdfghjkl qwerty zxcvbnm"},
            headers={"X-User-ID": user_id},
        )
        assert res3.status_code == 201, res3.text
        data3 = res3.json()
        assert data3["category"] == "NONSENSICAL"
        assert data3["status"] == "rejected"
        assert data3["generated_sql"] is None

        # Query 4: Unsafe SQL injection attempt
        res4 = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show all items; DROP TABLE users; --"},
            headers={"X-User-ID": user_id},
        )
        assert res4.status_code == 201, res4.text
        data4 = res4.json()
        assert data4["category"] == "IMPROPER_OR_UNSAFE"
        assert data4["status"] == "rejected"
        assert data4["generated_sql"] is None

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_ast_repair_missing_limit_and_order():
    """Verifies that bounded AST repair adds missing LIMIT and ORDER clauses."""
    columns = [
        {"original_name": "Order ID", "internal_name": "order_id", "inferred_type": "BIGINT"},
        {"original_name": "Customer Name", "internal_name": "customer_name", "inferred_type": "TEXT"},
        {"original_name": "Units Sold", "internal_name": "units_sold", "inferred_type": "BIGINT"},
    ]
    # Failed SQL that missed LIMIT 5
    failed_sql = "SELECT customer_name, units_sold FROM uploaded_data.orders ORDER BY units_sold DESC"
    question = "Top 5 orders by Units Sold"

    repaired = repair_semantic_sql(
        question=question,
        table_name="orders",
        columns=columns,
        failed_sql=failed_sql,
        error_message="The question requests top 5, but the SQL query does not contain a LIMIT clause.",
        dataset_name="Orders",
    )
    assert "limit 5" in repaired.lower()
    assert "order by" in repaired.lower()
    assert "units_sold" in repaired.lower()
    assert "desc" in repaired.lower()


def test_ast_repair_rejects_unresolved_metric_guess():
    """Verifies that repair refuses to guess an arbitrary column for unresolved evaluative query."""
    columns = [
        {"original_name": "Order ID", "internal_name": "order_id", "inferred_type": "BIGINT"},
        {"original_name": "Units Sold", "internal_name": "units_sold", "inferred_type": "BIGINT"},
        {"original_name": "Total Revenue", "internal_name": "total_revenue", "inferred_type": "NUMERIC"},
    ]
    failed_sql = "SELECT * FROM uploaded_data.orders"
    question = "Give me the top performing order"

    with pytest.raises(SqlValidationError) as exc_info:
        repair_semantic_sql(
            question=question,
            table_name="orders",
            columns=columns,
            failed_sql=failed_sql,
            error_message="Unconstrained table scan",
            dataset_name="Orders",
        )
    assert exc_info.value.error_code == "UNRESOLVED_AMBIGUOUS_METRIC"


# =============================================================================
# 10. Dedicated Tests for Cases A, B, and C
# =============================================================================

def test_case_a_argmax_age_of_highest_scoring_student():
    """
    Case A — Incorrect SQL semantics:
    Question: "What is the age of the highest scoring student?"
    The highest scoring student has marks=95 and age=24.
    An older student exists with age=35 and marks=60.
    Expected:
    1. Query identifies record with highest marks and projects age:
       SELECT age FROM uploaded_data.dataset_<id> ORDER BY marks DESC LIMIT 1
    2. Must NOT calculate MAX(age), which would return 35.
    3. Executed result must be 24.
    """
    csv_data = (
        "StudentID,Student Name,Age,Department,Marks\n"
        "101,Alice Smith,20,Computer Science,85\n"
        "102,Bob Jones,22,Mathematics,78\n"
        "103,Charlie Brown,21,Computer Science,92\n"
        "104,Diana Prince,23,Physics,88\n"
        "105,Ethan Hunt,24,Mathematics,95\n"
        "106,Frank Miller,35,History,60\n"
    )
    user_id = f"test_case_a_{uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/datasets",
        files={"file": ("students_argmax.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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

    try:
        # Step 1: Submit query
        res_q = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the age of the highest scoring student?"},
            headers={"X-User-ID": user_id},
        )
        assert res_q.status_code == 201, res_q.text
        q_data = res_q.json()
        assert q_data["category"] == "RELEVANT_CLEAR"
        assert q_data["status"] == "ready_for_sql"
        query_id = q_data["id"]

        # Step 2: Execute query
        exec_res = client.post(f"/api/queries/{query_id}/execute", headers={"X-User-ID": user_id})
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        sql = exec_data["generated_sql"].lower()
        # Verify it generates an ORDER BY marks DESC LIMIT 1 query
        assert "order by" in sql
        assert "marks" in sql
        assert "desc" in sql
        assert "limit 1" in sql
        assert "age" in sql
        # Strictly verify it does NOT compute MAX(age)
        assert "max(age)" not in sql
        assert "max_age" not in sql

        # Verify returned value is 24 (Ethan's age), NOT 35 (Frank's age)
        assert exec_data["result_row_count"] == 1
        first_row = exec_data["rows"][0]
        returned_age = int(list(first_row.values())[0])
        assert returned_age == 24, f"Expected 24 (age of highest scoring student), but got {returned_age}"

        # Unit verification: validate_sql_semantics MUST reject SELECT MAX(age) AS max_age
        cols_meta = [
            {"original_name": "StudentID", "internal_name": "studentid", "inferred_type": "BIGINT"},
            {"original_name": "Student Name", "internal_name": "student_name", "inferred_type": "TEXT"},
            {"original_name": "Age", "internal_name": "age", "inferred_type": "BIGINT"},
            {"original_name": "Department", "internal_name": "department", "inferred_type": "TEXT"},
            {"original_name": "Marks", "internal_name": "marks", "inferred_type": "BIGINT"},
        ]
        bad_max_sql = f"SELECT MAX(age) AS max_age FROM uploaded_data.{table_name}"
        with pytest.raises(SqlValidationError) as exc:
            validate_sql_semantics(bad_max_sql, "What is the age of the highest scoring student?", table_name, cols_meta)
        assert exc.value.error_code in ("INTENT_MISMATCH_LIMIT", "INTENT_MISMATCH_AGGREGATION", "INTENT_MISMATCH_ORDER")

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_case_b_top_5_performing_students_requires_clarification():
    """
    Case B — Ambiguous question executed without clarification:
    Question: "Give me the top 5 performing students."
    Expected:
    1. Performance metric is not defined in the question.
    2. System classifies as RELEVANT_AMBIGUOUS and halts in awaiting_clarification.
    3. Returns targeted clarification question with schema-grounded options.
    4. Guarantees 0 SQL is generated or executed while ambiguity remains unresolved.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_case_b_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_evaluative_test_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Give me the top 5 performing students."},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "RELEVANT_AMBIGUOUS"
        assert data["status"] == "awaiting_clarification"
        assert data["clarification_question"] is not None
        assert any(w in data["clarification_question"].lower() for w in ("metric", "determine", "define", "measure", "rank", "criteria"))
        assert data["clarification_options"] is not None
        assert len(data["clarification_options"]) >= 2
        # Grounded in candidate metric columns (GPA, Exam Marks, Attendance)
        for opt in data["clarification_options"]:
            assert opt in ("GPA", "Exam Marks", "Attendance")

        # Guarantee no SQL was executed or returned
        assert data["generated_sql"] is None
        assert data["rows"] is None
        assert data["columns"] is None

        # Verify that generator/repair refuses to guess an arbitrary metric
        cols = [
            {"original_name": "StudentID", "internal_name": "studentid", "inferred_type": "BIGINT"},
            {"original_name": "GPA", "internal_name": "gpa", "inferred_type": "NUMERIC"},
            {"original_name": "Exam Marks", "internal_name": "exam_marks", "inferred_type": "BIGINT"},
        ]
        with pytest.raises(SqlValidationError) as exc:
            generate_semantic_sql("Give me the top 5 performing students.", table_name, cols, "Students")
        assert exc.value.error_code == "UNRESOLVED_AMBIGUOUS_METRIC"

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_case_c_unrelated_five_apples_rejected_out_of_scope():
    """
    Case C — Unrelated question executes arbitrary SQL:
    Question: "Give me the name of five apples" against a student dataset.
    Expected:
    1. System classifies as OUT_OF_SCOPE and rejects the request.
    2. Query status transitions to 'rejected'.
    3. Guarantees 0 SQL is generated or executed.
    4. Generator raises UNRESOLVED_QUERY_INTENT and NEVER returns 'SELECT * FROM table'.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_case_c_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Give me the name of five apples"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["category"] == "OUT_OF_SCOPE"
        assert data["status"] == "rejected"
        assert data["generated_sql"] is None
        assert data["rows"] is None
        assert data["columns"] is None
        assert any(term in data["assistant_message"].lower() for term in ("apples", "unrelated", "outside the scope", "scope"))

        # Strict generator refusal test: ensure arbitrary table scan is NEVER produced
        cols = [
            {"original_name": "StudentID", "internal_name": "studentid", "inferred_type": "BIGINT"},
            {"original_name": "Student Name", "internal_name": "student_name", "inferred_type": "TEXT"},
            {"original_name": "Age", "internal_name": "age", "inferred_type": "BIGINT"},
            {"original_name": "Department", "internal_name": "department", "inferred_type": "TEXT"},
            {"original_name": "Marks", "internal_name": "marks", "inferred_type": "BIGINT"},
        ]
        with pytest.raises(SqlValidationError) as exc:
            generate_semantic_sql("Give me the name of five apples", table_name, cols, "Students")
        assert exc.value.error_code in ("OUT_OF_SCOPE", "UNRESOLVED_QUERY_INTENT")

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


# =============================================================================
# 11. Multi-Column Ranking Queries: GPA and Age of Highest Performing Student
# =============================================================================

def create_students_with_gpa_and_age_dataset(user_id: str) -> Tuple[str, str]:
    csv_data = (
        "StudentID,Student Name,GPA,Age,Department,Marks\n"
        "101,Alice Smith,3.85,20,Computer Science,85\n"
        "102,Bob Jones,3.40,22,Mathematics,78\n"
        "103,Charlie Brown,3.90,21,Computer Science,92\n"
        "104,Diana Prince,3.60,23,Physics,88\n"
        "105,Ethan Hunt,3.95,19,Mathematics,95\n"
        "106,Frank Miller,2.50,35,History,60\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("students_gpa_age.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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


def test_gpa_and_age_of_highest_performing_student():
    """
    Verifies fix for multi-column ranking queries:
    Question: "What is the GPA of the highest performing student and give the age too"
    Expected:
    - Generates SQL that retrieves GPA and Age, ordered by GPA DESC (or Marks DESC) LIMIT 1.
    - Strictly rejects SELECT MAX(age) AS max_age or any scalar query ignoring GPA.
    - Result contains GPA=3.95 and Age=19, NOT 35.
    """
    llm_service.set_mock_classifier(None)
    user_id = f"test_gpa_age_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_with_gpa_and_age_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={
                "dataset_id": dataset_id,
                "question": "What is the GPA of the highest performing student and give the age too",
            },
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        q_data = res.json()
        assert q_data["category"] == "RELEVANT_CLEAR"
        assert q_data["status"] == "ready_for_sql"
        query_id = q_data["id"]

        exec_res = client.post(f"/api/queries/{query_id}/execute", headers={"X-User-ID": user_id})
        assert exec_res.status_code == 200, exec_res.text
        exec_data = exec_res.json()

        assert exec_data["status"] == "completed"
        sql = exec_data["generated_sql"].lower()

        # Both GPA and Age must be in the projected query
        assert "gpa" in sql
        assert "age" in sql
        # Must order by performance metric descending with limit 1
        assert "order by" in sql
        assert "desc" in sql
        assert "limit 1" in sql

        # Strictly verify it does NOT compute MAX(age)
        assert "max(age)" not in sql
        assert "max_age" not in sql

        # Verify returned row count and values
        assert exec_data["result_row_count"] == 1
        first_row = exec_data["rows"][0]
        # GPA should be ~3.95 and Age should be 19
        row_vals = {k.lower(): v for k, v in first_row.items()}
        assert any(pytest.approx(3.95, abs=0.05) == float(v) for k, v in row_vals.items() if "gpa" in k)
        assert any(19 == int(v) for k, v in row_vals.items() if "age" in k)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_ai_failure_fails_safely_without_silent_sql():
    """
    Verifies that if Gemini encounters an error, timeout, or malformed response,
    the workflow fails safely without silently executing fallback SQL.
    """
    def broken_classifier(*args, **kwargs):
        raise RuntimeError("Gemini API connection timeout or quota exceeded")

    llm_service.set_mock_classifier(broken_classifier)
    user_id = f"test_ai_fail_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_students_dataset(user_id)

    try:
        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the average Age?"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()

        # Must fail safely or reject, NEVER ready_for_sql or execute SQL
        assert data["status"] in ("failed", "rejected")
        assert data["generated_sql"] is None
        assert data["rows"] is None

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})
