import io
import uuid
import threading
from typing import Tuple, List, Dict, Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.database import SessionLocal, readonly_engine
from app.models.metadata import AppDataset, AppDatasetTable, AppDatasetColumn, AppQuery
from app.schemas.classification import ClassificationResult, ClassificationCategory
from app.services import llm_service
from app.services.sql_validator import validate_sql_query, SqlValidationError
from app.services.query_execution_service import (
    execute_readonly_sql,
    export_rows_to_safe_csv,
    QueryExecutionError,
)

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


def create_test_dataset(user_id: str) -> Tuple[str, str]:
    """Helper to upload a student dataset fixture and return (dataset_id, table_name)."""
    csv_data = (
        "Student Name, Department , CGPA , Enrollment Year\n"
        "Alice Smith, Computer Science, 3.85, 2022\n"
        "Bob Jones, Mathematics, 3.40, 2021\n"
        "Charlie Brown, Computer Science, 3.90, 2023\n"
    )
    res = client.post(
        "/api/datasets",
        files={"file": ("students.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")},
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
# 1. AST & Policy Validation Unit Tests
# =============================================================================

def test_ast_validator_rejects_mutations_and_ddl():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa", "department"}

    mutations = [
        f"INSERT INTO uploaded_data.{target_table} (student_name) VALUES ('Hacker')",
        f"UPDATE uploaded_data.{target_table} SET cgpa = 4.0",
        f"DELETE FROM uploaded_data.{target_table} WHERE cgpa < 3.0",
        f"DROP TABLE uploaded_data.{target_table}",
        f"ALTER TABLE uploaded_data.{target_table} ADD COLUMN is_admin BOOLEAN",
        f"TRUNCATE TABLE uploaded_data.{target_table}",
    ]

    for sql in mutations:
        with pytest.raises(SqlValidationError) as exc:
            validate_sql_query(sql, target_table, allowed_cols)
        assert exc.value.error_code in ("NON_READ_ONLY_STATEMENT", "MUTATION_REJECTED", "FORBIDDEN_SQL_CONSTRUCT")


def test_ast_validator_rejects_multiple_statements_and_comments():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa"}

    stacked = [
        f"SELECT * FROM uploaded_data.{target_table}; DROP TABLE app.app_datasets;",
        f"SELECT * FROM uploaded_data.{target_table}; SELECT * FROM uploaded_data.{target_table}",
        f"-- inline comment\nSELECT * FROM uploaded_data.{target_table}",
        f"SELECT /* block comment */ * FROM uploaded_data.{target_table}",
    ]

    for sql in stacked:
        with pytest.raises(SqlValidationError) as exc:
            validate_sql_query(sql, target_table, allowed_cols)
        assert exc.value.error_code in ("MULTIPLE_STATEMENTS_REJECTED", "FORBIDDEN_SQL_CONSTRUCT")


def test_ast_validator_rejects_unauthorized_tables_and_schemas():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa"}

    unauthorized_queries = [
        "SELECT * FROM app.app_datasets",
        "SELECT * FROM app.app_queries",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM information_schema.columns",
        "SELECT * FROM uploaded_data.dataset_other_user",
        f"SELECT * FROM uploaded_data.{target_table} UNION ALL SELECT * FROM app.app_datasets",
        f"SELECT * FROM (SELECT * FROM app.app_queries) sub",
    ]

    for sql in unauthorized_queries:
        with pytest.raises(SqlValidationError) as exc:
            validate_sql_query(sql, target_table, allowed_cols)
        assert exc.value.error_code in ("UNAUTHORIZED_SCHEMA_ACCESS", "UNAUTHORIZED_TABLE_ACCESS")


def test_ast_validator_rejects_unauthorized_columns_and_system_columns():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa"}

    # Unauthorized column
    with pytest.raises(SqlValidationError) as exc1:
        validate_sql_query(f"SELECT student_name, password FROM uploaded_data.{target_table}", target_table, allowed_cols)
    assert exc1.value.error_code == "UNAUTHORIZED_COLUMN_ACCESS"

    # PostgreSQL system column
    with pytest.raises(SqlValidationError) as exc2:
        validate_sql_query(f"SELECT ctid, student_name FROM uploaded_data.{target_table}", target_table, allowed_cols)
    assert exc2.value.error_code == "SYSTEM_COLUMN_REJECTED"


def test_ast_validator_rejects_dangerous_functions():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa"}

    dangerous_functions = [
        f"SELECT pg_read_file('etc/passwd') FROM uploaded_data.{target_table}",
        f"SELECT pg_sleep(5) FROM uploaded_data.{target_table}",
        f"SELECT current_setting('server_version') FROM uploaded_data.{target_table}",
    ]

    for sql in dangerous_functions:
        with pytest.raises(SqlValidationError) as exc:
            validate_sql_query(sql, target_table, allowed_cols)
        assert exc.value.error_code == "UNAPPROVED_FUNCTION_REJECTED"


def test_ast_validator_accepts_valid_select_and_safe_ctes():
    target_table = "dataset_test123"
    allowed_cols = {"student_name", "cgpa", "department"}

    valid_queries = [
        f"SELECT student_name, cgpa FROM uploaded_data.{target_table} WHERE cgpa > 3.5 ORDER BY cgpa DESC LIMIT 10",
        f"SELECT department, count(*) as count, avg(cgpa) as avg_cgpa FROM uploaded_data.{target_table} GROUP BY department",
        f"WITH top_cs AS (SELECT student_name, cgpa FROM uploaded_data.{target_table} WHERE department = 'Computer Science') SELECT student_name, cgpa FROM top_cs",
    ]

    for sql in valid_queries:
        normalized = validate_sql_query(sql, target_table, allowed_cols)
        assert isinstance(normalized, str)
        assert len(normalized) > 0


# =============================================================================
# 2. Read-Only Database Privilege Enforcement
# =============================================================================

def test_readonly_user_cannot_mutate_database():
    """
    Even if an unvalidated query reached readonly_engine, PostgreSQL refuses DDL/DML.
    """
    with pytest.raises(QueryExecutionError) as exc:
        execute_readonly_sql("DROP TABLE IF EXISTS app.app_datasets")
    assert exc.value.error_code in ("PERMISSION_DENIED", "SQL_EXECUTION_ERROR")


# =============================================================================
# 3. CSV Export and Formula Injection Defense
# =============================================================================

def test_safe_csv_export_neutralizes_formula_injection():
    columns = ["Name", "Score", "Payload"]
    rows = [
        {"Name": "Alice", "Score": 100, "Payload": "=cmd|' /C calc'!A0"},
        {"Name": "Bob", "Score": 95, "Payload": "@SUM(1+2)"},
        {"Name": "Charlie", "Score": 80, "Payload": "+12345"},
        {"Name": "David", "Score": 75, "Payload": "\tTabPayload"},
        {"Name": "Eve", "Score": 90, "Payload": "Normal String, with comma"},
    ]

    csv_output = export_rows_to_safe_csv(columns, rows)

    # Malicious trigger characters must be prefixed with a single quote '
    assert "'=cmd|' /C calc'!A0" in csv_output
    assert "'@SUM(1+2)" in csv_output
    assert "'+12345" in csv_output
    assert "'\tTabPayload" in csv_output
    # Normal strings should not have an unnecessary prepended quote
    assert "Alice" in csv_output
    assert '"Normal String, with comma"' in csv_output


# =============================================================================
# 4. End-to-End Query Execution Pipeline
# =============================================================================

def test_clear_query_executes_to_completion():
    """
    A clear query flows through classification -> SQL generation -> AST validation ->
    readonly execution -> completed results with SQL and explanation.
    """
    user_id = f"test_exec_user_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_test_dataset(user_id)

    clear_classification = ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.98,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    )

    valid_sql = f"SELECT student_name, cgpa FROM uploaded_data.{table_name} WHERE cgpa > 3.5 ORDER BY cgpa DESC"

    try:
        llm_service.set_mock_classifier(lambda *args: clear_classification)
        llm_service.set_mock_sql_generator(lambda *args: valid_sql)
        llm_service.set_mock_explanation(lambda *args: "Explanation of student names")
        llm_service.set_mock_explanation(lambda q, sql, cnt: f"Found {cnt} students with CGPA above 3.5.")

        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show students with CGPA > 3.5"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["status"] == "ready_for_sql"
        assert data["category"] == "RELEVANT_CLEAR"

        # Explicitly execute query
        res_exec = client.post(f"/api/queries/{data['id']}/execute", headers={"X-User-ID": user_id})
        assert res_exec.status_code == 200, res_exec.text
        data = res_exec.json()

        assert data["status"] == "completed"
        assert data["category"] == "RELEVANT_CLEAR"
        assert "student_name" in data["columns"]
        assert "cgpa" in data["columns"]
        assert len(data["rows"]) == 2  # Alice (3.85) and Charlie (3.90)
        assert data["result_row_count"] == 2
        assert data["execution_duration_ms"] is not None
        assert data["generated_sql"] is not None
        assert "Found 2 students with CGPA above 3.5." in data["explanation"]

        # Verify CSV export endpoint
        res_export = client.get(f"/api/queries/{data['id']}/export", headers={"X-User-ID": user_id})
        assert res_export.status_code == 200
        assert res_export.headers["content-type"] == "text/csv; charset=utf-8"
        assert "Alice Smith" in res_export.text
        assert "Charlie Brown" in res_export.text

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


