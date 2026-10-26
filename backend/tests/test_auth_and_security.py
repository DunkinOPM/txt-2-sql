import io
import time
import uuid
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.database import SessionLocal, ReadonlySessionLocal
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.security import create_access_token
from app.models.user import AppUser
from app.services import llm_service
from app.schemas.classification import ClassificationResult, ClassificationCategory


@pytest.fixture
def client():
    return TestClient(app)


def test_auth_registration_and_login_success(client):
    """
    1. Verifies successful user registration and subsequent login.
    Checks returned JWT token and user profile structure.
    """
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"user_{unique_suffix}@example.com"
    username = f"user_{unique_suffix}"
    password = "SecurePassword123!"

    # Registration
    reg_res = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    assert reg_res.status_code == 201, reg_res.text
    reg_data = reg_res.json()
    assert "access_token" in reg_data
    assert reg_data["token_type"] == "bearer"
    assert reg_data["user"]["email"] == email
    assert reg_data["user"]["username"] == username
    assert "id" in reg_data["user"]
    user_id = reg_data["user"]["id"]

    # Verify cookie was set
    assert "access_token" in reg_res.cookies

    # Login
    login_res = client.post(
        "/api/auth/login",
        json={"username_or_email": email, "password": password},
    )
    assert login_res.status_code == 200, login_res.text
    login_data = login_res.json()
    assert "access_token" in login_data
    assert login_data["user"]["id"] == user_id

    # Verify /api/auth/me
    token = login_data["access_token"]
    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email
    assert me_res.json()["username"] == username


def test_auth_duplicate_registration_and_invalid_credentials(client):
    """
    2. Verifies duplicate email/username rejection (409) and invalid credentials rejection (401).
    """
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"dup_{unique_suffix}@example.com"
    username = f"dup_{unique_suffix}"
    password = "ValidPassword123!"

    # Register initial user
    res1 = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    assert res1.status_code == 201

    # Attempt duplicate email with different username
    res_dup_email = client.post(
        "/api/auth/register",
        json={"email": email, "username": f"other_{unique_suffix}", "password": password},
    )
    assert res_dup_email.status_code == 409
    assert res_dup_email.json()["error_code"] == "EMAIL_ALREADY_REGISTERED"

    # Attempt duplicate username with different email
    res_dup_user = client.post(
        "/api/auth/register",
        json={"email": f"diff_{unique_suffix}@example.com", "username": username, "password": password},
    )
    assert res_dup_user.status_code == 409
    assert res_dup_user.json()["error_code"] == "USERNAME_ALREADY_TAKEN"

    # Invalid login password
    res_bad_pw = client.post(
        "/api/auth/login",
        json={"username_or_email": email, "password": "WrongPassword!"},
    )
    assert res_bad_pw.status_code == 401
    assert res_bad_pw.json()["error_code"] == "INVALID_CREDENTIALS"

    # Non-existent user login
    res_non_existent = client.post(
        "/api/auth/login",
        json={"username_or_email": "non_existent_user_12345@example.com", "password": password},
    )
    assert res_non_existent.status_code == 401
    assert res_non_existent.json()["error_code"] == "INVALID_CREDENTIALS"


def test_passwords_are_hashed_not_plaintext():
    """
    3. Proves passwords are encrypted with bcrypt and never stored in plaintext.
    """
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"hashcheck_{unique_suffix}@example.com"
    username = f"hash_{unique_suffix}"
    plaintext_password = "SecretPasswordToHash123!"

    with SessionLocal() as db:
        from app.services.auth_service import register_user
        user, _ = register_user(db, email, username, plaintext_password)
        db_user = db.query(AppUser).filter(AppUser.id == user.id).first()

        assert db_user is not None
        assert db_user.hashed_password != plaintext_password
        assert db_user.hashed_password.startswith("$2b$")  # Bcrypt hash identifier
        assert plaintext_password not in db_user.hashed_password

        # Raw SQL inspection directly against PostgreSQL
        row = db.execute(
            text("SELECT hashed_password FROM app.app_users WHERE id = :id"),
            {"id": str(user.id)}
        ).fetchone()
        raw_hash = row[0]
        assert raw_hash.startswith("$2b$")
        assert plaintext_password not in raw_hash


