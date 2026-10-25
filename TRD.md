# Technical Requirements Document (TRD)
## Clarification-Driven Conversational Text-to-SQL

**Version:** 3.0  
**Status:** Updated baseline  
**Last updated:** 2026-10-24

## 1. Architecture Decisions

- **Frontend:** React + Vite + TypeScript.
- **Styling:** Tailwind CSS.
- **Icons:** Lucide React only.
- **UI construction:** project-owned reusable components using native/semantic HTML; no external component libraries.
- **Frontend API calls:** native `fetch`.
- **Frontend routing:** React Router.
- **Backend:** Python + FastAPI, running locally during initial development.
- **LLM:** Gemini API, called externally from the backend.
- **Workflow orchestration:** LangGraph inside the FastAPI process.
- **Database:** PostgreSQL in Docker during initial development.
- **File parsing:** Pandas + openpyxl.
- **Database access/import:** SQLAlchemy + psycopg.
- **SQL parsing:** SQLGlot plus independent safety policy checks.
- **API and LLM output validation:** Pydantic.
- **Tests:** pytest for backend; frontend test tooling can be selected when implementation begins.
- **Redis:** not used in the initial version.

## 2. Technology Stack

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend runtime | React + Vite | Browser application and development server |
| Frontend language | TypeScript | Typed UI and API contracts |
| Styling | Tailwind CSS | Responsive layouts and design tokens |
| Icons | Lucide React | Consistent interface icons |
| UI primitives | Native HTML + custom components | Forms, buttons, tables, dialogs, status states |
| Client routing | React Router | Workspace, datasets, and query history navigation |
| API transport | `fetch` | HTTP requests to FastAPI |
| API | FastAPI | Upload endpoints, query endpoints, orchestration |
| LLM | Gemini API | Classification, clarification generation, rewriting, SQL generation/repair |
| Workflow | LangGraph | Conditional routing and multi-turn state transitions |
| File parsing | Pandas + openpyxl | CSV/XLSX validation and parsing |
| Database | PostgreSQL | Imported records and application metadata |
| DB client | SQLAlchemy + psycopg | Import, metadata persistence, query execution |
| SQL validation | SQLGlot + policy layer | Parse SQL, check statement/identifiers and enforce allowlist |
| Structured validation | Pydantic | Validate API inputs and structured model output |
| Containers | Docker Compose | Local PostgreSQL service and persistent volume |
| Backend tests | pytest | Unit, integration, workflow, and security tests |

## 3. Runtime Architecture

```text
Browser
  React + Vite + TypeScript
  Tailwind CSS + native/custom components + Lucide React
  React Router + fetch
        |
        | HTTP/JSON and file upload
        v
FastAPI (local Python process)
  ├── Dataset API
  │    ├── File validation
  │    ├── Pandas/openpyxl parsing
  │    ├── Type inference and header normalization
  │    └── SQLAlchemy/psycopg import
  ├── Query API
  │    └── LangGraph workflow
  │         ├── Input validation
  │         ├── Relevance/safety/category classification
  │         ├── Schema-grounded answerability check
  │         ├── Ambiguity detection
  │         ├── Clarification and query rewriting
  │         ├── SQL generation
  │         ├── SQLGlot + policy validation
  │         ├── Read-only execution
  │         └── Bounded repair and revalidation
  ├── Dataset metadata / ownership service
  └── Query history service
        |
        ├── Gemini API (external HTTPS request)
        |
        v
PostgreSQL (Docker Compose)
  ├── Application metadata tables
  └── Controlled schema for uploaded dataset tables
```

Gemini API keys remain server-side. The browser never receives database credentials or the LLM API key.

## 4. Development and Deployment

### 4.1 Initial local development

- Run PostgreSQL in Docker Compose.
- Run FastAPI locally in a Python environment.
- Run the React/Vite frontend locally.
- Configure the frontend API base URL to point to FastAPI.
- Connect local FastAPI to PostgreSQL through `localhost:5432`.
- Keep secrets in environment variables and an ignored `.env` file.

