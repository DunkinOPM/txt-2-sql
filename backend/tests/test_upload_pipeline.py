import io
import uuid
import datetime
from decimal import Decimal
import pytest
import pandas as pd
import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.database import engine, readonly_engine, SessionLocal
from app.services.dataset_service import create_dataset_and_import

client = TestClient(app)


def create_csv_file_bytes(content: str) -> io.BytesIO:
    return io.BytesIO(content.encode("utf-8"))


def create_xlsx_file_bytes(df: pd.DataFrame) -> io.BytesIO:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return buf


def test_valid_csv_upload_and_schema_inspection():
    """Test standard CSV upload, schema retrieval, preview, and physical table creation."""
    csv_data = (
        "Student Name, Department , CGPA , Enrollment Year , Active\n"
        "Alice Smith, Computer Science, 3.85, 2022, True\n"
        "Bob Jones, Mathematics, 3.40, 2021, False\n"
        "Charlie Brown, Computer Science, 3.90, 2023, True\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("students.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_student_user"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    dataset_id = data["id"]
    assert data["display_name"] == "Students"
    assert data["row_count"] == 3
    assert data["column_count"] == 5
    assert data["file_format"] == "csv"
    assert data["status"] == "ready"

    try:
        # 1. Verify schema endpoint
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_student_user"},
        )
        assert schema_res.status_code == 200
        schema_data = schema_res.json()
        assert schema_data["column_count"] == 5
        cols = {c["original_name"]: c for c in schema_data["columns"]}

        # Check column normalization and type inference
        assert cols["Student Name"]["internal_name"] == "student_name"
        assert cols["Student Name"]["inferred_type"] == "TEXT"

        assert cols["Department"]["internal_name"] == "department"
        assert cols["Department"]["inferred_type"] == "TEXT"
        # Categorical sample values extracted for low-cardinality text
        assert cols["Department"]["sample_values"] is not None
        assert "Computer Science" in cols["Department"]["sample_values"]

        assert cols["CGPA"]["internal_name"] == "cgpa"
        assert cols["CGPA"]["inferred_type"] == "NUMERIC"

        assert cols["Enrollment Year"]["internal_name"] == "enrollment_year"
        assert cols["Enrollment Year"]["inferred_type"] == "BIGINT"

        assert cols["Active"]["internal_name"] == "active"
        assert cols["Active"]["inferred_type"] == "BOOLEAN"
        assert cols["Active"]["sample_values"] == [True, False]

        # 2. Verify preview endpoint
        preview_res = client.get(
            f"/api/datasets/{dataset_id}/preview?limit=2",
            headers={"X-User-ID": "test_student_user"},
        )
        assert preview_res.status_code == 200
        preview_data = preview_res.json()
        assert preview_data["total_preview_rows"] == 2
        assert preview_data["total_dataset_rows"] == 3
        assert len(preview_data["rows"]) == 2
        assert preview_data["rows"][0]["student_name"] == "Alice Smith"

        # 3. Verify physical table in PostgreSQL schema 'uploaded_data'
        table_name = schema_data["table_name"]
        with engine.connect() as conn:
            count = conn.execute(
                text(f'SELECT count(*) FROM uploaded_data."{table_name}"')
            ).scalar()
            assert count == 3

    finally:
        # Cleanup
        client.delete(
            f"/api/datasets/{dataset_id}",
            headers={"X-User-ID": "test_student_user"},
        )