def test_missing_malformed_and_expired_tokens(client, monkeypatch):
    """
    4. Proves missing, malformed, expired, and forged-signature tokens return 401 Unauthorized.
    """
    monkeypatch.setattr(settings, "enable_mock_auth", False)

    # Missing token
    res_missing = client.get("/api/auth/me")
    assert res_missing.status_code == 401
    assert res_missing.json()["error_code"] == "UNAUTHORIZED"

    # Malformed token
    res_malformed = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt-token"},
    )
    assert res_malformed.status_code == 401
    assert res_malformed.json()["error_code"] == "INVALID_TOKEN"

    # Forged signature token
    forged_token = create_access_token(
        subject=str(uuid.uuid4()),
        extra_claims={"email": "forged@example.com"}
    )
    # Alter token string slightly
    tampered_token = forged_token[:-4] + "abcd"
    res_tampered = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert res_tampered.status_code == 401
    assert res_tampered.json()["error_code"] == "INVALID_TOKEN"

    # Expired token
    expired_token = create_access_token(
        subject=str(uuid.uuid4()),
        expires_delta=timedelta(seconds=-10)  # Expired 10 seconds ago
    )
    res_expired = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_expired.status_code == 401
    assert res_expired.json()["error_code"] == "TOKEN_EXPIRED"


