# Clarification-Driven Conversational Text-to-SQL

> **An Ambiguity-Aware Framework for Reliable Natural Language Database Querying**

---

## 1. Overview & Guiding Philosophy

This project implements a conversational data assistant for structured tabular datasets (CSV and XLSX). Rather than guessing ambiguous column filters, hallucinating non-existent database fields, or executing unsafe mutations, this framework adheres to a core design principle: **clarify or abstain rather than inventing intent or fabricating answers.**

### Key Architectural Highlights
- **Pre-execution Intent Gate:** Every natural language question is classified into one of six distinct categories before any SQL is generated (`RELEVANT_CLEAR`, `RELEVANT_AMBIGUOUS`, `RELEVANT_UNANSWERABLE`, `OUT_OF_SCOPE`, `NONSENSICAL`, `IMPROPER_OR_UNSAFE`).
- **Structured Multi-Turn Clarification:** Ambiguous queries present structured clarification options and allow free-text responses, continuing in a multi-turn clarification loop bounded at three turns.
- **AST Security Policy:** All candidate SQL statements are parsed using SQLGlot, restricted to single read-only `SELECT` statements (and safe read-only CTEs), and validated against backend-registered table and column allowlists.
- **Least-Privilege Database Isolation:** Dynamic queries execute strictly under a dedicated PostgreSQL `readonly_user` role with statement timeouts (`10,000ms`), transaction read-only mode, and zero access to internal application schemas (`app`).
- **Production Authentication & Anti-Spoofing:** Real user registration and login with `bcrypt` (12-round salt) password hashing and signed HS256 JWT tokens. Caller-supplied `X-User-ID` headers are ignored; dataset and query ownership is bound strictly to verified JWT claims.
- **RFC 4180 Safe CSV Export:** Downloaded query results neutralize spreadsheet formula injection attacks (`=`, `+`, `-`, `@`, `\t`, `\r`) by prepending a single quote `'`.
- **Privacy & Grounding Guarantee:** LLM prompts consume authorized column metadata, inferred types, and low-cardinality category values. Uploaded row data is never transmitted to external providers.

---

## 2. Prerequisites

Ensure the following tools are installed on your machine:
- **Docker & Docker Compose** (Docker Desktop on Windows/macOS or Docker Engine on Linux)
- **Python 3.11+**
- **Node.js 20+ & npm**
- **Git**

---

## 3. Environment Configuration & Secret Generation

Copy `.env.example` to `.env` in the repository root:
```powershell
# Windows PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

### Generating Secure Secrets
Generate a cryptographically secure 32-byte secret for `JWT_SECRET_KEY`:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

### Environment Variables Reference
| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | String | `development` | Environment mode (`development` or `production`). In production, mock auth is forbidden and strong JWT keys are enforced. |
| `POSTGRES_DB` | String | `text2sql` | Database name. |
| `POSTGRES_USER` | String | `appuser` | Master administrative database user owning schemas `app` and `uploaded_data`. |
| `POSTGRES_PASSWORD` | String | `local_dev_password` | Master database password. Change in production. |
| `READONLY_USER_PASSWORD` | String | `readonly_dev_password` | Password for dedicated query execution role `readonly_user`. |
| `DATABASE_URL` | String | `postgresql+psycopg://appuser:...@127.0.0.1:5432/text2sql` | Master connection URL for migrations, user models, and table provisioning. |
| `READONLY_DATABASE_URL` | String | `postgresql+psycopg://readonly_user:...@127.0.0.1:5432/text2sql` | Connection URL strictly for dynamic SQL query execution. |
| `JWT_SECRET_KEY` | String | *32+ chars* | Cryptographic signing secret for HS256 authentication tokens. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`| Integer | `1440` | Token expiration lifetime (default 24 hours). |
| `ENABLE_MOCK_AUTH` | Boolean | `false` | Gated development mock authentication. **Must remain `false` in production.** |
| `RATE_LIMIT_AUTH_PER_MINUTE` | Integer | `15` | Maximum registration and login requests permitted per IP per minute. |
| `RATE_LIMIT_UPLOAD_PER_MINUTE` | Integer | `20` | Maximum file uploads permitted per client per minute. |
| `GEMINI_API_KEY` | String | `placeholder_key` | Google Gemini API key for intent classification and SQL generation. |
| `FRONTEND_ORIGIN` | String | `http://localhost:5173` | Primary frontend origin for CORS headers. |
| `MAX_UPLOAD_MB` | Integer | `20` | Maximum tabular file upload size in megabytes. |
| `MAX_UPLOAD_ROWS` | Integer | `100000` | Hard cap on row count per uploaded dataset. |
| `MAX_UPLOAD_COLUMNS` | Integer | `250` | Hard cap on column count per uploaded dataset. |
| `QUERY_TIMEOUT_SECONDS` | Integer | `10` | Server-side execution timeout for dynamic queries. |
| `MAX_RESULT_ROWS` | Integer | `1000` | Hard cap on row results returned and persisted. |

