# Clarification-Driven Conversational Text-to-SQL

> **An Ambiguity-Aware Framework for Reliable Natural Language Database Querying**

---

## 1. Overview & Guiding Philosophy

This project implements a conversational data assistant for structured tabular datasets (CSV and XLSX). Rather than guessing ambiguous column filters, hallucinating non-existent database fields, or executing unsafe mutations, this framework adheres to a core design principle: **clarify or abstain rather than inventing intent or fabricating answers.**

### Key Architectural Highlights
- **Pre-execution Intent Gate:** Every natural language question is classified into one of six distinct categories before any SQL is generated (`RELEVANT_CLEAR`, `RELEVANT_AMBIGUOUS`, `RELEVANT_UNANSWERABLE`, `OUT_OF_SCOPE`, `NONSENSICAL`, `DANGEROUS_OR_OFFENSIVE`).
- **Structured Multi-Turn Clarification:** Ambiguous queries present structured clarification options and allow free-text responses, continuing in a multi-turn clarification loop bounded at three turns.
- **AST Security Policy:** All candidate SQL statements are parsed using SQLGlot, restricted to single read-only `SELECT` statements (and safe read-only CTEs), and validated against backend-registered table and column allowlists.
- **Least-Privilege Database Isolation:** Dynamic queries execute strictly under a dedicated PostgreSQL `readonly_user` role with statement timeouts (`5,000ms`), transaction read-only mode, and zero access to internal application schemas (`app`).
- **RFC 4180 Safe CSV Export:** Downloaded query results neutralize spreadsheet formula injection attacks (`=`, `+`, `-`, `@`, `\t`, `\r`) by prepending a single quote `'`.
- **Privacy & Grounding Guarantee:** LLM prompts consume authorized column metadata, inferred types, and low-cardinality category values. Uploaded row data is never transmitted to external providers.

---

## 2. Prerequisites

Ensure the following tools are installed on your machine:
- **Docker & Docker Compose** (Docker Desktop on Windows/macOS or Docker Engine on Linux)
- **Python 3.11+**
- **Node.js 18+ & npm**
- **Git**

---

## 3. Quick Start & Local Setup Runbook

Follow these step-by-step instructions to set up the complete stack locally.

### Step 1: Start PostgreSQL in Docker
Start the isolated PostgreSQL 17 container:
```bash
docker-compose up -d
```
Verify the container is healthy:
```bash
docker ps --filter "name=text2sql_postgres"
```
The database listens on loopback: `127.0.0.1:5432`.

> [!IMPORTANT]
> **PostgreSQL Dual-Role Initialization Notice:**
> The initialization script at `docker/init-db.sql` automatically provisions:
> 1. `appuser` (Application administrative role owning schemas `app` and `uploaded_data`).
> 2. `readonly_user` (Execution role granted read-only `SELECT` strictly on `uploaded_data` tables with access explicitly revoked from schema `app`).
>
> If you make changes to `docker/init-db.sql` on an **existing** database container, re-apply permissions using:
> ```bash
> docker exec -i text2sql_postgres psql -U appuser -d text2sql < docker/init-db.sql
> ```

---

### Step 2: Configure Environment Variables
Copy the example environment configuration:
```bash
# Windows PowerShell
copy backend\.env.example backend\.env

# Linux / macOS
cp backend/.env.example backend/.env
```

Review and adjust settings in `backend/.env` as needed:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | String | `postgresql+psycopg://appuser:local_dev_password@127.0.0.1:5432/text2sql` | Connection string for metadata management, migrations, and table provisioning. |
| `READONLY_DATABASE_URL` | String | `postgresql+psycopg://readonly_user:readonly_dev_password@127.0.0.1:5432/text2sql` | Dedicated connection string for executing user-generated SQL. |
| `GEMINI_API_KEY` | String | `placeholder_key` | Google Gemini API key for intent classification and SQL generation. |
| `FRONTEND_ORIGIN` | String | `http://localhost:5173` | Allowed CORS origin for the Vite frontend. |
| `MAX_UPLOAD_MB` | Integer | `20` | Maximum file upload size in megabytes. |
| `MAX_UPLOAD_ROWS` | Integer | `100000` | Maximum number of rows allowed in an uploaded dataset. |
| `MAX_UPLOAD_COLUMNS` | Integer | `250` | Maximum number of columns allowed in an uploaded dataset. |
| `QUERY_TIMEOUT_SECONDS` | Integer | `10` | Server-side execution timeout for dynamic queries. |
| `MAX_RESULT_ROWS` | Integer | `1000` | Hard cap on row results persisted and returned to the client. |
| `DEFAULT_OWNER_ID` | String | `default_user` | Fallback user identity for development mock auth. |

---

### Step 3: Set Up and Run the Backend
1. Create and activate a Python 3.11 virtual environment:
   ```bash
   # Windows PowerShell
   py -3.11 -m venv backend\.venv
   .\backend\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3.11 -m venv backend/.venv
   source backend/.venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Run database migrations to provision the metadata schema:
   ```bash
   cd backend
   alembic upgrade head
   cd ..
   ```

4. Launch the FastAPI server:
   ```bash
   cd backend
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   - Interactive Swagger API docs: `http://127.0.0.1:8000/docs`
   - Health check: `http://127.0.0.1:8000/api/health`

---

### Step 4: Set Up and Run the Frontend
1. Open a new terminal and navigate to `frontend`:
   ```bash
   cd frontend
   npm install
   ```

2. Start the Vite development server:
   ```bash
   npm run dev
   ```
   Open your browser to: `http://localhost:5173`

