# Feature Specification: Compass — AI-Assisted Internal Assistant

**Feature Branch**: `001-compass`

**Created**: 2026-06-15

**Status**: Draft

**Input**: Build Brief for Compass (see `brief.md` in this directory for the verbatim source).

## Overview

Compass is an AI-assisted internal company assistant with two pillars:

1. **Document search (main feature)** — staff find policies and how-to guides by *meaning*
   (not by document code), and get answers grounded in the source with inline citations.
2. **ERP/data assistant via a SQL catalog** — an in-app chat widget answers questions about
   company data (leave balances, salary distributions, headcount, etc.) by selecting from a
   fixed catalog of safe, pre-approved parameterized queries. The LLM never writes raw SQL.

It is role-aware (superuser / hr / mgr / emp). Standalone academic project on synthetic data
only. The defining constraint: **the LLM is never trusted as a security boundary** — every
consequential action is gated by deterministic backend checks (see Constitution).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Document search by meaning with grounded answers (Priority: P1)

Any authenticated staff member opens the Document Search page, types a question in plain
language (not a doc code), and either gets a ranked list of relevant source chunks
(Analyze=OFF) or a grounded, cited answer (Analyze=ON). Retrieval is hybrid (keyword +
vector + RRF fusion) then reranked by a cross-encoder.

**Why this priority**: This is the headline feature and the most-used path for every role.
It is independently demonstrable and delivers value on its own.

**Independent Test**: With a small ingested corpus, search "how much annual leave do new
joiners get" and confirm (a) OFF returns ranked chunks with doc_code+page+score; (b) ON
returns a markdown answer with inline citations that refer only to retrieved chunks, and
refuses when evidence is weak. Status line shows model · hybrid · reranked · N retrieved · k cited · latency.

**Acceptance Scenarios**:

1. **Given** a ready corpus, **When** an emp searches a natural-language question with
   Analyze=OFF, **Then** the system returns ranked chunks each with snippet, doc_code, page, score.
2. **Given** Analyze=ON and strong evidence, **When** any role searches, **Then** the answer
   is grounded markdown with inline citations (doc_code + page), and every citation maps to an
   actually-retrieved chunk.
3. **Given** Analyze=ON and weak/absent evidence, **When** a user searches, **Then** the
   system refuses cleanly rather than hallucinating.
4. **Given** an identical repeat search by the same role/scope, **When** submitted within the
   cache TTL, **Then** it returns from cache without re-calling embeddings/LLM.

---

### User Story 2 - Role-scoped data questions via SQL catalog (Priority: P1)

