# Product Requirements Document (PRD)
## Clarification-Driven Conversational Text-to-SQL

**Version:** 3.0  
**Status:** Updated baseline  
**Last updated:** 2026-10-24

## 1. Product Summary

Build a conversational data assistant that lets users upload CSV/XLSX files and ask questions about the uploaded data in natural language. The system checks whether a question is meaningful, in scope, answerable from the selected dataset, and sufficiently unambiguous before generating SQL. When a question is ambiguous, it asks a targeted clarification and continues the same conversation. It validates and executes read-only SQL against PostgreSQL and explains the returned results.

The application will use a custom React interface styled with Tailwind CSS. UI components will be built from native HTML elements and project-owned components; Lucide React is the only permitted icon pack.

## 2. Problem Statement

Users who do not know SQL need a reliable way to explore structured data. A naïve text-to-SQL system may guess what vague words mean, query columns that do not exist, or try to answer unrelated questions. The product must distinguish ambiguity from missing data and irrelevant input, ask follow-up questions when needed, and prevent unsafe SQL from running.

## 3. Goals

- Allow users to upload CSV and XLSX datasets.
- Show dataset import status, schema, and a sample preview.
- Let users select a dataset and ask natural-language questions.
- Classify questions before SQL generation.
- Ask targeted clarifying questions for ambiguous requests.
- Explain when a question is out of scope or cannot be answered from the available data.
- Generate schema-grounded, read-only SQL and validate it before execution.
- Display tabular results, generated SQL, and a plain-English explanation.
- Provide query history for the current application scope.
- Make errors understandable and recoverable.
- Keep datasets isolated by owner/session according to the implemented authentication model.

## 4. Non-Goals for the Initial Release

- General-purpose chat unrelated to the selected dataset.
- INSERT, UPDATE, DELETE, DDL, or other mutating SQL generated from user prompts.
- Uploading SQL scripts or arbitrary database dumps.
- Support for formats beyond CSV and XLSX.
- Redis, real-time collaboration, or multi-user editing.
- Charts, dashboards, or advanced data visualization.
- Multiple database engines or user-configured database connections.
- Running Gemini locally or inside Docker.
- A full enterprise role/permission administration console.

## 5. Target Users

- Students and researchers exploring structured datasets.
- Faculty or administrators querying data they are authorized to access.
- General users who have tabular CSV/XLSX data but do not know SQL.
- Developers/operators configuring the application and its safety limits.

## 6. Core User Stories

1. As a user, I can upload a CSV/XLSX file and see whether it was imported successfully.
2. As a user, I can inspect the dataset's columns, inferred types, and a sample of rows.
3. As a user, I can select a dataset and ask a natural-language question.
4. As a user, I receive results when my question is clear and answerable.
5. As a user, I am asked to clarify a question with multiple plausible meanings.
6. As a user, I can answer a clarification in the same conversation without repeating my original question.
7. As a user, I am told when a requested field or relationship is missing rather than receiving invented results.
8. As a user, I am told when a request is unrelated to the selected dataset.
9. As a user, I receive a useful response to gibberish or non-query input.
10. As a user, I can inspect the SQL that produced the results and copy it.
11. As a user, I can review previous queries and their statuses.
12. As a user, I cannot query datasets I am not authorized to access.

## 7. Query Categories and Expected Behavior

Each request is assigned a primary category:

- `RELEVANT_CLEAR`: meaningful, in scope, specific enough, and answerable. Continue to schema selection and SQL generation.
- `RELEVANT_AMBIGUOUS`: relevant but has multiple plausible interpretations. Ask a targeted clarification and pause final SQL execution.
- `RELEVANT_UNANSWERABLE`: meaningful and related to the dataset, but required columns, values, or relationships are absent. Explain the limitation.
- `OUT_OF_SCOPE`: asks about a domain not represented by the selected dataset. Politely decline and invite a dataset-related question.
- `NONSENSICAL`: gibberish or input that cannot reasonably be interpreted as a data question. Ask the user to rephrase.
- `IMPROPER_OR_UNSAFE`: requests destructive operations, unauthorized access, or disallowed behavior. Refuse the unsafe action.