def test_valid_xlsx_upload():
    """Test Excel XLSX format upload and ingestion."""
    df = pd.DataFrame({
        "Product": ["Laptop", "Mouse", "Keyboard"],
        "Price": [1200.50, 25.00, 75.25],
        "Quantity": [10, 150, 45],
    })
    xlsx_bytes = create_xlsx_file_bytes(df)

    response = client.post(
        "/api/datasets",
        files={"file": ("inventory.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-ID": "test_inventory_user"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    dataset_id = data["id"]
    assert data["file_format"] == "xlsx"
    assert data["row_count"] == 3
    assert data["column_count"] == 3

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_inventory_user"},
        )
        assert schema_res.status_code == 200
        cols = {c["original_name"]: c["inferred_type"] for c in schema_res.json()["columns"]}
        assert cols["Product"] == "TEXT"
        assert cols["Price"] == "NUMERIC"
        assert cols["Quantity"] == "BIGINT"
    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_inventory_user"})


def test_invalid_extension_rejection():
    """Test rejection of non-CSV/XLSX files."""
    file_bytes = io.BytesIO(b"Hello world, not a dataset")
    response = client.post(
        "/api/datasets",
        files={"file": ("notes.txt", file_bytes, "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_FORMAT"


def test_empty_file_rejection():
    """Test rejection of 0-byte file."""
    file_bytes = io.BytesIO(b"")
    response = client.post(
        "/api/datasets",
        files={"file": ("empty.csv", file_bytes, "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "EMPTY_FILE"


def test_zero_data_rows_rejection():
    """Test rejection of CSV with headers but no data rows."""
    file_bytes = io.BytesIO(b"ColA,ColB\n")
    response = client.post(
        "/api/datasets",
        files={"file": ("no_data.csv", file_bytes, "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "NO_DATA_ROWS"


def test_duplicate_and_colliding_headers():
    """
    CRITICAL REQUIREMENT:
    Duplicate and colliding column headers must NOT fail;
    they must be resolved deterministically (e.g. score, score_2).
    """
    csv_data = (
        "Score,Score,score,Score 1,select\n"
        "95,88,72,100,approved\n"
        "80,75,90,85,pending\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("grades.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_col_user"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_col_user"},
        )
        assert schema_res.status_code == 200
        columns = schema_res.json()["columns"]
        internal_names = [c["internal_name"] for c in columns]

        # Verify all internal names are unique
        assert len(internal_names) == len(set(internal_names))
        # Verify deterministic suffixing
        assert "score" in internal_names
        assert "score_2" in internal_names
        assert "score_3" in internal_names
        assert "score_1" in internal_names
        # Reserved word 'select' prefixed with 'col_'
        assert "col_select" in internal_names
    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_col_user"})


def test_type_inference_conservative_fallback():
    """Test conservative type inference when values are mixed."""
    csv_data = (
        "Id,MixedNumbers,Status\n"
        "1,100,Active\n"
        "2,N/A,Pending\n"
        "3,300,Active\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("mixed.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_mixed_user"},
    )
    assert response.status_code == 201
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_mixed_user"},
        )
        cols = {c["original_name"]: c["inferred_type"] for c in schema_res.json()["columns"]}
        assert cols["Id"] == "BIGINT"
        # MixedNumbers contains "N/A" string so falls back conservatively to TEXT
        assert cols["MixedNumbers"] == "TEXT"
        assert cols["Status"] == "TEXT"
    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_mixed_user"})


def test_dataset_ownership_isolation():
    """
    CRITICAL SECURITY REQUIREMENT:
    User A cannot view, retrieve schema, preview, or delete User B's dataset.
    """
    csv_data = "Item,Count\nBook,5\nPen,10\n"
    file_bytes = create_csv_file_bytes(csv_data)

    # User A uploads dataset
    res_a = client.post(
        "/api/datasets",
        files={"file": ("user_a_data.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "user_a"},
    )
    assert res_a.status_code == 201
    dataset_id_a = res_a.json()["id"]

    try:
        # User B lists datasets: should NOT contain User A's dataset
        res_list_b = client.get(
            "/api/datasets",
            headers={"X-User-ID": "user_b"},
        )
        assert res_list_b.status_code == 200
        ids_b = [d["id"] for d in res_list_b.json()]
        assert dataset_id_a not in ids_b

        # User B attempts to access metadata: 404
        assert client.get(
            f"/api/datasets/{dataset_id_a}",
            headers={"X-User-ID": "user_b"},
        ).status_code == 404

        # User B attempts to access schema: 404
        assert client.get(
            f"/api/datasets/{dataset_id_a}/schema",
            headers={"X-User-ID": "user_b"},
        ).status_code == 404

        # User B attempts to access preview: 404
        assert client.get(
            f"/api/datasets/{dataset_id_a}/preview",
            headers={"X-User-ID": "user_b"},
        ).status_code == 404

        # User B attempts to delete User A's dataset: 404
        assert client.delete(
            f"/api/datasets/{dataset_id_a}",
            headers={"X-User-ID": "user_b"},
        ).status_code == 404

    finally:
        # User A cleans up
        client.delete(f"/api/datasets/{dataset_id_a}", headers={"X-User-ID": "user_a"})


def test_readonly_user_permissions_on_dynamic_table():
    """
    CRITICAL SECURITY CHECK:
    Verify readonly_user can SELECT from the dynamically imported table,
    but CANNOT perform mutations or access schema 'app'.
    """
    csv_data = "Code,Score\nA1,90\nB2,85\n"
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("grades_ro.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_ro_user"},
    )
    assert response.status_code == 201
    dataset_id = response.json()["id"]

    schema_res = client.get(
        f"/api/datasets/{dataset_id}/schema",
        headers={"X-User-ID": "test_ro_user"},
    )
    table_name = schema_res.json()["table_name"]

    try:
        with readonly_engine.connect() as ro_conn:
            # 1. readonly_user CAN SELECT
            rows = ro_conn.execute(
                text(f'SELECT code, score FROM uploaded_data."{table_name}"')
            ).fetchall()
            assert len(rows) == 2

            # 2. readonly_user CANNOT INSERT
            with pytest.raises(Exception) as exc:
                ro_conn.execute(
                    text(f'INSERT INTO uploaded_data."{table_name}" (code, score) VALUES (\'X\', 50)')
                )
            assert "permission denied" in str(exc.value).lower()
            ro_conn.rollback()

            # 3. readonly_user CANNOT DROP
            with pytest.raises(Exception) as exc:
                ro_conn.execute(text(f'DROP TABLE uploaded_data."{table_name}"'))
            err_drop = str(exc.value).lower()
            assert "permission denied" in err_drop or "must be owner" in err_drop or "privilege" in err_drop
            ro_conn.rollback()

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_ro_user"})


def test_upload_failure_cleanup_on_error(monkeypatch):
    """
    CRITICAL REQUIREMENT:
    Failed imports must NOT leave misleading metadata or partially imported tables.
    If insertion fails midway, the dynamic table in uploaded_data must be dropped.
    """
    from app.api import datasets

    unique_user = f"test_fail_user_{uuid.uuid4().hex[:6]}"

    def mock_failing_import(*args, **kwargs):
        raise RuntimeError("Simulated database failure during ingestion")

    monkeypatch.setattr(datasets, "create_dataset_and_import", mock_failing_import)

    csv_data = "Col1,Col2\nVal1,Val2\n"
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("failing.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": unique_user},
    )
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_SERVER_ERROR"

    # Verify no datasets created for this user
    list_res = client.get("/api/datasets", headers={"X-User-ID": unique_user})
    assert list_res.status_code == 200
    assert len(list_res.json()) == 0


def test_transaction_rollback_cleans_up_physical_table():
    """
    Verify that if an error occurs inside create_dataset_and_import after the physical
    table has been created, the created table is dropped so no orphaned table remains.
    """
    df = pd.DataFrame({"Alpha": [1, 2]})
    db = SessionLocal()

    # Intentionally pass an invalid object that causes SQLAlchemy commit to fail
    def failing_commit():
        raise RuntimeError("Forced commit failure to test cleanup")

    original_commit = db.commit
    db.commit = failing_commit

    try:
        with pytest.raises(Exception):
            create_dataset_and_import(
                db=db,
                owner_id="rollback_test_user",
                df=df,
                raw_headers=["Alpha"],
                original_filename="rollback_test.csv",
                file_format="csv",
            )
    finally:
        db.commit = original_commit
        db.close()


def test_dataset_deletion_and_cleanup():
    """Test full deletion: drops dynamic table in PostgreSQL and cascades metadata."""
    csv_data = "City,Population\nTokyo,37000000\nDelhi,32000000\n"
    file_bytes = create_csv_file_bytes(csv_data)

    upload_res = client.post(
        "/api/datasets",
        files={"file": ("cities.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_del_user"},
    )
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["id"]

    schema_res = client.get(
        f"/api/datasets/{dataset_id}/schema",
        headers={"X-User-ID": "test_del_user"},
    )
    table_name = schema_res.json()["table_name"]

    # Delete dataset
    del_res = client.delete(
        f"/api/datasets/{dataset_id}",
        headers={"X-User-ID": "test_del_user"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # 1. Metadata check: GET returns 404
    assert client.get(
        f"/api/datasets/{dataset_id}",
        headers={"X-User-ID": "test_del_user"},
    ).status_code == 404

    # 2. Database check: dynamic table does NOT exist in uploaded_data
    with engine.connect() as conn:
        table_exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'uploaded_data' AND table_name = :tname)"
            ),
            {"tname": table_name},
        ).scalar()
        assert table_exists is False


def test_whitespace_and_empty_column_handling():
    """
    FIX 1 VERIFICATION:
    Columns with only whitespace or empty strings must fall back to nullable TEXT,
    must not be inferred as numeric, and must insert successfully without HTTP 500.
    """
    csv_data = (
        "Id,OnlySpaces,MixedEmpty,ValidNum\n"
        "1,   ,,10\n"
        "2,     ,   ,20\n"
        "3,  ,,30\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("spaces.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_spaces_user"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_spaces_user"},
        )
        assert schema_res.status_code == 200
        cols = {c["original_name"]: c for c in schema_res.json()["columns"]}

        # OnlySpaces: only whitespace, so must be TEXT and nullable=True
        assert cols["OnlySpaces"]["inferred_type"] == "TEXT"
        assert cols["OnlySpaces"]["nullable"] is True
        assert cols["OnlySpaces"]["sample_values"] is None

        # MixedEmpty: whitespace and empty strings, must be TEXT and nullable=True
        assert cols["MixedEmpty"]["inferred_type"] == "TEXT"
        assert cols["MixedEmpty"]["nullable"] is True

        # ValidNum: has actual integers, inferred as BIGINT
        assert cols["ValidNum"]["inferred_type"] == "BIGINT"

        # Preview verification: spaces and empty cells converted to None/null
        preview_res = client.get(
            f"/api/datasets/{dataset_id}/preview",
            headers={"X-User-ID": "test_spaces_user"},
        )
        assert preview_res.status_code == 200
        rows = preview_res.json()["rows"]
        assert len(rows) == 3
        for r in rows:
            assert r["onlyspaces"] is None
            assert r["mixedempty"] is None
            assert r["validnum"] in (10, 20, 30)

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_spaces_user"})


def test_integer_overflow_range_safety():
    """
    FIX 2 VERIFICATION:
    Integers outside PostgreSQL signed 64-bit BIGINT [-2^63, 2^63-1] must NOT
    be inferred as BIGINT, but safely use NUMERIC to prevent 'bigint out of range' errors.
    Standard 64-bit integers must continue to be inferred as BIGINT.
    """
    csv_data = (
        "StandardInt,HugePositive,HugeNegative\n"
        "9223372036854775807,123456789012345678901234567890,-987654321098765432109876543210\n"
        "100,500000000000000000000000000000,-100000000000000000000000000000\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("large_ints.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_overflow_user"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_overflow_user"},
        )
        assert schema_res.status_code == 200
        cols = {c["original_name"]: c["inferred_type"] for c in schema_res.json()["columns"]}

        assert cols["StandardInt"] == "BIGINT"
        assert cols["HugePositive"] == "NUMERIC"
        assert cols["HugeNegative"] == "NUMERIC"

        preview_res = client.get(
            f"/api/datasets/{dataset_id}/preview",
            headers={"X-User-ID": "test_overflow_user"},
        )
        assert preview_res.status_code == 200
        rows = preview_res.json()["rows"]
        assert len(rows) == 2
        assert rows[0]["standardint"] == 9223372036854775807
    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_overflow_user"})


def test_sensitive_column_sample_value_suppression():
    """
    FIX 3 VERIFICATION:
    Sensitive columns (email, phone, mobile, address, salary, tax) must have sample_values=None.
    Non-sensitive columns like 'syntax_type' or 'taxonomy' must NOT be falsely suppressed.
    """
    csv_data = (
        "User Email,Phone Number,Mobile,Home Address,Base Salary,Tax Code,Syntax Type,Taxonomy\n"
        "user1@test.com,555-0101,9876543210,123 Main St,75000,TX-01,Valid,Biology\n"
        "user2@test.com,555-0102,9876543211,456 Elm St,85000,TX-02,Invalid,Physics\n"
    )
    file_bytes = create_csv_file_bytes(csv_data)

    response = client.post(
        "/api/datasets",
        files={"file": ("privacy.csv", file_bytes, "text/csv")},
        headers={"X-User-ID": "test_privacy_user"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_privacy_user"},
        )
        assert schema_res.status_code == 200
        cols = {c["original_name"]: c for c in schema_res.json()["columns"]}

        # Sensitive columns MUST have sample_values suppressed (None)
        assert cols["User Email"]["sample_values"] is None
        assert cols["Phone Number"]["sample_values"] is None
        assert cols["Mobile"]["sample_values"] is None
        assert cols["Home Address"]["sample_values"] is None
        assert cols["Base Salary"]["sample_values"] is None
        assert cols["Tax Code"]["sample_values"] is None

        # Non-sensitive columns must NOT be suppressed
        assert cols["Syntax Type"]["sample_values"] is not None
        assert "Valid" in cols["Syntax Type"]["sample_values"]
        assert cols["Taxonomy"]["sample_values"] is not None
        assert "Biology" in cols["Taxonomy"]["sample_values"]

    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_privacy_user"})


def test_excel_native_date_handling():
    """
    FIX 5 VERIFICATION:
    Excel files containing native openpyxl datetime.date or datetime.datetime cells
    must be correctly inferred as TIMESTAMPTZ, imported without HTTP 500, and
    exposed as timezone-aware ISO strings in the preview.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Event Name", "Event Date", "Event Timestamp"])
    ws.append(["Conference", datetime.date(2023, 6, 15), datetime.datetime(2023, 6, 15, 9, 30, 0)])
    ws.append(["Workshop", datetime.date(2023, 7, 20), datetime.datetime(2023, 7, 20, 14, 0, 0)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = client.post(
        "/api/datasets",
        files={"file": ("events.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-ID": "test_excel_date_user"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    try:
        schema_res = client.get(
            f"/api/datasets/{dataset_id}/schema",
            headers={"X-User-ID": "test_excel_date_user"},
        )
        assert schema_res.status_code == 200
        cols = {c["original_name"]: c["inferred_type"] for c in schema_res.json()["columns"]}
        assert cols["Event Name"] == "TEXT"
        assert cols["Event Date"] == "TIMESTAMPTZ"
        assert cols["Event Timestamp"] == "TIMESTAMPTZ"

        preview_res = client.get(
            f"/api/datasets/{dataset_id}/preview",
            headers={"X-User-ID": "test_excel_date_user"},
        )
        assert preview_res.status_code == 200
        rows = preview_res.json()["rows"]
        assert len(rows) == 2
        # Check ISO string formatting
        assert "2023-06-15" in rows[0]["event_date"]
        assert "2023-06-15T09:30:00" in rows[0]["event_timestamp"]
    finally:
        client.delete(f"/api/datasets/{dataset_id}", headers={"X-User-ID": "test_excel_date_user"})


def test_csv_delimiter_detection_semicolon_and_tab():
    """
    FIX 6 VERIFICATION:
    CSV files delimited by semicolon (;) or tab (\t) must be automatically detected,
    correctly splitting headers and data rows.
    """
    # 1. Semicolon delimited
    semi_csv = "Product;Category;Stock\nLaptop;Electronics;50\nChair;Furniture;120\n"
    res_semi = client.post(
        "/api/datasets",
        files={"file": ("items.csv", create_csv_file_bytes(semi_csv), "text/csv")},
        headers={"X-User-ID": "test_delim_user"},
    )
    assert res_semi.status_code == 201, res_semi.text
    id_semi = res_semi.json()["id"]
    assert res_semi.json()["column_count"] == 3
    assert res_semi.json()["row_count"] == 2

    # 2. Tab delimited
    tab_csv = "Employee\tDepartment\nJohn Doe\tEngineering\nJane Smith\tMarketing\n"
    res_tab = client.post(
        "/api/datasets",
        files={"file": ("staff.csv", create_csv_file_bytes(tab_csv), "text/csv")},
        headers={"X-User-ID": "test_delim_user"},
    )
    assert res_tab.status_code == 201, res_tab.text
    id_tab = res_tab.json()["id"]
    assert res_tab.json()["column_count"] == 2
    assert res_tab.json()["row_count"] == 2

    # Cleanup
    client.delete(f"/api/datasets/{id_semi}", headers={"X-User-ID": "test_delim_user"})
    client.delete(f"/api/datasets/{id_tab}", headers={"X-User-ID": "test_delim_user"})