---

## 4. Running with Docker Compose (Full Demonstration)

The repository provides a complete containerized deployment including PostgreSQL 17, FastAPI backend, and Nginx reverse-proxy serving the React production build:

```powershell
# 1. Build and launch all services in background
docker compose up -d --build

# 2. Check service health
docker compose ps
```

Services will be accessible at:
- **Web Application (Nginx + React SPA):** `http://127.0.0.1:3000`
- **FastAPI Backend (Direct API):** `http://127.0.0.1:8000`
- **API Documentation (Swagger UI):** `http://127.0.0.1:8000/docs`
- **PostgreSQL Database:** `127.0.0.1:5432`

To shut down containers and preserve data:
```powershell
docker compose down
```

To shut down and wipe persistent volumes:
```powershell
docker compose down -v
```

---

## 5. Local Development Runbook (Windows PowerShell)

If running directly on the host machine without Docker for backend/frontend:

### Step 1: Start PostgreSQL
```powershell
docker compose up -d postgres
```

### Step 2: Set Up Backend
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# Run Alembic migrations to create schemas and tables
alembic upgrade head

# Start FastAPI development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Step 3: Set Up Frontend
Open a new PowerShell terminal:
```powershell
cd frontend
npm install
npm run dev
```
Open your browser to `http://localhost:5173`.

---

## 6. Two-User Demonstration Script (Verifying Data Isolation)

Follow these steps in the web UI to verify authentication, dataset upload, and strict cross-user data isolation:

1. **Register User A:**
   - Navigate to `http://localhost:5173/login` (or `http://127.0.0.1:3000/login` in Docker).
   - Switch to **Create Account**.
   - Email: `alice@example.com`, Username: `alice_analyst`, Password: `Password123!`
   - Click **Create Account**. Notice you are logged in and redirected to the Workspace. Topbar displays `alice_analyst`.

2. **Upload Dataset as User A:**
   - Go to **Datasets** tab.
   - Click **Upload Dataset** and upload a CSV (e.g., `company_sales.csv`).
   - Confirm the dataset status is `ready` and preview the schema and rows.

3. **Log Out User A:**
   - Click the **Sign Out** button in the top right corner.
   - Confirm you are returned to the login screen and session storage is cleared.

4. **Register User B:**
   - Switch to **Create Account**.
   - Email: `bob@example.com`, Username: `bob_researcher`, Password: `Password123!`
   - Click **Create Account**. Topbar now displays `bob_researcher`.

5. **Verify Data Isolation:**
   - Go to **Datasets** tab.
   - Notice that User B's dataset table is completely empty. User A's dataset is not visible.
   - Go to **Query History** tab. User B has 0 historical queries.
   - Direct API attempts by User B to access User A's dataset ID return `HTTP 404 Not Found`.

---

## 7. Security Architecture

### Dual Database Roles
```
+-----------------------------------------------------------------------------------+
|                                  PostgreSQL 17                                    |
|                                                                                   |
|  +-------------------------------------+   +------------------------------------+ |
|  |             schema "app"            |   |       schema "uploaded_data"       | |
|  |  - app_users                        |   |  - dataset_<id_1>                  | |
|  |  - app_datasets                     |   |  - dataset_<id_2>                  | |
|  |  - app_dataset_tables               |   |  - ...                             | |
|  |  - app_dataset_columns              |   |                                    | |
|  |  - app_queries                      |   |                                    | |
|  |  - app_query_turns                  |   |                                    | |
|  +-------------------------------------+   +------------------------------------+ |
|                     ^                                         ^                   |
|                     | ALL PRIVILEGES                          | USAGE + SELECT    |
|                     |                                         |                   |
|            [ appuser (Admin) ]                    [ readonly_user (Exec) ]        |
|          - Migrations & Metadata                 - Dynamic user queries only     |
|          - DDL on uploaded_data                  - REVOKE ALL ON SCHEMA app       |
|          - User credential storage               - ZERO mutation privileges       |
+-----------------------------------------------------------------------------------+
```

1. **`appuser` (Application Admin Role):**
   - Owns schemas `app` and `uploaded_data`.
   - Used by FastAPI for schema migrations, user registrations, metadata tracking, and creating/dropping dynamic dataset tables.