def test_protected_endpoints_reject_unauthenticated_requests(client, monkeypatch):
    """
    5. Verifies all protected datasets and queries endpoints reject unauthenticated requests
    when production mode is active (enable_mock_auth=False).
    """
    monkeypatch.setattr(settings, "enable_mock_auth", False)

    # Dataset listing
    assert client.get("/api/datasets").status_code == 401

    # Dataset upload
    csv_bytes = b"id,val\n1,10\n"
    res_upload = client.post(
        "/api/datasets",
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res_upload.status_code == 401

    # Query creation
    res_query = client.post(
        "/api/queries",
        json={"dataset_id": str(uuid.uuid4()), "question": "What is the total?"},
    )
    assert res_query.status_code == 401

    # Query history
    assert client.get("/api/queries").status_code == 401


def test_caller_supplied_x_user_id_cannot_impersonate(client, monkeypatch):
    """
    6. Proves caller-supplied X-User-ID header cannot impersonate other users:
    - In production mode, unauthenticated request with X-User-ID is rejected (401).
    - When authenticated with User A's token, passing X-User-ID for User B is ignored.
    """
    monkeypatch.setattr(settings, "enable_mock_auth", False)

    # 1. Unauthenticated request with X-User-ID is strictly rejected
    res_spoof = client.get("/api/datasets", headers={"X-User-ID": "admin_or_victim"})
    assert res_spoof.status_code == 401
    assert res_spoof.json()["error_code"] == "UNAUTHORIZED"

    # 2. Authenticated user supplying a different X-User-ID
    suffix = uuid.uuid4().hex[:8]
    reg_res = client.post(
        "/api/auth/register",
        json={"email": f"alice_{suffix}@example.com", "username": f"alice_{suffix}", "password": "AlicePassword123!"},
    )
    assert reg_res.status_code == 201
    alice_token = reg_res.json()["access_token"]
    alice_id = reg_res.json()["user"]["id"]

    # Upload dataset as Alice while maliciously passing X-User-ID: victim_user
    csv_bytes = b"col1,col2\n10,20\n"
    upload_res = client.post(
        "/api/datasets",
        files={"file": ("alice_data.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-User-ID": "victim_user_who_did_not_upload"
        },
    )
    assert upload_res.status_code == 201
    dataset = upload_res.json()

    # Verify in DB that owner_id was set to Alice's true ID, NOT the spoofed header
    with SessionLocal() as db:
        from app.models.metadata import AppDataset
        db_dataset = db.query(AppDataset).filter(AppDataset.id == uuid.UUID(dataset["id"])).first()
        assert db_dataset is not None
        assert db_dataset.owner_id == str(alice_id)
        assert db_dataset.owner_id != "victim_user_who_did_not_upload"


def test_cross_user_isolation_with_authenticated_jwt(client):
    """
    7. Proves strict data isolation between User A and User B using verified JWT tokens:
    User B cannot read, query, delete, or export User A's dataset or queries.
    """
    suffix = uuid.uuid4().hex[:8]
    # Register User A
    res_a = client.post(
        "/api/auth/register",
        json={"email": f"usera_{suffix}@example.com", "username": f"usera_{suffix}", "password": "Password123!"},
    )
    token_a = res_a.json()["access_token"]

    # Register User B
    res_b = client.post(
        "/api/auth/register",
        json={"email": f"userb_{suffix}@example.com", "username": f"userb_{suffix}", "password": "Password123!"},
    )
    token_b = res_b.json()["access_token"]

    # User A uploads dataset
    csv_bytes = b"dept,budget\nSales,50000\nEngineering,120000\n"
    upload_res = client.post(
        "/api/datasets",
        files={"file": ("financials.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert upload_res.status_code == 201
    dataset_a_id = upload_res.json()["id"]

    # User B attempts to access User A's dataset metadata -> 404
    res_b_get = client.get(
        f"/api/datasets/{dataset_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_get.status_code == 404

    # User B attempts to get User A's schema -> 404
    res_b_schema = client.get(
        f"/api/datasets/{dataset_a_id}/schema",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_schema.status_code == 404

    # User B attempts to get User A's preview -> 404
    res_b_preview = client.get(
        f"/api/datasets/{dataset_a_id}/preview",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_preview.status_code == 404

    # User B attempts to delete User A's dataset -> 404
    res_b_del = client.delete(
        f"/api/datasets/{dataset_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_del.status_code == 404

    # User B attempts to query User A's dataset -> 404
    res_b_query = client.post(
        "/api/queries",
        json={"dataset_id": dataset_a_id, "question": "Total budget?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_query.status_code == 404

    # User B list queries does not include User A's queries
    res_b_history = client.get(
        "/api/queries",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_history.status_code == 200
    assert res_b_history.json()["total"] == 0


def test_auth_and_upload_rate_limiting(client, monkeypatch):
    """
    8. Verifies configurable in-memory sliding window rate limits:
    - Rapid auth attempts trigger 429 Too Many Requests with Retry-After header.
    - Rapid dataset uploads trigger 429 Too Many Requests.
    """
    limiter.reset()
    # Temporarily set limit to 3 requests per minute
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 3)
    monkeypatch.setattr(settings, "rate_limit_upload_per_minute", 2)

    # 1. Auth Rate Limit
    login_payload = {"username_or_email": "ratelimit_user@example.com", "password": "Password123!"}
    r1 = client.post("/api/auth/login", json=login_payload)
    r2 = client.post("/api/auth/login", json=login_payload)
    r3 = client.post("/api/auth/login", json=login_payload)
    r4 = client.post("/api/auth/login", json=login_payload)

    assert r4.status_code == 429
    assert r4.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in r4.headers

    # 2. Upload Rate Limit
    limiter.reset()
    reg = client.post(
        "/api/auth/register",
        json={"email": f"uplim_{uuid.uuid4().hex[:6]}@example.com", "username": f"uplim_{uuid.uuid4().hex[:6]}", "password": "Password123!"}
    )
    auth_header = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    csv_bytes = b"col1\n1\n"

    up1 = client.post("/api/datasets", files={"file": ("1.csv", io.BytesIO(csv_bytes), "text/csv")}, headers=auth_header)
    assert up1.status_code == 201

    up2 = client.post("/api/datasets", files={"file": ("2.csv", io.BytesIO(csv_bytes), "text/csv")}, headers=auth_header)
    assert up2.status_code == 201

    up3 = client.post("/api/datasets", files={"file": ("3.csv", io.BytesIO(csv_bytes), "text/csv")}, headers=auth_header)
    assert up3.status_code == 429
    assert up3.json()["error_code"] == "RATE_LIMIT_EXCEEDED"


def test_readonly_user_database_security_isolation():
    """
    9. Verifies PostgreSQL role isolation: readonly_user is denied access to app.app_users.
    """
    with ReadonlySessionLocal() as ro_db:
        with pytest.raises(Exception) as excinfo:
            ro_db.execute(text("SELECT id, email, hashed_password FROM app.app_users"))
        # Permission denied error from PostgreSQL
        assert "permission denied" in str(excinfo.value).lower()


def test_authenticated_full_workflow_and_logout(client):
    """
    10. Complete end-to-end workflow under active JWT authentication:
    Register -> Upload -> Query -> Execute -> History -> Export -> Logout.
    """
    suffix = uuid.uuid4().hex[:8]
    # Register
    reg = client.post(
        "/api/auth/register",
        json={"email": f"workflow_{suffix}@example.com", "username": f"wf_{suffix}", "password": "SecurePassword123!"}
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Upload dataset
    csv_bytes = b"dept,headcount\nEngineering,50\nMarketing,20\nOperations,30\n"
    up_res = client.post(
        "/api/datasets",
        files={"file": ("staff.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=auth_header,
    )
    assert up_res.status_code == 201
    dataset_id = up_res.json()["id"]

    # Retrieve physical table mapping from DB
    with SessionLocal() as db:
        from app.models.metadata import AppDatasetTable
        mapping = db.query(AppDatasetTable).filter(AppDatasetTable.dataset_id == uuid.UUID(dataset_id)).first()
        table_name = mapping.table_name

    # Set mock LLM handlers for clear execution
    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.98,
        reason="Clear question.",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f"SELECT dept, headcount FROM uploaded_data.{table_name}"
    ))
    llm_service.set_mock_explanation(lambda *args, **kwargs: "Retrieved departments and headcount.")

    try:
        # Submit clear query
        q_res = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "What is the headcount by department?"},
            headers=auth_header,
        )
        assert q_res.status_code == 201
        query_id = q_res.json()["id"]
        assert q_res.json()["status"] == "ready_for_sql"

        # Execute query
        exec_res = client.post(
            f"/api/queries/{query_id}/execute",
            headers=auth_header,
        )
        assert exec_res.status_code == 200
        assert exec_res.json()["status"] == "completed"
        assert exec_res.json()["result_row_count"] == 3

        # History retrieval
        hist_res = client.get(
            f"/api/queries?dataset_id={dataset_id}",
            headers=auth_header,
        )
        assert hist_res.status_code == 200
        assert hist_res.json()["total"] >= 1

        # Safe CSV Export
        export_res = client.get(
            f"/api/queries/{query_id}/export",
            headers=auth_header,
        )
        assert export_res.status_code == 200
        assert "text/csv" in export_res.headers["content-type"]
        assert "Engineering" in export_res.text

        # Logout
        logout_res = client.post(
            "/api/auth/logout",
            headers=auth_header,
        )
        assert logout_res.status_code == 200
        assert logout_res.json()["message"] == "Successfully logged out."
    finally:
        llm_service.set_mock_classifier(None)
        llm_service.set_mock_sql_generator(None)
        llm_service.set_mock_explanation(None)



def test_complete_10_step_demonstration_workflow(client, monkeypatch):
    """
    Verifies the complete 10-step end-to-end demonstration workflow required for Phase 7 closure:
    1. Register User A and log in.
    2. Upload a CSV dataset.
    3. Inspect the detected schema.
    4. Ask a clear natural-language question.
    5. Generate, validate, and execute read-only SQL.
    6. Display query results and generated SQL.
    7. Ask an ambiguous question and resolve it through clarification.
    8. View query history and export results as CSV.
    9. Log out and verify protected endpoints reject unauthenticated requests.
    10. Register User B and verify cross-user isolation.
    """
    suffix = uuid.uuid4().hex[:8]

    # 1. Register User A and log in
    alice_email = f"alice_{suffix}@example.com"
    alice_user = f"alice_{suffix}"
    alice_pwd = "AliceSecurePassword123!"

    reg_a = client.post(
        "/api/auth/register",
        json={"email": alice_email, "username": alice_user, "password": alice_pwd},
    )
    assert reg_a.status_code == 201, reg_a.text
    token_a = reg_a.json()["access_token"]
    auth_a = {"Authorization": f"Bearer {token_a}"}

    login_a = client.post(
        "/api/auth/login",
        json={"username_or_email": alice_email, "password": alice_pwd},
    )
    assert login_a.status_code == 200

    # 2. Upload CSV dataset
    csv_content = (
        b"student_name,department,gpa\n"
        b"Alice Smith,Computer Science,3.90\n"
        b"Bob Jones,Mathematics,3.75\n"
        b"Charlie Brown,Computer Science,3.40\n"
        b"Diana Prince,Physics,3.95\n"
    )
    up_res = client.post(
        "/api/datasets",
        files={"file": ("university_students.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_a,
    )
    assert up_res.status_code == 201
    dataset_a = up_res.json()
    dataset_id = dataset_a["id"]
    assert dataset_a["status"] == "ready"
    assert dataset_a["row_count"] == 4
    assert dataset_a["column_count"] == 3

    # 3. Inspect detected schema
    schema_res = client.get(
        f"/api/datasets/{dataset_id}/schema",
        headers=auth_a,
    )
    assert schema_res.status_code == 200
    schema_data = schema_res.json()
    col_names = [c["internal_name"] for c in schema_data["columns"]]
    assert "student_name" in col_names
    assert "department" in col_names
    assert "gpa" in col_names
    table_name = schema_data["table_name"]

    # 4. Ask a clear question
    llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
        category=ClassificationCategory.RELEVANT_CLEAR,
        confidence=0.99,
        reason="Clear question.",
        missing_fields=[],
        ambiguities=[],
    ))
    llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
        f"SELECT student_name, gpa FROM uploaded_data.{table_name} WHERE department = 'Computer Science' ORDER BY gpa DESC"
    ))
    llm_service.set_mock_explanation(lambda *args, **kwargs: "Showing Computer Science students sorted by GPA.")

    try:
        q_clear = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show Computer Science students sorted by GPA"},
            headers=auth_a,
        )
        assert q_clear.status_code == 201
        clear_data = q_clear.json()
        clear_id = clear_data["id"]
        assert clear_data["category"] == "RELEVANT_CLEAR"
        assert clear_data["status"] == "ready_for_sql"
        # 5. Generate, validate, and execute read-only SQL
        exec_clear = client.post(
            f"/api/queries/{clear_id}/execute",
            headers=auth_a,
        )
        assert exec_clear.status_code == 200
        exec_data = exec_clear.json()

        # 6. Display query results and generated SQL
        assert exec_data["status"] == "completed"
        assert "WHERE department = 'Computer Science'" in exec_data["generated_sql"]
        assert exec_data["result_row_count"] == 2
        assert exec_data["columns"] == ["student_name", "gpa"]
        assert len(exec_data["rows"]) == 2
        assert exec_data["rows"][0]["student_name"] == "Alice Smith"

        # 7. Ask ambiguous question and resolve through clarification
        llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
            category=ClassificationCategory.RELEVANT_AMBIGUOUS,
            confidence=0.85,
            reason="Ambiguous department filter.",
            missing_fields=[],
            ambiguities=["Which department would you like to filter by?"],
        ))
        llm_service.set_mock_rewriter(lambda *args, **kwargs: "Show Mathematics students with their GPA")

        q_ambig = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Show top students"},
            headers=auth_a,
        )
        assert q_ambig.status_code == 201
        ambig_data = q_ambig.json()
        ambig_id = ambig_data["id"]
        assert ambig_data["category"] == "RELEVANT_AMBIGUOUS"
        assert ambig_data["status"] == "awaiting_clarification"

        # Answer clarification and re-classify as resolved/clear
        llm_service.set_mock_classifier(lambda *args, **kwargs: ClassificationResult(
            category=ClassificationCategory.RELEVANT_CLEAR,
            confidence=0.99,
            reason="Clarified department filter to Mathematics.",
            missing_fields=[],
            ambiguities=[],
        ))
        llm_service.set_mock_sql_generator(lambda *args, **kwargs: (
            f"SELECT student_name, gpa FROM uploaded_data.{table_name} WHERE department = 'Mathematics'"
        ))
        clarif_res = client.post(
            f"/api/queries/{ambig_id}/clarifications",
            json={"free_text_answer": "Mathematics department"},
            headers=auth_a,
        )
        assert clarif_res.status_code == 200
        clarif_data = clarif_res.json()
        assert clarif_data["status"] == "ready_for_sql"

        # Execute resolved ambiguous query
        exec_ambig = client.post(
            f"/api/queries/{ambig_id}/execute",
            headers=auth_a,
        )
        assert exec_ambig.status_code == 200
        assert exec_ambig.json()["status"] == "completed"
        assert exec_ambig.json()["result_row_count"] == 1

        # 8. View query history and export results as CSV
        hist_res = client.get(
            f"/api/queries?dataset_id={dataset_id}",
            headers=auth_a,
        )
        assert hist_res.status_code == 200
        hist_data = hist_res.json()
        assert hist_data["total"] >= 2
        history_ids = [item["id"] for item in hist_data["items"]]
        assert clear_id in history_ids
        assert ambig_id in history_ids

        # Export CSV
        csv_export = client.get(
            f"/api/queries/{clear_id}/export",
            headers=auth_a,
        )
        assert csv_export.status_code == 200
        assert "text/csv" in csv_export.headers["content-type"]
        assert "Alice Smith" in csv_export.text

        # 9. Log out and verify unauthenticated rejection
        logout_res = client.post("/api/auth/logout", headers=auth_a)
        assert logout_res.status_code == 200

        # Enforce production mode (mock auth disabled)
        monkeypatch.setattr(settings, "enable_mock_auth", False)

        unauth_get_datasets = client.get("/api/datasets")
        assert unauth_get_datasets.status_code == 401
        assert unauth_get_datasets.json()["error_code"] == "UNAUTHORIZED"

        unauth_get_queries = client.get("/api/queries")
        assert unauth_get_queries.status_code == 401

        # 10. Register User B and verify cross-user isolation
        bob_email = f"bob_{suffix}@example.com"
        bob_user = f"bob_{suffix}"
        bob_pwd = "BobSecurePassword123!"

        reg_b = client.post(
            "/api/auth/register",
            json={"email": bob_email, "username": bob_user, "password": bob_pwd},
        )
        assert reg_b.status_code == 201
        token_b = reg_b.json()["access_token"]
        auth_b = {"Authorization": f"Bearer {token_b}"}

        # Bob cannot see Alice's dataset
        b_datasets = client.get("/api/datasets", headers=auth_b)
        assert b_datasets.status_code == 200
        assert len(b_datasets.json()) == 0

        # Bob cannot access Alice's dataset details or schema
        assert client.get(f"/api/datasets/{dataset_id}", headers=auth_b).status_code == 404
        assert client.get(f"/api/datasets/{dataset_id}/schema", headers=auth_b).status_code == 404
        assert client.get(f"/api/datasets/{dataset_id}/preview", headers=auth_b).status_code == 404

        # Bob cannot query Alice's dataset
        b_query = client.post(
            "/api/queries",
            json={"dataset_id": dataset_id, "question": "Any question"},
            headers=auth_b,
        )
        assert b_query.status_code == 404

        # Bob cannot access Alice's query history or export
        assert client.get(f"/api/queries/{clear_id}", headers=auth_b).status_code == 404
        assert client.get(f"/api/queries/{clear_id}/export", headers=auth_b).status_code == 404

        b_history = client.get("/api/queries", headers=auth_b)
        assert b_history.status_code == 200
        assert b_history.json()["total"] == 0

    finally:
        llm_service.set_mock_classifier(None)
        llm_service.set_mock_rewriter(None)
        llm_service.set_mock_sql_generator(None)
        llm_service.set_mock_explanation(None)
