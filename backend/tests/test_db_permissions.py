import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.core.database import engine, readonly_engine


def test_admin_has_full_access():
    """Verify appuser can access and manage metadata in schema 'app'."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT count(*) FROM app.app_datasets")).scalar()
        assert result is not None


def test_readonly_user_denied_app_schema_access():
    """
    CRITICAL SECURITY CHECK:
    Verify readonly_user CANNOT access schema 'app' or any of its tables.
    Effective privileges (including PUBLIC and inherited) must NOT permit reading app metadata.
    """
    with readonly_engine.connect() as ro_conn:
        # Check has_schema_privilege directly from PostgreSQL catalog
        has_usage = ro_conn.execute(
            text("SELECT has_schema_privilege('readonly_user', 'app', 'USAGE')")
        ).scalar()
        assert has_usage is False, "readonly_user must not have USAGE on schema 'app'"

        # Attempt to SELECT from app_datasets
        with pytest.raises(DBAPIError) as exc_info:
            ro_conn.execute(text("SELECT * FROM app.app_datasets"))
        
        # Verify the database rejected with permission denied
        err_msg = str(exc_info.value).lower()
        assert "permission denied" in err_msg or "privilege" in err_msg
        ro_conn.rollback()


def test_readonly_user_uploaded_data_behavior():
    """
    Verify readonly_user can SELECT from uploaded_data tables,
    but CANNOT perform INSERT, UPDATE, DELETE, or DDL (DROP, CREATE, ALTER).
    """
    test_table = "test_perm_check_01"

    # Step 1: Create a test table in uploaded_data as appuser
    with engine.begin() as admin_conn:
        admin_conn.execute(text(f"DROP TABLE IF EXISTS uploaded_data.{test_table}"))
        admin_conn.execute(text(
            f"CREATE TABLE uploaded_data.{test_table} (id SERIAL PRIMARY KEY, val TEXT)"
        ))
        admin_conn.execute(text(
            f"INSERT INTO uploaded_data.{test_table} (val) VALUES ('sample_data')"
        ))

    try:
        with readonly_engine.connect() as ro_conn:
            # 1. readonly_user CAN SELECT
            rows = ro_conn.execute(
                text(f"SELECT val FROM uploaded_data.{test_table}")
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "sample_data"

            # 2. readonly_user CANNOT INSERT
            with pytest.raises(DBAPIError) as exc_info:
                ro_conn.execute(
                    text(f"INSERT INTO uploaded_data.{test_table} (val) VALUES ('hack')")
                )
            assert "permission denied" in str(exc_info.value).lower()
            ro_conn.rollback()

            # 3. readonly_user CANNOT UPDATE
            with pytest.raises(DBAPIError) as exc_info:
                ro_conn.execute(
                    text(f"UPDATE uploaded_data.{test_table} SET val = 'tampered'")
                )
            assert "permission denied" in str(exc_info.value).lower()
            ro_conn.rollback()

            # 4. readonly_user CANNOT DELETE
            with pytest.raises(DBAPIError) as exc_info:
                ro_conn.execute(
                    text(f"DELETE FROM uploaded_data.{test_table}")
                )
            assert "permission denied" in str(exc_info.value).lower()
            ro_conn.rollback()

            # 5. readonly_user CANNOT DROP TABLE (must be owner / insufficient privilege)
            with pytest.raises(DBAPIError) as exc_info:
                ro_conn.execute(
                    text(f"DROP TABLE uploaded_data.{test_table}")
                )
            err_drop = str(exc_info.value).lower()
            assert "permission denied" in err_drop or "must be owner" in err_drop or "insufficientprivilege" in err_drop
            ro_conn.rollback()

            # 6. readonly_user CANNOT CREATE TABLE in uploaded_data
            with pytest.raises(DBAPIError) as exc_info:
                ro_conn.execute(
                    text("CREATE TABLE uploaded_data.malicious (id INT)")
                )
            assert "permission denied" in str(exc_info.value).lower()
            ro_conn.rollback()

    finally:
        # Cleanup test table as appuser
        with engine.begin() as admin_conn:
            admin_conn.execute(text(f"DROP TABLE IF EXISTS uploaded_data.{test_table}"))