### 4.2 PostgreSQL Compose baseline

```yaml
services:
  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
```

Use a local `.env` file that is excluded from version control. Do not commit real credentials. The host port is bound to loopback for local development. If FastAPI is later moved into the same Compose network, use the service hostname `postgres` rather than `localhost`.

### 4.3 Environment configuration

Expected configuration values include:

```env
POSTGRES_DB=text2sql
POSTGRES_USER=appuser
POSTGRES_PASSWORD=replace_with_local_secret
DATABASE_URL=postgresql+psycopg://appuser:replace_with_local_secret@localhost:5432/text2sql
GEMINI_API_KEY=replace_with_server_side_secret
FRONTEND_ORIGIN=http://localhost:5173
MAX_UPLOAD_MB=20
MAX_UPLOAD_ROWS=100000
MAX_UPLOAD_COLUMNS=250
QUERY_TIMEOUT_SECONDS=10
MAX_RESULT_ROWS=1000
```

These are development defaults to tune after benchmarking. Use a URL-safe password or encode reserved URL characters correctly in `DATABASE_URL`.

## 5. Suggested Repository Structure

```text
text-to-sql/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── App.tsx
│   │   │   └── router.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── AppLayout.tsx
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   └── Topbar.tsx
│   │   │   ├── datasets/
│   │   │   │   ├── DatasetUpload.tsx
│   │   │   │   ├── DatasetCard.tsx
│   │   │   │   ├── SchemaViewer.tsx
│   │   │   │   └── DatasetPreview.tsx
│   │   │   ├── query/
│   │   │   │   ├── QueryInput.tsx
│   │   │   │   ├── ChatMessage.tsx
│   │   │   │   ├── ClarificationCard.tsx
│   │   │   │   ├── QueryStatus.tsx
│   │   │   │   ├── ResultsTable.tsx
│   │   │   │   ├── SQLViewer.tsx
│   │   │   │   └── ExplanationPanel.tsx
│   │   │   └── common/
│   │   │       ├── Button.tsx
│   │   │       ├── EmptyState.tsx
│   │   │       └── ErrorMessage.tsx
│   │   ├── pages/
│   │   │   ├── WorkspacePage.tsx
│   │   │   ├── DatasetsPage.tsx
│   │   │   └── QueryHistoryPage.tsx
│   │   ├── api/
│   │   │   └── client.ts
│   │   ├── types/
│   │   │   └── api.ts
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── upload_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── schema_service.py
│   │   │   ├── sql_service.py
│   │   │   └── query_service.py
│   │   └── workflows/
│   │       └── text_to_sql_graph.py
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
├── docker-compose.yml
├── .gitignore
└── README.md
```

This is a proposed structure, not a requirement to create all files immediately. Keep components cohesive and avoid making every tiny visual element a separate file without a reuse benefit.

## 6. Dataset Upload Pipeline

1. Receive a multipart upload at the dataset API.
2. Validate extension, MIME/content, size, and upload limits. Do not trust the filename or browser-provided MIME type alone.
3. Parse CSV/XLSX using Pandas and openpyxl.
4. Reject empty files, invalid sheets, malformed headers, duplicate normalized headers, unsupported values, and limit violations with structured errors.
5. Normalize column names to safe, unique internal names while retaining original display names in metadata.
6. Infer safe PostgreSQL types from observed values. Use conservative types when inference is uncertain.
7. Generate a backend-controlled dataset/table identifier. Never use raw filenames or LLM-provided identifiers as SQL identifiers.
8. Create/import the physical table within a controlled schema and transaction where practical.
9. Register dataset ownership, original filename, row count, timestamps, table mapping, and column metadata.
10. Return a dataset ID and import summary.
11. On failure, roll back or remove partial tables and metadata.

Do not send the full file to Gemini for routine querying. Supply authorized schema information and, only when useful and permitted, a limited sample of values.

## 7. Query Classification Contract

Use Pydantic to validate a structured classification result. Suggested fields:

```json
{
  "category": "RELEVANT_CLEAR",
  "confidence": 0.91,
  "reason": "The requested filter can be expressed using available columns.",
  "missing_fields": [],
  "ambiguities": [],
  "clarification_question": null
}
```

Allowed categories:

- `RELEVANT_CLEAR`
- `RELEVANT_AMBIGUOUS`
- `RELEVANT_UNANSWERABLE`
- `OUT_OF_SCOPE`
- `NONSENSICAL`
- `IMPROPER_OR_UNSAFE`

The confidence value is advisory, not an authorization or execution decision. Apply deterministic policy checks alongside model output. A missing field does not by itself imply nonsense or out-of-scope intent.

## 8. LangGraph Workflow

Recommended logical flow:

```text
START
  |
Validate request and authorize dataset
  |
Classify intent / relevance / safety
  ├── IMPROPER_OR_UNSAFE -> Refuse safely
  ├── NONSENSICAL -> Ask user to rephrase
  ├── OUT_OF_SCOPE -> Explain scope and stop
  ├── RELEVANT_UNANSWERABLE -> Explain missing data and stop
  ├── RELEVANT_AMBIGUOUS -> Ask clarification -> Store answer
  |                                        |
  |                              Rewrite/refine question
  |                                        |
  |                              Reclassify (bounded loop)
  |
  └── RELEVANT_CLEAR
          |
      Select authorized schema context
          |
      Generate SQL
          |
      Validate SQL and policy
          ├── Invalid -> bounded repair -> revalidate
          └── Valid
                |
          Execute read-only query
                |
          Handle execution error
                ├── bounded repair -> revalidate -> retry
                └── safe failure
                |
          Format results + explanation
                |
               END
```

The graph state should include query ID, authorized dataset ID, original question, clarification turns, refined question, classification, schema context, candidate SQL, validation findings, execution status, bounded result rows, and user-facing explanation. Do not store API keys or credentials in graph state.

Clarification and SQL repair must have explicit maximum attempt counts to prevent loops. Persist multi-turn state through application storage/checkpointing as needed; Redis is not part of the initial architecture.

## 9. SQL Safety and Execution

SQLGlot is a parser and analysis tool, not a complete security boundary. Enforce all of the following:

- Parse SQL and require exactly one permitted statement.
- Permit only an approved read-only query form (initially SELECT, with carefully reviewed support for safe CTEs).
- Reject INSERT, UPDATE, DELETE, MERGE, DDL, transaction control, COPY, administrative commands, and multiple statements.
- Reject unauthorized schemas/tables and unapproved functions.
- Resolve dataset ownership and table mapping in backend code; do not trust LLM-provided table identifiers.
- Execute using a separate least-privilege database role restricted to approved read access.
- Apply statement timeout, row cap, and request limits.
- Parameterize values where possible; validate identifiers against backend metadata.
- Avoid exposing raw database errors, credentials, prompts, or stack traces to users.
- Re-validate every repaired SQL candidate before execution.
- Log security-relevant decisions without logging secrets or unnecessary personal data.

Authorization is enforced by the backend and database privileges, never by the LLM.

## 10. Frontend Component and Page Requirements

### Application shell
- `AppLayout`, `Sidebar`, `Topbar`
- Sidebar navigation: Workspace, Datasets, Query History
- Active dataset selector/list
- Responsive collapsible navigation

### Workspace
- `ChatMessage`, `QueryInput`, `SuggestedQuestions`
- `QueryStatus` and loading states
- `ClarificationCard` with options and free-text response
- Inline out-of-scope, missing-data, unsafe-request, and error responses

### Dataset management
- `DatasetUpload`, `UploadProgress`, `DatasetCard`
- `SchemaViewer`, `DatasetPreview`
- Delete confirmation and import status

### Results
- `ResultSummary`, `ResultsTable`, `TablePagination`
- `SQLViewer` with copy action
- `ExplanationPanel`
- `ExportResults` for CSV

### History
- `QueryHistory`, `HistoryDetail`