---

## 4. Security & Safety Model

### Dual Database Roles
```
+-----------------------------------------------------------------------------------+
|                                  PostgreSQL 17                                    |
|                                                                                   |
|  +-------------------------------------+   +------------------------------------+ |
|  |             schema "app"            |   |       schema "uploaded_data"       | |
|  |  - app_datasets                     |   |  - tbl_<dataset_id_1>              | |
|  |  - app_dataset_tables               |   |  - tbl_<dataset_id_2>              | |
|  |  - app_dataset_columns              |   |  - ...                             | |
|  |  - app_queries                      |   |                                    | |
|  |  - app_query_turns                  |   |                                    | |
|  +-------------------------------------+   +------------------------------------+ |
|                     ^                                         ^                   |
|                     | ALL PRIVILEGES                          | USAGE + SELECT    |
|                     |                                         |                   |
|            [ appuser (Admin) ]                    [ readonly_user (Exec) ]        |
|          - Migrations & Metadata                 - Dynamic user queries only     |
|          - DDL on uploaded_data                  - REVOKE ALL ON SCHEMA app       |
|          - Table provisioning                    - ZERO mutation privileges       |
+-----------------------------------------------------------------------------------+
```

1. **`appuser` (Application Admin Role):**
   - Owns schemas `app` and `uploaded_data`.
   - Used by FastAPI for schema migrations, metadata tracking, and creating/dropping dynamic dataset tables.
2. **`readonly_user` (Execution Role):**
   - Dedicated connection used strictly when executing user-generated SQL.
   - Granted `USAGE` on schema `uploaded_data` and `SELECT` on all tables in `uploaded_data`.
   - **Explicitly revoked from schema `app`** (`REVOKE ALL ON SCHEMA app FROM readonly_user`).
   - Has zero mutating privileges (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `DROP`, `CREATE`, `ALTER`).
   - Inherited and `PUBLIC` privileges on `app` and `uploaded_data` are revoked to eliminate privilege leakage.

### AST Validation Policy (SQLGlot)
Before any SQL statement is sent to the database, it undergoes rigorous AST inspection:
- **Single Statement Enforcement:** Statements containing semicolons or multiple AST trees are rejected.
- **Comment Rejection:** Block comments (`/* ... */`) and line comments (`-- ...`) are rejected outright to prevent comment-based evasion.
- **Read-Only Verification:** Statement must be a single `SELECT` or a safe CTE (`WITH ... AS (SELECT ...)`). Any mutation (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `COPY`, `EXECUTE`) is rejected.
- **Table Allowlist:** References are strictly restricted to the authorized dataset table in schema `uploaded_data`. References to `app`, `information_schema`, or `pg_catalog` are rejected.
- **Column Allowlist:** All referenced column names must exist in the registered dataset metadata or be defined CTE aliases. PostgreSQL system columns (`ctid`, `xmin`, `xmax`, etc.) are forbidden.
- **Function Allowlist:** Only explicitly approved analytical and scalar functions (`count`, `sum`, `avg`, `min`, `max`, `round`, `coalesce`, `date_trunc`, `lower`, `upper`, etc.) are permitted. File system functions, administrative functions, and system setting calls are rejected.
- **Automatic Qualification:** Unqualified table references are deterministically rewritten to `uploaded_data.{target_table_name}`.

### Authentication Status & Development Model
- **Current Model:** Local development uses a mock identity (`owner_id = 'default_user'`), overrideable via the `X-User-ID` HTTP header.
- **Explicit Limitation:** **This model is strictly intended for local development and testing. It does NOT provide session encryption, multi-tenant authentication, or production authorization.**
- **Production Requirement:** A verified authentication provider (OAuth2 / JWT / session tokens) must be integrated prior to deploying into shared or multi-user environments.

---

## 5. Verification & Testing Commands

### Backend Test Suite
Run all 74 unit, integration, security, and end-to-end tests:
```bash
cd backend
.\.venv\Scripts\pytest.exe -v
```

Run targeted suites:
```bash
# End-to-end user story lifecycle tests (15 tests)
pytest -v tests/test_end_to_end_scenarios.py

# Automated accessibility markup verification (6 tests)
pytest -v tests/test_accessibility_markup.py

# SQL AST validation and safety tests
pytest -v tests/test_sql_safety_and_execution.py

# Query classification and multi-turn clarification tests
pytest -v tests/test_classification_workflow.py

# Ingestion pipeline and boundary tests
pytest -v tests/test_upload_pipeline.py
```

### Frontend Production Build
Validate TypeScript typings and build static assets:
```bash
cd frontend
npm run build
```

---

## 6. Implementation Roadmap

- [x] **Phase 01:** Foundation, Infrastructure & Application Shell (`phase/01-foundation-scaffold`)
- [x] **Phase 02:** Dataset Upload & Schema Ingestion Pipeline (`phase/02-dataset-pipeline`)
- [x] **Phase 03:** Intent Classification & Clarification Workflow (`phase/03-query-classification-clarification`)
- [x] **Phase 04:** Schema-Grounded SQL Generation, SQLGlot Validation & Safe Execution (`phase/04-sql-generation-execution`)
- [x] **Phase 05:** Results Presentation, Query History & Suggested Queries (`phase/05-query-history-suggestions`)
- [ ] **Phase 06:** End-to-End Hardening, Accessibility, Security Testing & Documentation (`phase/06-hardening-testing`)

---

## 7. API Reference
Complete endpoint contracts, request/response models, query parameters, error responses, and headers are documented in [docs/API.md](docs/API.md).
