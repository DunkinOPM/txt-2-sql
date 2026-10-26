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
In Docker Compose deployments, the frontend proxies `/api/` directly to the backend service.

### Authentication & Authorization Model
- **JWT Bearer Authentication:** All protected endpoints require a signed HS256 JSON Web Token (JWT) provided in the `Authorization` header as `Bearer <token>` or as an HttpOnly `access_token` session cookie.
- **Passwords:** Plaintext passwords are never stored or logged. Stored credentials use 12-round `bcrypt` key derivation with random salting.
- **Anti-Spoofing & Impersonation Protection:** User identity is derived strictly from the verified JWT payload (`sub`). Caller-supplied `X-User-ID` headers are ignored and cannot impersonate other users.
- **Gated Mock Authentication:** `ENABLE_MOCK_AUTH` is strictly disabled by default (`false`) outside explicit local development. In production, unauthenticated requests are rejected immediately with `401 Unauthorized`.
- **Ownership Isolation:** All datasets, table mappings, generated queries, clarification turns, and CSV exports are strictly isolated by owner ID. Inaccessible resources return `404 Not Found` to prevent resource existence enumeration.

### Request Headers
| Header | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `Authorization` | String | Yes (Protected) | Bearer token format: `Bearer <JWT_ACCESS_TOKEN>`. |
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

### Error Codes Summary
| Status | Error Code | Description |
| :--- | :--- | :--- |
| `400` | `INVALID_PARAMETERS` | Malformed parameters, invalid status/category filters, or query execution preconditions not met. |
| `401` | `UNAUTHORIZED` | Missing, malformed, or invalid Bearer token. |
| `401` | `TOKEN_EXPIRED` | JWT access token expired. Re-authentication required. |
| `401` | `INVALID_CREDENTIALS` | Incorrect username/email or password during login. |
| `403` | `ACCOUNT_INACTIVE` | User account has been deactivated. |
| `404` | `NOT_FOUND` | Resource does not exist or belongs to another user. |
| `409` | `EMAIL_ALREADY_REGISTERED` | User registration failed due to duplicate email address. |
| `409` | `USERNAME_ALREADY_TAKEN` | User registration failed due to duplicate username. |
| `413` | `FILE_TOO_LARGE` | Uploaded file size exceeds the configured limit (`MAX_UPLOAD_MB`). |
| `422` | `VALIDATION_ERROR` | Request body or query parameters failed Pydantic schema validation. |
| `429` | `RATE_LIMIT_EXCEEDED` | Request rate exceeded the sliding window limit. Includes `Retry-After` header. |
| `500` | `INTERNAL_SERVER_ERROR` | Sanitized server error with correlation `request_id`. |

---

## 2. Authentication Endpoints

### `POST /api/auth/register`
Registers a new user account. Returns a signed JWT token and user profile.
- Rate-limited per client IP.
- Hashes passwords using bcrypt with a 12-round salt.

**Request Body (`UserRegisterRequest`):**
```json
{
  "email": "analyst@example.com",
  "username": "analyst_alice",
  "password": "SecurePassword123!"
}
```

**Response `201 Created` (`TokenResponse`):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "e4f5a2b1-1234-4567-89ab-cdef01234567",
    "email": "analyst@example.com",
    "username": "analyst_alice",
    "created_at": "2026-10-27T02:00:00Z"
  }
}
```

---

### `POST /api/auth/login`
Authenticates registered user credentials. Returns signed JWT token.
- Rate-limited per client IP.
- Timing-attack mitigated.

**Request Body (`UserLoginRequest`):**
```json
{
  "username_or_email": "analyst_alice",
  "password": "SecurePassword123!"
}
```

**Response `200 OK` (`TokenResponse`):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "e4f5a2b1-1234-4567-89ab-cdef01234567",
    "email": "analyst@example.com",
    "username": "analyst_alice",
    "created_at": "2026-10-27T02:00:00Z"
  }
}
```

---

### `GET /api/auth/me`
Retrieves current profile metadata for the authenticated user session.
- Requires `Authorization: Bearer <token>`.