A missing column alone must not automatically make a request nonsensical or out of scope. For example, “Show internship ratings” against a student dataset without an internship-rating field is generally `RELEVANT_UNANSWERABLE`; “Show employee payroll” against a student-only dataset is likely `OUT_OF_SCOPE`.

## 8. UI Technology and Design Decisions

### 8.1 Fixed frontend stack

| Area | Decision |
|---|---|
| Framework | React + Vite |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Icons | Lucide React only |
| UI components | Project-owned components built with semantic/native HTML |
| API requests | Native `fetch` |
| Client routing | React Router |
| Initial state handling | React hooks and local component/state modules; add a library only if needed |
| Forms | Native HTML forms and TypeScript validation |
| Backend | FastAPI |

Do not introduce component libraries such as shadcn/ui, Material UI, Chakra UI, or other external icon packs in the initial release. Tailwind CSS is a styling system, not a component library; reusable UI elements will be implemented in the project.

### 8.2 Application shell

- **Sidebar:** navigation links for Workspace, Datasets, and Query History; list/select available datasets; provide a collapse control on wider screens.
- **Topbar:** current page, active dataset context, and relevant actions.
- **Main content area:** page-specific workflow.
- **Responsive behavior:** sidebar collapses into a mobile navigation control; tables remain usable through horizontal scrolling.

### 8.3 Screens and components

**A. Workspace / conversational querying**
- `AppLayout`, `Sidebar`, `Topbar`
- `DatasetSelector`
- `ChatMessage` for user and assistant turns
- `QueryInput` with multiline entry and submit action
- `SuggestedQuestions` based on the selected dataset schema
- `QueryStatus` for classifying, clarifying, generating, executing, complete, and failed states
- `ClarificationCard` and `ClarificationOptions`
- `EmptyState` for a new workspace

**B. Dataset management**
- `DatasetUpload` for CSV/XLSX file selection and drag-and-drop
- `UploadProgress` and import status
- `DatasetCard` showing dataset name, row count, and column count
- `SchemaViewer` showing columns and inferred data types
- `DatasetPreview` showing a limited sample
- `DeleteDatasetDialog` for confirming dataset deletion

**C. Query results**
- `ResultSummary` showing row count and execution duration when available
- `ResultsTable` with horizontal overflow handling
- `TablePagination`
- `SQLViewer` with a copy action
- `ExplanationPanel` explaining the query and result in plain English
- `ExportResults` to download returned results as CSV

**D. Query history and response states**
- `QueryHistory` and `HistoryDetail`
- `ErrorMessage` with recovery guidance
- `OutOfScopeMessage`
- `MissingDataMessage`
- `UnsafeQueryMessage`

These names define responsibilities, not a requirement to create one file per component. Components should be split where it improves reuse and maintainability.

### 8.4 Visual and accessibility requirements

- Start with a light theme, neutral backgrounds, subtle borders, and one consistent accent color.
- Use spacing, typography, and contrast consistently through Tailwind theme tokens.
- Use semantic HTML, associated labels, keyboard-accessible controls, visible focus indicators, and meaningful accessible names for icon-only buttons.
- Do not communicate state using color alone; pair status colors with text/icons.
- Provide loading, empty, success, validation-error, and server-error states.
- Avoid presenting fabricated sample result counts as real results.

## 9. Functional Requirements

### Dataset upload and management
- Accept CSV and XLSX only in the first release.
- Enforce configurable file size, row, and column limits.
- Validate file contents, headers, duplicate column names, and inferred types.
- Use backend-generated safe identifiers for physical table/schema names.
- Import data transactionally and clean up partially created tables on failure.
- Register dataset ownership, source filename, timestamps, row count, and schema metadata.
- Expose schema and a limited preview through the API.
- Allow users to list and select only datasets they are authorized to access.