A user asks the chat widget a data question (e.g. HR: "how many annual leave days does
employee 1 have left?"). The LLM selects a catalog id and extracts params; the backend
validates the id and params, enforces the user's role and scope, runs the parameterized
query, and returns a plain-language answer.

**Why this priority**: This is the second core pillar and the primary security story. It is
independently demonstrable once auth, schema, and the catalog exist.

**Independent Test**: As hr, ask for any employee's leave balance → correct answer. As emp,
ask for another employee's balance → refused/scoped to self. Confirm the LLM output is only
`{catalog_id, params}` and is schema-validated before any query runs.

**Acceptance Scenarios**:

1. **Given** an hr user, **When** they ask a company-scope data question, **Then** the backend
   runs the mapped parameterized query and returns an NL answer.
2. **Given** an emp user asking about another employee, **When** the request is processed,
   **Then** the backend refuses or restricts to self-scope regardless of LLM output.
3. **Given** any data question, **When** the LLM responds, **Then** its output is strict JSON
   validated against schema and the allowed catalog ids; malformed output is rejected/repaired.
4. **Given** an unknown `catalog_id` or an out-of-range param, **When** validated, **Then** the
   request is rejected before any DB call and the decision is audit-logged.

---

### User Story 3 - Async document upload & ingestion with live status (Priority: P2)

An hr/superuser uploads a document on Manage Documents. The API saves the file, creates a
`documents` row (status=pending), enqueues an RQ job, and returns 202 immediately. The worker
processes it (pending→processing→ready/failed), and the UI shows a live status badge per
document with retry/re-embed for failures.

**Why this priority**: Required to populate the corpus realistically and a strong production
talking point, but document search (US1) can be demoed against a CLI-ingested corpus first.

**Independent Test**: Upload a PDF → see Pending → Processing → Ready and a chunk count; force
a failure → see Failed with an error message and a working retry.

**Acceptance Scenarios**:

1. **Given** an hr user, **When** they upload a valid document, **Then** the API returns 202 +
   document id and the request does not block on ingestion.
2. **Given** an enqueued job, **When** the worker runs, **Then** status transitions
   pending→processing→ready and `chunk_count`/`processed_at` are set; the doc is searchable only when ready.
3. **Given** a failing job, **When** it errors, **Then** status=failed with `error_message`, and
   a retry/re-embed re-runs the pipeline on the existing doc.
4. **Given** an emp user, **When** they attempt to access Manage Documents/upload, **Then** they are denied.

---

### User Story 4 - Dashboards with "Ask Compass to analyze this" (Priority: P2)

A mgr (team-scoped) or hr/superuser (company-scoped) views role-appropriate dashboards and
clicks "Ask Compass to analyze this." The backend runs the relevant scoped catalog query(ies),
passes the returned rows to the LLM with an analysis prompt, and returns a written summary
(trends, outliers, retention/approval signals). The LLM only analyzes rows the backend fetched.

**Why this priority**: High-value but depends on the catalog (US2) and schema being in place.

**Independent Test**: As mgr, open the team dashboard, click analyze → get a summary scoped to
direct reports only. As hr, analyze salary distribution → company-wide summary. Confirm the LLM
received only backend-fetched, scoped rows.

**Acceptance Scenarios**:

1. **Given** a mgr, **When** they analyze a team dashboard, **Then** the analysis covers only
   their direct reports' data.
2. **Given** an hr/superuser, **When** they analyze a company dashboard, **Then** the analysis
   covers company-wide aggregates.
3. **Given** repeated dashboard loads within TTL, **When** the same scoped aggregate is
   requested, **Then** rows are served from the dashboard cache; a relevant write busts the keys.

---

### User Story 5 - App support / how-to chat (Priority: P3)

Any employee asks the widget how to use Compass ("how do I request leave?", "where are my
documents?"). The intent router classifies it as `app_support` and answers from a small
app-help corpus via the same RAG pipeline.

**Why this priority**: Nice-to-have that reuses the RAG pipeline; lowest risk and lowest demo weight.

**Independent Test**: Ask "how do I request leave in this app?" → grounded how-to answer from
the app-help corpus.

**Acceptance Scenarios**:

1. **Given** any role, **When** they ask an app how-to question, **Then** the widget answers
   from the app-help corpus via RAG and logs intent `app_support`.

---

### User Story 6 - Auth, roles, admin & audit (Priority: P1, foundational)

Each role logs in via JWT and sees only what the section-3 matrix permits. Superuser manages
users/roles; hr/superuser manage employees. hr (HR-scope) and superuser (full) view audit logs
filtered by user, action_type, and date, with readable JSONB detail.

**Why this priority**: Foundational — every other story keys off roles and is audited.

**Independent Test**: Log in as each of the four seeded roles; confirm route/page access matches
the matrix; confirm each meaningful action writes an audit row visible on the audit page.

**Acceptance Scenarios**:

1. **Given** the four seeded users, **When** each logs in, **Then** a JWT carrying user_id+role
   is issued and the correct pages/routes are accessible per the matrix.
2. **Given** any meaningful action, **When** it occurs, **Then** an `audit_log` row is written
   with the appropriate action_type and detail JSONB.
3. **Given** a guardrail block, **When** it trips, **Then** an audit row with
   `action_type=guardrail_block` and a reason is recorded.

---

### Edge Cases

- Scanned/image-only PDF with no text layer → OCR path triggers; text-based PDFs do not OCR.
- Prompt injection in a user message OR inside a retrieved chunk → cannot change scope or run
  an unapproved query; blocked at the guard and/or harmless by design; logged.
- Out-of-scope data question (emp about a peer; mgr about a non-report) → refused/scoped, logged.
- Weak retrieval evidence in Analyze=ON → refusal, not hallucination.
- Cache must never serve one role/scope's result to another (keys include role/scope).
- Upload of disallowed type or oversized file → rejected before storage.
- Worker crash mid-job → status reflects failure; job retryable; doc re-embeddable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST authenticate via JWT (access token carrying user_id + role); passwords
  hashed with bcrypt/passlib; seed one user per role with documented demo passwords.
- **FR-002**: System MUST enforce the section-3 capability matrix in the backend via role-guard
  dependencies; role/scope MUST derive from the JWT, never from client/LLM input.
- **FR-003**: System MUST provide hybrid document retrieval: Postgres FTS over `chunks.tsv` +
  pgvector cosine over `chunks.embedding`, fused via RRF, then reranked by a cross-encoder; expose as one `search()` function.
- **FR-004**: Document Search MUST support Analyze ON (grounded cited markdown answer; refuse on
  weak evidence) and OFF (ranked raw chunks with doc_code+page+score), plus a sources panel and a status line.
- **FR-005**: System MUST maintain a SQL catalog of ~15–20 parameterized entries with
  `id, description, params, required_role, scope, sql, formatter`; the LLM sees only id/description/params.
- **FR-006**: For data questions the LLM MUST return only `{catalog_id, params}`; the backend MUST
  validate catalog_id against the registry and each param against its schema before binding/executing.
- **FR-007**: All SQL MUST use bind parameters only; the app DB role MUST be least-privilege
  (SELECT-only on catalog tables); writes go through separate authorized endpoints.
- **FR-008**: A widget intent router MUST classify each message as `data_query`,
  `data_analysis`, `app_support`, or `refuse` (rule-based first pass, LLM fallback) and log the decision.
- **FR-009**: Dashboard analysis MUST pass only backend-fetched, role-scoped rows to the LLM; the
  LLM MUST NOT fetch data itself.
- **FR-010**: Ingestion MUST be a shared module (extract per file type with page numbers; OCR via
  Tesseract only when no text layer; regex `clean_text()`; ~500-token chunks w/ ~50 overlap; OpenAI
  embeddings; tsv + GIN index; HNSW/IVFFlat index) with a CLI batch entry point.
- **FR-011**: Uploads MUST enqueue an async RQ ingestion job; `documents.embedding_status` MUST
  transition pending→processing→ready/failed with retry and re-embed; UI shows per-document status badges.
- **FR-012**: Every meaningful action (login, doc_search, data_query, data_analysis, support,
  admin, guardrail_block) MUST write an `audit_log` row with detail JSONB; the audit page reads it.
- **FR-013**: Every LLM call MUST pass through input and output guards (length cap, injection-
  pattern flagging, off-topic/abuse rejection, per-user rate limit; output schema validation,
  groundedness check in RAG mode, secret-pattern scan, citation-validity check); blocks are audit-logged.
- **FR-014**: All secrets MUST be fetched from Vault at startup via `hvac`; `.env`/keys git-ignored;
  `.env.example` committed blank; secrets never logged.
- **FR-015**: Redis MUST serve as both RQ broker and app cache: embedding cache (long TTL),
  retrieval/answer cache keyed by (query, mode, role-scope) (short TTL), dashboard data cache keyed by
  (catalog_id, scope, params) (short TTL, invalidated on writes); reranker model loaded once at startup.
- **FR-016**: Docker Compose MUST bring up postgres(pgvector), redis, vault(dev), api, worker with
  health checks; `docker compose up` starts the whole system.
- **FR-017**: System MUST present the role-gated pages: Login, Document Search, Dashboards, Manage
  Employees, Manage Documents, Audit Logs, and a persistent chat widget.
- **FR-018**: Uploads MUST be validated (type allowlist, max size, stored outside web root,
  filename scan); auth and LLM endpoints rate-limited; CORS locked to app origin; security headers set.
- **FR-019**: PII the requester is not entitled to MUST be redacted/masked before reaching the LLM.
- **FR-020**: UI MUST render LLM answers as markdown, use the compass theme, and design loading,
  empty, and refusal states.

### Key Entities

- **users** — id, username, password_hash, role, employee_id (nullable FK), is_active.
- **employees** — id, full_name, department, grade/level, manager_id (self-FK), hire_date,
  contract_end_date, salary, status.
- **leave_balances** — employee_id, leave_type, days_total, days_used, year.
- **leave_requests** — id, employee_id, start_date, end_date, type, status, approver_id.
- **documents** — id, doc_code, title, doc_type, source_path, page_count, embedding_status,
  uploaded_by, uploaded_at, processed_at, error_message, chunk_count.
- **chunks** — id, document_id (FK), page, chunk_index, text, embedding (vector), tsv (tsvector).
- **audit_log** — id, ts, user_id, role, action_type, detail (JSONB), result_status.
- **SQL catalog entry** — id, description, params schema, required_role, scope, sql, formatter
  (registry, not a DB table; LLM sees only id/description/params).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `docker compose up` brings all five services healthy from a clean checkout with no
  hand-editing beyond copying `.env.example` and running the Vault seed.
- **SC-002**: All four seeded roles log in and can access exactly the pages/routes their matrix row
  permits — no more, no less (verified by a role walkthrough).
- **SC-003**: For a seeded corpus, Analyze=ON answers are grounded with citations that 100% map to
  retrieved chunks; weak-evidence queries refuse rather than hallucinate.
- **SC-004**: A set of deliberate attack cases (injection strings in user input and in documents,
  scope-escalation attempts, unknown catalog ids, out-of-range params) are ALL blocked/scoped and
  every block appears in the audit log.
- **SC-005**: There is zero string-built SQL in the codebase (verified by a grep/lint gate); the LLM
  never receives a table name or the `sql` field.
- **SC-006**: An uploaded document moves pending→processing→ready with a visible badge; a forced
  failure shows Failed + error and a retry succeeds.
- **SC-007**: Identical repeat document searches and repeated dashboard loads within TTL are served
  from cache, and no cache entry is ever served across a role/scope boundary.
- **SC-008**: The catalog contains 15–20 entries spanning self/team/company/signal categories; the
  widget answers data questions, analyses, and app-support correctly per role.

## Assumptions

- Synthetic dataset: ~50–80 employees with a realistic manager hierarchy, salary spread across
  departments/grades, leave balances, and some pending/approved leave requests.
- Local dev on Docker Compose; Vault runs in dev mode; no production deployment in scope.

## Clarifications (from brief section 16) — RESOLVED 2026-06-15

1. **Embedding model + dimension** — OpenAI `text-embedding-3-small`, 1536-dim (`vector(1536)`). ✅
2. **App-support corpus (6c)** — RAG over a small app-help corpus in `data/app_help/`. ✅
3. **Frontend library** — Alpine.js on server-rendered templates, no SPA. ✅
4. **Guardrails approach** — custom `input_guard()` / `output_guard()` wrappers. ✅