# =============================================================================
# 5. Bounded Repair Loop
# =============================================================================

def test_bounded_repair_succeeds_on_first_repair():
    """
    Candidate SQL initially generates an invalid column -> triggers repair attempt 1 ->
    repaired query passes validation and executes cleanly.
    """
    user_id = f"test_repair_user_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_test_dataset(user_id)

    clear_classification = ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.95,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    )

    # Initial SQL contains invalid column "grade_point"
    invalid_sql = f"SELECT student_name, grade_point FROM uploaded_data.{table_name}"
    # Repaired SQL uses valid column "cgpa"
    repaired_sql = f"SELECT student_name, cgpa FROM uploaded_data.{table_name}"

    try:
        llm_service.set_mock_classifier(lambda *args: clear_classification)
        llm_service.set_mock_sql_generator(lambda *args: invalid_sql)
        llm_service.set_mock_sql_repairer(lambda *args: repaired_sql)

        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show all students and grades"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["status"] == "ready_for_sql"

        # Explicitly execute query
        res_exec = client.post(f"/api/queries/{data['id']}/execute", headers={"X-User-ID": user_id})
        assert res_exec.status_code == 200, res_exec.text
        data = res_exec.json()

        # Successfully repaired and completed!
        assert data["status"] == "completed"
        assert len(data["rows"]) == 3
        assert "cgpa" in data["columns"]

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