### Conversational querying
- Require an active dataset for data-specific questions.
- Classify relevance, ambiguity, answerability, and safety before SQL execution.
- Ask concise clarifications that distinguish plausible interpretations.
- Preserve original intent and clarification answers across turns.
- Re-evaluate the refined question after each clarification.
- Never silently guess when materially different interpretations remain.
- Provide a clear explanation when the data cannot answer a question.
- Limit the number of clarification and SQL-repair cycles.

### SQL generation and execution
- Supply Gemini with only the authorized schema context and minimal relevant metadata, not the entire uploaded file by default.
- Validate generated SQL with SQLGlot and independent policy checks.
- Permit only a single read-only query against authorized dataset tables and approved operations.
- Use a database role with least privilege for generated queries.
- Apply statement timeout, row limits, and other configurable resource limits.
- Never rely on the LLM or SQL parsing alone as the security boundary.
- If execution fails, allow bounded repair, then revalidate before retrying.
- Return structured errors rather than raw internal traces.

### Results and history
- Display results as a table with pagination or bounded result size.
- Display generated SQL and a plain-English explanation.
- Support copying SQL and exporting displayed/returned rows as CSV.
- Store or expose query history only within the configured ownership boundary.
- Do not expose secrets, database credentials, or sensitive internal prompts to the client.

## 10. High-Level API Expectations

- `POST /api/datasets` — upload and import a dataset.
- `GET /api/datasets` — list authorized datasets.
- `GET /api/datasets/{dataset_id}` — dataset metadata.
- `GET /api/datasets/{dataset_id}/schema` — columns and inferred types.
- `GET /api/datasets/{dataset_id}/preview` — bounded preview rows.
- `DELETE /api/datasets/{dataset_id}` — delete an authorized dataset and its imported data.
- `POST /api/queries` — submit a new question.
- `POST /api/queries/{query_id}/clarifications` — submit clarification response.
- `GET /api/queries` — list authorized query history.
- `GET /api/queries/{query_id}` — retrieve query details/results.

Exact request/response contracts are defined in the TRD and may evolve during implementation.

## 11. Acceptance Criteria

- A valid CSV/XLSX file imports and its schema is visible.
- Invalid or oversized files fail safely with an understandable message.
- A clear, answerable question returns results grounded in the selected dataset.
- An ambiguous question pauses and asks a targeted clarification.
- Clarification answers update the question and trigger re-evaluation.
- A relevant but unanswerable question explains which information is missing.
- Out-of-scope and nonsensical inputs do not trigger SQL execution.
- Unsafe/mutating SQL is rejected.
- Generated SQL is validated before every execution, including repairs.
- Dataset authorization is enforced by the backend.
- The UI exposes loading, empty, error, and success states.
- The UI works at desktop and mobile widths and is keyboard accessible.
- PostgreSQL data persists across container restarts using a named volume.

## 12. Success Metrics

- Correct routing across the query categories.
- Clarification usefulness and successful resolution rate.
- SQL execution success rate on supported questions.
- Result correctness against known test datasets.
- Unsafe-query rejection rate and authorization test pass rate.
- Upload success rate for valid supported files.
- Median response time for classification and query execution.
- Usability: users can upload a file, ask a question, clarify, and understand results without writing SQL.

## 13. Research Foundation

The project is motivated by research on ambiguous and unanswerable Text-to-SQL questions, conversational clarification, multi-turn Text-to-SQL, question rewriting, execution-guided refinement, and uncertainty-aware abstention. The implementation should retain the central design principle: clarify or abstain rather than inventing intent or unsupported data.

## 14. Deployment Baseline

- PostgreSQL runs in Docker Compose with a named persistent volume.
- During initial development, FastAPI runs locally and connects to the published PostgreSQL port.
- Gemini is accessed through its external API using a server-side secret.
- The frontend runs locally during development and calls FastAPI.
- Redis is not included.
- Dockerizing the backend/frontend can be considered after local development is stable.