### UI implementation constraints
- React + Vite + TypeScript and Tailwind CSS.
- Lucide React is the only icon pack.
- Use native semantic HTML and project-owned components; do not add third-party component libraries.
- Use `fetch` for API calls initially.
- Use React Router for page navigation.
- Provide loading, empty, success, and error states.
- Use accessible labels, keyboard interactions, visible focus rings, and accessible names for icon-only buttons.
- Do not treat client-side controls as a security boundary.

## 11. API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/datasets` | Upload/import CSV or XLSX |
| `GET` | `/api/datasets` | List authorized datasets |
| `GET` | `/api/datasets/{dataset_id}` | Retrieve dataset metadata |
| `GET` | `/api/datasets/{dataset_id}/schema` | Retrieve column metadata |
| `GET` | `/api/datasets/{dataset_id}/preview` | Retrieve bounded preview rows |
| `DELETE` | `/api/datasets/{dataset_id}` | Delete authorized dataset and imported table |
| `POST` | `/api/queries` | Submit a natural-language query |
| `POST` | `/api/queries/{query_id}/clarifications` | Submit clarification answer |
| `GET` | `/api/queries` | List authorized query history |
| `GET` | `/api/queries/{query_id}` | Retrieve query status, SQL, explanation, and results |

Use Pydantic request/response models, consistent error envelopes, request IDs, and explicit status fields. For long-running requests, the implementation may return a query ID and expose status polling; choose synchronous versus asynchronous behavior based on measured response time.

## 12. Frontend API and State Handling

- Centralize the API base URL and `fetch` wrapper in `frontend/src/api/client.ts`.
- Handle JSON and multipart uploads correctly; do not manually set multipart `Content-Type` when using `FormData`.
- Validate and type API responses at the boundary.
- Keep UI state such as open dialogs and input text in React component/hooks.
- Keep server-derived datasets, query status, clarifications, and results associated with the relevant dataset/query IDs.
- Disable duplicate submissions while a request is in flight.
- Preserve the conversation context required to answer a clarification.
- Display user-safe error messages and keep diagnostic details in server logs.
- Avoid putting secrets in Vite environment variables; client-exposed variables are public.

## 13. Testing Strategy

### Backend
- File parsing, header normalization, type inference, and import rollback.
- Classification across all categories.
- Ambiguity clarification and multi-turn state handling.
- SQL parsing, allowlist checks, unauthorized table access, mutation rejection, and multiple-statement rejection.
- Row caps, query timeout, and bounded repair loops.
- Dataset ownership and deletion cleanup.
- API response contracts and error handling.

### Frontend
- Upload success/failure states.
- Dataset selection and schema preview.
- Clear question submission and query progress.
- Clarification display and answer submission.
- Result table, SQL copy, CSV export, and history navigation.
- Keyboard accessibility, responsive layout, and error states.

### End-to-end
- Upload a known fixture, ask a clear question, and compare output to expected rows.
- Ask an ambiguous question and verify no SQL executes before clarification.
- Ask for a missing field and verify the system explains the limitation.
- Ask an out-of-scope or unsafe question and verify no query executes.
- Verify unauthorized dataset IDs cannot be queried.

## 14. Implementation Milestones

1. **Foundation:** repository, environment configuration, Docker PostgreSQL, FastAPI health endpoint, React/Vite/Tailwind scaffold.
2. **Dataset pipeline:** upload validation, PostgreSQL import, metadata/schema endpoints, dataset list and preview UI.
3. **Query workflow:** LangGraph classification, schema context, clarification turn handling, Gemini integration.
4. **SQL safety:** SQLGlot validation, read-only role, timeouts, row limits, bounded repair.
5. **Results and history:** result table, SQL viewer, explanation, CSV export, history endpoints and screens.
6. **Hardening:** unit/integration tests, accessibility, responsive behavior, error handling, documentation.

## 15. Deferred Decisions

- Authentication provider and exact ownership/session model.
- Persistent LangGraph checkpoint implementation.
- Frontend test framework and visual testing setup.
- Whether to add a dedicated server-state library.
- Whether to Dockerize FastAPI and the frontend after local development.
- Production hosting, logging/monitoring, and rate limiting strategy.