**Response `200 OK` (`UserResponse`):**
```json
{
  "id": "e4f5a2b1-1234-4567-89ab-cdef01234567",
  "email": "analyst@example.com",
  "username": "analyst_alice",
  "created_at": "2026-10-27T02:00:00Z"
}
```

---

### `POST /api/auth/logout`
Invalidates client session and clears authentication cookies.

**Response `200 OK`:**
```json
{
  "message": "Successfully logged out."
}
```

---

## 3. Health & System Endpoints

### `GET /`
Returns service metadata and operating status.

**Response `200 OK`:**
```json
{
  "project": "Clarification-Driven Conversational Text-to-SQL",
  "version": "0.1.0",
  "status": "online",
  "docs_url": "/docs"
}
```

---

### `GET /api/health`
Verifies database connectivity and service health.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "database": "connected",
  "readonly_database": "connected",
  "version": "0.1.0",
  "environment": "development"
}
```

---

## 4. Dataset Management Endpoints

### `POST /api/datasets`
Uploads and imports a tabular CSV or XLSX file for the authenticated user.
- Rate-limited per client IP/user.
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
  "owner_id": "e4f5a2b1-1234-4567-89ab-cdef01234567",
  "display_name": "students",
  "original_filename": "students.csv",
  "file_format": "csv",
  "row_count": 1500,
  "column_count": 4,
  "status": "ready",
  "error_message": null,
  "created_at": "2026-10-27T02:05:00.123456Z",
  "updated_at": "2026-10-27T02:05:00.123456Z"
}
```

---

### `GET /api/datasets`
Lists all datasets owned by the authenticated user.

**Response `200 OK`:** `List[DatasetSummaryResponse]`

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
  "display_name": "students",
  "table_name": "dataset_7b8e1951fc454df3a15debcaee6a7a02",
  "row_count": 1500,
  "column_count": 4,
  "columns": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
      "ordinal_position": 1,
      "original_name": "Student ID",
      "internal_name": "student_id",
      "inferred_type": "BIGINT",
      "nullable": false,
      "sample_values": null,
      "created_at": "2026-10-27T02:05:00Z"
    }
  ]
}
```

---

### `GET /api/datasets/{dataset_id}/preview`
Retrieves bounded raw rows (1 to 100 rows) directly from the underlying physical table.

**Query Parameters:**
- `limit`: Integer (1 to 100, default `20`).

**Response `200 OK` (`DatasetPreviewResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "columns": ["student_id", "student_name", "department", "gpa"],
  "rows": [
    {"student_id": 1, "student_name": "Alice Smith", "department": "Computer Science", "gpa": 3.85}
  ],
  "total_rows": 1500
}
```

---

### `GET /api/datasets/{dataset_id}/suggested-questions`
Generates 3 to 4 schema-grounded natural language query suggestions.
- Uses only authorized table column metadata. Uploaded row data is never transmitted to LLM.

**Response `200 OK` (`SuggestedQuestionsResponse`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "dataset_name": "students",
  "questions": [
    "What is the average GPA by department?",
    "Show the top 10 students with the highest GPA",
    "How many students are enrolled in each department?"
  ]
}
```

---

### `DELETE /api/datasets/{dataset_id}`
Permanently deletes an authorized dataset, cascades associated metadata, and drops the physical table in `uploaded_data`.

**Response `200 OK` (`DatasetDeleteResponse`):**
```json
{
  "id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "display_name": "students",
  "status": "deleted",
  "message": "Dataset and associated physical table deleted successfully."
}
```

---

## 5. Conversational Query Endpoints

### `POST /api/queries`
Submits a natural language question for classification, clarification, and SQL generation.

**Request Body (`QueryCreateRequest`):**
```json
{
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "question": "Show all students in Computer Science with GPA above 3.5"
}
```

