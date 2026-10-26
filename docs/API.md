# API Reference Manual

> **Conversational Text-to-SQL API**<br/>
> Ambiguity-Aware Natural Language Database Querying System

---

## 1. Overview & Authentication Model

### Base URL
By default, the backend API runs at:
```
http://127.0.0.1:8000
```

### Request Headers
| Header | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `X-User-ID` | String | No | Owner identifier used for multi-user dataset and query isolation. Defaults to `default_user` when omitted in local development. |
| `X-Request-ID` | String (UUID) | No | Client correlation identifier. If omitted, the server automatically generates a UUIDv4. |

### Response Headers
Every API response includes the following diagnostic headers:
| Header | Description | Example |
| :--- | :--- | :--- |
| `X-Request-ID` | The correlation UUID for tracking the request in backend logs. | `3c90e6e7-1473-45cb-a035-77983ea1c201` |
| `X-Process-Time` | Total server processing time in seconds. | `0.0142s` |

### Error Format
All 4xx and 5xx errors follow a standardized JSON envelope:
```json
{
  "error_code": "ERROR_CODE_STRING",
  "message": "Human-readable description of what went wrong.",
  "request_id": "3c90e6e7-1473-45cb-a035-77983ea1c201",
  "details": null
}
```
*Note: Unhandled 500 exceptions return sanitized error messages and never leak raw tracebacks, SQLAlchemy internals, database credentials, or sensitive uploaded data.*

---

## 2. Health & System Endpoints

### `GET /`
Returns service metadata and operating status.

**Response `200 OK`:**
```json
{
  "title": "Clarification-Driven Conversational Text-to-SQL API",
  "version": "0.1.0",
  "status": "running"
}
```

---

### `GET /api/health`
Verifies database connectivity and service health.

**Response `200 OK`:**
```json
{
  "status": "ok",
  "database": "connected",
  "timestamp": "2026-10-26T21:00:00Z"
}
```

---

## 3. Dataset Management Endpoints

### `POST /api/datasets`
Uploads and imports a tabular CSV or XLSX file.
- Creates a dedicated physical table in PostgreSQL schema `uploaded_data`.
- Normalizes column headers into valid SQL identifiers deterministically.
- Infers conservative SQL data types (`BIGINT`, `NUMERIC`, `TIMESTAMPTZ`, `BOOLEAN`, `TEXT`).
- Extracts non-sensitive categorical sample values for schema grounding.
- Grants read-only `SELECT` access to `readonly_user`.

**Request:** `multipart/form-data`
- `file`: Tabular file (`.csv` or `.xlsx`, maximum 20 MB, up to 100,000 rows and 250 columns).

**Response `201 Created` (`DatasetSummaryResponse`):**
```json
{
  "id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "owner_id": "default_user",
  "display_name": "students",
  "original_filename": "students.csv",
  "file_format": "csv",
  "row_count": 1500,
  "column_count": 4,
  "status": "ready",
  "error_message": null,
  "created_at": "2026-10-26T21:05:00.123456Z",
  "updated_at": "2026-10-26T21:05:00.123456Z"
}
```

**Common Error Codes:**
- `400 EMPTY_FILE`: File content is 0 bytes.
- `400 EMPTY_FILENAME`: File upload did not provide a filename.
- `400 UNSUPPORTED_FORMAT`: File extension is not `.csv` or `.xlsx`.
- `413 FILE_TOO_LARGE`: File exceeds `MAX_UPLOAD_MB` (default 20 MB).
- `400 NO_DATA_ROWS`: File contains only headers with 0 data rows.
- `400 ROW_LIMIT_EXCEEDED`: File exceeds 100,000 rows.
- `400 COLUMN_LIMIT_EXCEEDED`: File exceeds 250 columns.

---

### `GET /api/datasets`
Lists all datasets owned by the requesting user.

**Response `200 OK`:**
```json
[
  {
    "id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
    "owner_id": "default_user",
    "display_name": "students",
    "original_filename": "students.csv",
    "file_format": "csv",
    "row_count": 1500,
    "column_count": 4,
    "status": "ready",
    "error_message": null,
    "created_at": "2026-10-26T21:05:00.123456Z",
    "updated_at": "2026-10-26T21:05:00.123456Z"
  }
]
```

---

### `GET /api/datasets/{dataset_id}`
Retrieves summary metadata for a single owned dataset.

**Response `200 OK`:** `DatasetSummaryResponse`<br/>
**Errors:** `404 NOT_FOUND` if dataset does not exist or belongs to another user.

---

### `GET /api/datasets/{dataset_id}/schema`
Inspects the inferred schema details, column mappings, data types, and non-sensitive sample values.