2. **`readonly_user` (Execution Role):**
   - Dedicated connection used strictly when executing user-generated SQL.
   - Granted `USAGE` on schema `uploaded_data` and `SELECT` on all tables in `uploaded_data`.
   - **Explicitly revoked from schema `app`** (`REVOKE ALL ON SCHEMA app FROM readonly_user`).
   - Has zero mutating privileges (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `DROP`, `CREATE`, `ALTER`).

### AST Validation Policy (SQLGlot)
Before any SQL statement is sent to the database, it undergoes rigorous AST inspection:
- **Single Statement Enforcement:** Statements containing semicolons or multiple AST trees are rejected.
- **Comment Rejection:** Block comments (`/* ... */`) and line comments (`-- ...`) are rejected outright to prevent comment-based evasion.
- **Read-Only Verification:** Statement must be a single `SELECT` or a safe CTE (`WITH ... AS (SELECT ...)`). Any mutation (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `COPY`, `EXECUTE`) is rejected.
- **Table Allowlist:** References are strictly restricted to the authorized dataset table in schema `uploaded_data`. References to `app`, `information_schema`, or `pg_catalog` are rejected.
- **Column Allowlist:** All referenced column names must exist in the registered dataset metadata or be defined CTE aliases. PostgreSQL system columns (`ctid`, `xmin`, `xmax`, etc.) are forbidden.
- **Function Allowlist:** Only explicitly approved analytical and scalar functions (`count`, `sum`, `avg`, `min`, `max`, `round`, `coalesce`, `date_trunc`, `lower`, `upper`, etc.) are permitted. File system functions, administrative functions, and system setting calls are rejected.
- **Automatic Qualification:** Unqualified table references are deterministically rewritten to `uploaded_data.{target_table_name}`.

---

## 8. Verification & Testing Commands

### Backend Test Suite
Run all 93 unit, integration, authentication, security, and end-to-end tests:
```powershell
cd backend
.\.venv\Scripts\pytest.exe -v
```

Targeted suites:
```powershell
# Authentication & production security tests (10 tests)
pytest -v tests/test_auth_and_security.py

# End-to-end user story lifecycle tests (15 tests)
pytest -v tests/test_end_to_end_scenarios.py

# Automated accessibility markup verification (6 tests)
pytest -v tests/test_accessibility_markup.py

# SQL AST validation and safety tests
pytest -v tests/test_sql_safety_and_execution.py

# Ingestion pipeline and boundary tests
pytest -v tests/test_upload_pipeline.py
```

### Frontend Production Build
Validate TypeScript typings and build static assets:
```powershell
cd frontend
npm run build
```

---

## 9. Implementation Roadmap

- [x] **Phase 01:** Foundation, Infrastructure & Application Shell (`phase/01-foundation-scaffold`)
- [x] **Phase 02:** Dataset Upload & Schema Ingestion Pipeline (`phase/02-dataset-pipeline`)
- [x] **Phase 03:** Intent Classification & Clarification Workflow (`phase/03-query-classification-clarification`)
- [x] **Phase 04:** Schema-Grounded SQL Generation, SQLGlot Validation & Safe Execution (`phase/04-sql-generation-execution`)
- [x] **Phase 05:** Results Presentation, Query History & Suggested Queries (`phase/05-query-history-suggestions`)
- [x] **Phase 06:** End-to-End Hardening, Accessibility, Security Testing & Documentation (`phase/06-hardening-testing`)
- [x] **Phase 07:** Authentication, Production Security & Demo Deployment (`phase/07-auth-deployment-security`)

---

## 10. Known Limitations & Production Hosting Tasks

1. **TLS / HTTPS Termination:** In local development and Docker Compose, HTTP is used. For public internet deployments, a reverse proxy (e.g., Caddy, Traefik, or AWS ALB) must terminate HTTPS with valid TLS certificates, enabling `Secure` flags on all cookies.
2. **Reverse Proxy Headers:** When deployed behind reverse proxies, configure `Uvicorn` with `--proxy-headers` and `--forwarded-allow-ips` to preserve client IP addresses for rate limiting.
3. **Multi-Instance Rate Limiting:** The current rate limiter operates in-memory for single-process deployments. For multi-node distributed clusters, integrate Redis or PostgreSQL-backed token bucket tracking.
4. **Token Revocation (Denylist):** JWT tokens expire after 24 hours. For instantaneous session revocation prior to expiration, maintain an active token blocklist in Redis or database sessions.