**Response `201 Created` (`QueryResponse`):**
```json
{
  "id": "9f8e7d6c-5b4a-3210-fedc-ba9876543210",
  "dataset_id": "7b8e1951-fc45-4df3-a15d-ebcaee6a7a02",
  "owner_id": "e4f5a2b1-1234-4567-89ab-cdef01234567",
  "original_question": "Show all students in Computer Science with GPA above 3.5",
  "refined_question": null,
  "category": "RELEVANT_CLEAR",
  "status": "ready_for_sql",
  "generated_sql": "SELECT student_name, gpa FROM uploaded_data.dataset_7b8e1951fc454df3a15debcaee6a7a02 WHERE department = 'Computer Science' AND gpa > 3.5",
  "explanation": "Retrieves Computer Science students having GPA strictly greater than 3.5.",
  "result_columns": null,
  "result_rows": null,
  "result_row_count": null,
  "execution_duration_ms": null,
  "turns": [
    {
      "turn_number": 1,
      "role": "user",
      "turn_type": "question",
      "content": "Show all students in Computer Science with GPA above 3.5",
      "clarification_options": null,
      "created_at": "2026-10-27T02:08:00Z"
    }
  ]
}
```

---

### `POST /api/queries/{query_id}/clarifications`
Submits an answer to a clarification prompt for an ambiguous query.

**Request Body (`ClarificationAnswerRequest`):**
```json
{
  "selected_option": "Computer Science (department)",
  "free_text_answer": null
}
```

**Response `200 OK`:** `QueryResponse`

---

### `POST /api/queries/{query_id}/execute`
Executes validated SQL against the database using the least-privilege `readonly_user`.
- Enforces 5,000ms statement timeout.
- Caps result sets at 1,000 rows.

**Response `200 OK`:** `QueryResponse` (with `status: completed`, `result_columns`, `result_rows`).

---

### `GET /api/queries/{query_id}`
Retrieves query history details in read-only mode. Does not trigger execution.

**Response `200 OK`:** `QueryResponse`<br/>
**Errors:** `404 NOT_FOUND` if query does not exist or belongs to another user.

---

### `GET /api/queries/{query_id}/export`
Exports query results as an RFC 4180 compliant CSV file.
- Formula injection triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) are sanitized by prepending `'`.

**Response `200 OK`:** `text/csv; charset=utf-8`

---

## 6. Query History & Exploration Endpoints

### `GET /api/queries`
Searches, filters, and paginates previous queries owned by the authenticated user.

**Query Parameters:**
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `dataset_id` | UUID | No | Filter queries for a specific owned dataset. |
| `status` | String | No | Filter by query status (`completed`, `awaiting_clarification`, `ready_for_sql`, `rejected`, `failed`). |
| `category` | String | No | Filter by classification category (`RELEVANT_CLEAR`, `RELEVANT_AMBIGUOUS`, etc.). |
| `search` | String | No | Case-insensitive substring search across `original_question` and `refined_question`. |
| `limit` | Integer | No | Page size (1 to 100, default `20`). |
| `offset` | Integer | No | Pagination offset (>= 0, default `0`). |

**Response `200 OK` (`QueryHistoryListResponse`):**
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
      "created_at": "2026-10-27T02:10:00Z"
    }
  ]
}
```

---

## 7. End-to-End Security Guardrails Summary

1. **JWT Authentication & Bcrypt Passwords:** All users authenticate via signed HS256 JWT tokens. Passwords are encrypted with bcrypt (12 rounds) and never stored or logged in plaintext.
2. **Strict Identity Isolation:** Caller-supplied `X-User-ID` headers are ignored and cannot impersonate other users. Inaccessible resources return `404 Not Found`.
3. **AST Whitelist Verification:** Every generated and repaired SQL statement is parsed with SQLGlot. Statements must be a single `SELECT` or safe read-only CTE. System tables (`information_schema`, `pg_catalog`), unauthorized schemas, file access functions, and mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`) are strictly rejected.
4. **PostgreSQL Role Isolation:** Execution runs under `readonly_user`. The application schema `app` (containing metadata, users, credentials, and query turns) is explicitly revoked from `readonly_user`.
5. **Rate Limiting:** Sliding-window rate limiters prevent credential stuffing and upload abuse.
6. **Execution Guardrails:** 5,000ms statement timeout and 1,000-row result cap enforced prior to running any query.
7. **Formula Injection Sanitization:** CSV exports prefix formula triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) with single quotes `'`.
8. **No Data Leakage to LLM:** LLM prompts consume only column names, inferred types, and minimal non-sensitive category values. Uploaded row data is never transmitted to external providers.
