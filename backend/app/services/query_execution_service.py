import io
import csv
import time
import decimal
import datetime
import uuid
import logging
from typing import Any, List, Dict, Tuple, Optional
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import settings
from app.core.database import readonly_engine

logger = logging.getLogger(__name__)

# Dangerous formula trigger prefixes in spreadsheets (CSV injection / DDE attack)
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class QueryExecutionError(Exception):
    def __init__(self, error_code: str, message: str, raw_db_error: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.raw_db_error = raw_db_error


def _serialize_cell_value(val: Any) -> Any:
    """Converts PostgreSQL database values into JSON-safe primitive types."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    if isinstance(val, decimal.Decimal):
        # Convert integral decimals to int, otherwise float
        return int(val) if val % 1 == 0 else float(val)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")
    return str(val)


def sanitize_csv_cell(val: Any) -> str:
    """
    Sanitizes values for CSV export, neutralizing formula injection attacks.
    If value begins with =, +, -, @, \t, or \r (or after leading spaces), prepends a single quote.
    """
    if val is None:
        return ""
    s = str(val)
    if s.startswith(FORMULA_PREFIXES):
        return f"'{s}"
    s_lstrip = s.lstrip()
    if s_lstrip.startswith(FORMULA_PREFIXES):
        return f"'{s_lstrip}"
    return s


def export_rows_to_safe_csv(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    """Generates RFC 4180 compliant CSV string with spreadsheet formula injection defense."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Sanitize and write header
    writer.writerow([sanitize_csv_cell(c) for c in columns])

    # Write sanitized data rows
    for row in rows:
        writer.writerow([sanitize_csv_cell(row.get(c)) for c in columns])

    return output.getvalue()


def execute_readonly_sql(
    sql_query: str,
    timeout_seconds: Optional[int] = None,
    max_rows: Optional[int] = None,
) -> Tuple[List[str], List[Dict[str, Any]], int, int]:
    """
    Executes a validated read-only SQL query against PostgreSQL using readonly_user.
    Guarantees:
    - Executed strictly via readonly_user (no DDL/DML, access only to uploaded_data).
    - Session set to READ ONLY.
    - Statement timeout enforced via PostgreSQL statement_timeout.
    - Result rows capped server-side (default 1,000 rows).
    - Output values serialized to JSON-safe primitives.
    - Database errors sanitized before returning.
    Returns:
    - (columns, rows, result_row_count, execution_duration_ms)
    """
    timeout_ms = (timeout_seconds or settings.query_timeout_seconds) * 1000
    row_limit = max_rows or settings.max_result_rows

    start_time = time.perf_counter()
    try:
        with readonly_engine.connect() as conn:
            # 1. Enforce transaction read-only mode and statement timeout
            conn.execute(text("SET TRANSACTION READ ONLY;"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms';"))

            # 2. Execute validated query
            cursor = conn.execute(text(sql_query))

            # Extract column names
            columns = list(cursor.keys()) if cursor.returns_rows else []

            # Fetch rows up to row_limit + 1 to detect truncation
            raw_rows = cursor.fetchmany(row_limit + 1) if cursor.returns_rows else []
            total_count = len(raw_rows)

            # Cap rows at row_limit
            capped_raw = raw_rows[:row_limit]

            # Serialize rows to JSON-safe dicts
            serialized_rows = [
                {col: _serialize_cell_value(val) for col, val in zip(columns, row)}
                for row in capped_raw
            ]

    except DBAPIError as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        orig_msg = str(e.orig) if hasattr(e, "orig") else str(e)

        # Detect PostgreSQL statement timeout (SQLSTATE 57014)
        if "statement_timeout" in orig_msg.lower() or "canceling statement due to statement timeout" in orig_msg.lower():
            logger.warning(f"Query timed out after {timeout_ms}ms: {sql_query}")
            raise QueryExecutionError(
                error_code="QUERY_TIMEOUT",
                message=f"Query exceeded statement timeout limit of {timeout_ms // 1000} seconds.",
                raw_db_error="canceling statement due to statement timeout"
            )

        # Detect permission violation
        if "permission denied" in orig_msg.lower():
            logger.error(f"Permission denied during read-only execution: {orig_msg}")
            raise QueryExecutionError(
                error_code="PERMISSION_DENIED",
                message="The database user is not authorized to perform this operation.",
                raw_db_error=orig_msg
            )

        logger.error(f"Database execution error: {orig_msg}")
        # Cleanly sanitize internal table details or stack traces
        sanitized = orig_msg.split("\n")[0]
        raise QueryExecutionError(
            error_code="SQL_EXECUTION_ERROR",
            message=f"Database execution failed: {sanitized}",
            raw_db_error=sanitized
        )
    except Exception as e:
        logger.error(f"Unexpected query execution failure: {str(e)}")
        raise QueryExecutionError(
            error_code="UNEXPECTED_EXECUTION_FAILURE",
            message="An unexpected error occurred during database execution.",
            raw_db_error=str(e)
        )

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    return columns, serialized_rows, total_count, duration_ms