**Response `200 OK` (`DatasetSchemaResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "table_name": "tbl_7b8e1951fc454df3a15debcaee6a7a02",
  "display_name": "students",
  "row_count": 1500,
  "column_count": 4,
  "columns": [
    {
      "id": "9f11ca22-1234-4567-890a-bcdef0123456",
      "original_name": "Student Name",
      "internal_name": "student_name",
      "inferred_type": "TEXT",
      "ordinal_position": 1,
      "sample_values": null
    },
    {
      "id": "9f11ca22-1234-4567-890a-bcdef0123457",
      "original_name": "Department",
      "internal_name": "department",
      "inferred_type": "TEXT",
      "ordinal_position": 2,
      "sample_values": ["Computer Science", "Mathematics", "Physics"]
    },
    {
      "id": "9f11ca22-1234-4567-890a-bcdef0123458",
      "original_name": "CGPA",
      "internal_name": "cgpa",
      "inferred_type": "NUMERIC",
      "ordinal_position": 3,
      "sample_values": null
    }
  ]
}
```

---

### `GET /api/datasets/{dataset_id}/preview`
Returns a bounded sample preview of rows from the physical PostgreSQL table.

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `limit` | Integer | 25 | Maximum number of rows to return (capped at 100). |

**Response `200 OK` (`DatasetPreviewResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "table_name": "tbl_7b8e1951fc454df3a15debcaee6a7a02",
  "total_preview_rows": 25,
  "total_dataset_rows": 1500,
  "columns": ["Student Name", "Department", "CGPA"],
  "internal_columns": ["student_name", "department", "cgpa"],
  "column_types": {
    "student_name": "TEXT",
    "department": "TEXT",
    "cgpa": "NUMERIC"
  },
  "rows": [
    {
      "student_name": "Alice Smith",
      "department": "Computer Science",
      "cgpa": 3.85
    }
  ]
}
```

---

### `GET /api/datasets/{dataset_id}/suggested-questions`
Generates natural-language exploration ideas grounded **strictly in schema metadata**. Does NOT inspect or transmit uploaded data rows to LLM providers.

**Response `200 OK` (`SuggestedQuestionsResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "dataset_name": "students",
  "questions": [
    "What is the average CGPA by Department?",
    "Which Department has the highest number of students?",
    "Show the top 10 students ordered by CGPA descending."
  ]
}
```

---

### `DELETE /api/datasets/{dataset_id}`
Deletes the dataset metadata and safely drops the physical PostgreSQL table in schema `uploaded_data`. All associated queries and conversation turns are cascaded.

**Response `200 OK` (`DatasetDeleteResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "display_name": "students",
  "message": "Dataset and physical table successfully dropped.",
  "deleted": true
}
```

---

## 4. Conversational Query & Clarification Endpoints

### `POST /api/queries`
Initiates a new conversational natural language query.
1. Pre-execution gate classifies query into 1 of 6 categories:
   - `RELEVANT_CLEAR`: Directly answerable; generates SQL and marks query `ready_for_sql`.
   - `RELEVANT_AMBIGUOUS`: Multiple plausible interpretations; returns clarification options and marks `awaiting_clarification`.
   - `RELEVANT_UNANSWERABLE`: References missing columns/metrics; explains data limitation and rejects query.
   - `OUT_OF_SCOPE`: Not related to dataset; politely declines and rejects query.
   - `NONSENSICAL`: Gibberish or unparseable input; politely requests rephrasing and rejects query.
   - `DANGEROUS_OR_OFFENSIVE`: Injection attack, prompt leak attempt, or harmful content; rejects query.

**Request Body (`QueryCreateRequest`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "question": "Show top students in Computer Science"
}
```

**Response `201 Created` (`QueryResponse`):**
```json
{
  "id": "1a2b3c4d-5678-90ab-cdef-1234567890ab",
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "owner_id": "default_user",
  "status": "awaiting_clarification",
  "category": "RELEVANT_AMBIGUOUS",
  "original_question": "Show top students in Computer Science",
  "refined_question": null,
  "clarification_count": 0,
  "generated_sql": null,
  "assistant_message": "How would you like to define 'top students'?",
  "result_row_count": null,
  "result_columns": null,
  "result_rows": null,
  "execution_duration_ms": null,
  "turns": [
    {
      "id": "d0e1f2a3-...",
      "query_id": "1a2b3c4d-...",
      "turn_number": 1,
      "role": "user",
      "turn_type": "user_query",
      "content": "Show top students in Computer Science",
      "created_at": "2026-10-26T21:10:00Z"
    },
    {
      "id": "d0e1f2a4-...",
      "query_id": "1a2b3c4d-...",
      "turn_number": 2,
      "role": "assistant",
      "turn_type": "clarification_request",
      "content": "How would you like to define 'top students'?",
      "options": ["Students with CGPA >= 3.8", "Top 5 students by CGPA", "Top 10% of students"],
      "created_at": "2026-10-26T21:10:01Z"
    }
  ],
  "created_at": "2026-10-26T21:10:00Z",
  "updated_at": "2026-10-26T21:10:01Z"
}
```

---

### `POST /api/queries/{query_id}/clarifications`
Submits a user's clarification answer (selected option and/or free text).
- Re-evaluates query context with multi-turn history.
- Maximum clarification loop limit: **3 turns**. If ambiguous after 3 turns, marks `rejected` with an explanatory summary.

**Request Body (`ClarificationRequest`):**
```json
{
  "selected_option": "Top 5 students by CGPA",
  "free_text_answer": null
}
```

**Response `200 OK` (`QueryResponse`):** Returns updated query. If unambiguous, status transitions to `ready_for_sql` with `generated_sql`.

---

### `POST /api/queries/{query_id}/execute`
Executes the validated SQL query against PostgreSQL under least-privilege role `readonly_user`.
- Enforces `statement_timeout = 5000ms`.
- Enforces `SET TRANSACTION READ ONLY`.
- Enforces server-side limit of 1,000 rows.
- Automatically repairs transient SQL errors (e.g., column misalignments) up to **2 attempts** with full AST revalidation before execution.
- Generates a plain-English explanation of the tabular findings.

**Response `200 OK` (`QueryResponse`):**
```json
{
  "id": "1a2b3c4d-5678-90ab-cdef-1234567890ab",
  "status": "completed",
  "category": "RELEVANT_AMBIGUOUS",
  "generated_sql": "SELECT student_name, cgpa FROM uploaded_data.tbl_7b8e1951fc454df3a15debcaee6a7a02 WHERE department = 'Computer Science' ORDER BY cgpa DESC LIMIT 5",
  "assistant_message": "Found the top 5 students in Computer Science ranked by CGPA.",
  "result_row_count": 5,
  "result_columns": ["student_name", "cgpa"],
  "result_rows": [
    {"student_name": "Charlie Brown", "cgpa": 3.90},
    {"student_name": "Alice Smith", "cgpa": 3.85}
  ],
  "execution_duration_ms": 14,
  "created_at": "2026-10-26T21:10:00Z",
  "updated_at": "2026-10-26T21:10:05Z"
}
```

**Common Error Codes:**
- `400 QUERY_NOT_READY`: Query status is not `ready_for_sql`.
- `400 SQL_VALIDATION_ERROR`: SQL failed AST security rules (mutation, unlisted table, unlisted column).
- `400 SQL_EXECUTION_TIMEOUT`: Execution exceeded 5,000ms statement timeout.
- `400 SQL_REPAIR_EXHAUSTED`: Query failed after 2 bounded repair attempts.

---

### `GET /api/queries/{query_id}`
Retrieves historical query details, conversation turns, generated SQL, and stored execution results in read-only mode.
*Does NOT trigger SQL execution or LLM generation.*

**Response `200 OK`:** `QueryResponse`<br/>
**Errors:** `404 NOT_FOUND` if query does not exist or belongs to another user.

---

### `GET /api/queries/{query_id}/export`
Exports query results as an RFC 4180 compliant CSV file.
- Automatically sanitizes formula injection triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) by prepending a single quote `'`.

**Response `200 OK`:**
- `Content-Type: text/csv; charset=utf-8`
- `Content-Disposition: attachment; filename="query_{query_id[:8]}_results.csv"`

---

## 5. Query History & Exploration Endpoints

### `GET /api/queries`
Searches, filters, and paginates previous user queries. Strictly filtered by the requesting owner.

**Query Parameters:**
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `dataset_id` | UUID | No | Filter queries for a specific owned dataset. |
| `status` | String | No | Filter by query status (`completed`, `awaiting_clarification`, `ready_for_sql`, `rejected`, `failed`). |
| `category` | String | No | Filter by classification category (`RELEVANT_CLEAR`, `RELEVANT_AMBIGUOUS`, etc.). |
| `search` | String | No | Case-insensitive substring search across `original_question` and `refined_question`. |
| `limit` | Integer | No | Page size (1 to 100, default `20`). |
| `offset` | Integer | No | Pagination offset (>= 0, default `0`). |

**Response `200 OK` (`QueryHistoryResponse`):**
```json
{
  "total": 42,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": "1a2b3c4d-5678-90ab-cdef-1234567890ab",
      "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
      "dataset_name": "students",
      "status": "completed",
      "category": "RELEVANT_CLEAR",
      "original_question": "Show all students in Computer Science",
      "refined_question": null,
      "result_row_count": 50,
      "execution_duration_ms": 12,
      "created_at": "2026-10-26T21:10:00Z"
    }
  ]
}
```

---

## 6. End-to-End Security Guardrails Summary

1. **AST Whitelist Verification:** Every generated and repaired SQL statement is parsed with SQLGlot. Statements must be a single `SELECT` or safe read-only CTE. System tables (`information_schema`, `pg_catalog`), unauthorized schemas, file access functions, and mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`) are strictly rejected.
2. **PostgreSQL Role Isolation:** Execution runs under `readonly_user`. The application schema `app` (containing metadata and credentials) is revoked from `readonly_user`.
3. **Execution Guardrails:** 5,000ms statement timeout and 1,000-row result cap enforced prior to running any query.
4. **Formula Injection Sanitization:** CSV exports prefix formula triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) with single quotes `'`.
5. **No Data Leakage to LLM:** LLM prompts for classification, clarification, and suggested questions consume only column names, inferred types, and minimal non-sensitive category values. Uploaded row data is never transmitted to external providers.