def test_bounded_repair_terminates_after_max_repairs():
    """
    If candidate SQL continues to fail after 2 repair attempts, workflow halts with 'failed'.
    """
    user_id = f"test_maxrepair_user_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_test_dataset(user_id)

    clear_classification = ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.95,
        reason="Clear question",
        missing_fields=[],
        ambiguities=[],
    )

    # Persistent syntax error
    bad_sql = f"SELECT FROM uploaded_data.{table_name} WHERE"

    try:
        llm_service.set_mock_classifier(lambda *args: clear_classification)
        llm_service.set_mock_sql_generator(lambda *args: bad_sql)
        llm_service.set_mock_sql_repairer(lambda *args: bad_sql)

        res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show data"},
            headers={"X-User-ID": user_id},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["status"] == "ready_for_sql"

        # Explicitly execute query
        res_exec = client.post(f"/api/queries/{data['id']}/execute", headers={"X-User-ID": user_id})
        assert res_exec.status_code == 200, res_exec.text
        data = res_exec.json()

        assert data["status"] == "failed"
        assert data["error_code"] == "SQL_SYNTAX_ERROR"
        assert "unable to generate or execute a valid query" in data["assistant_message"].lower()

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


# =============================================================================
# 6. Concurrency Control on Query Execution
# =============================================================================

def test_prevent_concurrent_duplicate_execution():
    """
    Simultaneous execution requests for the same query lock the row and do not create duplicate turns.
    """
    user_id = f"test_concur_exec_{uuid.uuid4().hex[:6]}"
    dataset_id, table_name = create_test_dataset(user_id)

    valid_sql = f"SELECT student_name FROM uploaded_data.{table_name}"

    try:
        # 1. Create a query manually in 'ready_for_sql' state
        db = SessionLocal()
        query_id = uuid.uuid4()
        q = AppQuery(
            id=query_id,
            dataset_id=uuid.UUID(dataset_id),
            owner_id=user_id,
            original_question="Show student names",
            status="ready_for_sql",
        )
        db.add(q)
        db.commit()
        db.close()

        llm_service.set_mock_sql_generator(lambda *args: valid_sql)
        llm_service.set_mock_explanation(lambda *args: "Explanation of student names")

        results = []

        def execute_call():
            r = client.post(f"/api/queries/{query_id}/execute", headers={"X-User-ID": user_id})
            results.append((r.status_code, r.json()))

        t1 = threading.Thread(target=execute_call)
        t2 = threading.Thread(target=execute_call)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both calls should resolve to 200 (one executes, the second sees status 'completed' and returns existing)
        for code, resp in results:
            assert code == 200
            assert resp["status"] == "completed"

        # Check turn count in database: exactly 1 turn should have been recorded
        res_get = client.get(f"/api/queries/{query_id}", headers={"X-User-ID": user_id})
        assert len(res_get.json()["turns"]) == 1

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": user_id})


# =============================================================================
# 7. Ownership Isolation on Execution and Export
# =============================================================================

def test_ownership_isolation_on_execute_and_export():
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"
    dataset_id_a, table_name_a = create_test_dataset(user_a)

    try:
        # Create completed query for User A
        db = SessionLocal()
        query_id_a = uuid.uuid4()
        q_a = AppQuery(
            id=query_id_a,
            dataset_id=uuid.UUID(dataset_id_a),
            owner_id=user_a,
            original_question="Show students",
            status="completed",
            result_columns=["student_name"],
            result_rows=[{"student_name": "Alice"}],
            result_row_count=1,
        )
        db.add(q_a)
        db.commit()
        db.close()

        # User B attempts to execute User A's query -> 404
        res_cross_exec = client.post(
            f"/api/queries/{query_id_a}/execute",
            headers={"X-User-ID": user_b},
        )
        assert res_cross_exec.status_code == 404

        # User B attempts to export User A's results -> 404
        res_cross_export = client.get(
            f"/api/queries/{query_id_a}/export",
            headers={"X-User-ID": user_b},
        )
        assert res_cross_export.status_code == 404

    finally:
        client.delete(f"/api/datasets/{dataset_id_a}", headers={"X-User-ID": user_a})
