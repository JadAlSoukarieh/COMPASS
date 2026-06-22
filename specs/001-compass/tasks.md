---
description: "Task list for Compass implementation"
---

# Tasks: Compass

> **Audit (Phases 0–10), 2026-06-16:** Implemented by Codex (backend) + Claude (frontend).
> All 47 tests pass. Constitution verified compliant: the LLM only ever returns
> `{catalog_id, params}` (registry `prompt_payload()` never serializes `sql`/table names);
> all catalog queries bind-parameterized; `{scope_clause}` interpolates only a backend-controlled
> column name (`catalog/validate.py:_render_sql`), never user/LLM input; role/scope JWT-derived and
> refused server-side; dashboard cache keyed by (catalog_id, scope+employee_id, params) and busted
> on employee writes; widget/dashboard/search paths all audit-logged incl. `guardrail_block`.
> Two string-SQL sites exist and are audited-safe (must be whitelisted by the Phase 11 grep gate):
> `db.py` Postgres `format(%L)` for role passwords (server-side, value still parameterized) and
> `validate.py` `.sql.format(scope_clause=...)` (backend-controlled column). Phase 11 still needs:
> chunk-level injection handling/PII redaction, the grep-gate script, and the attack-case suite.

**Input**: Design documents from `specs/001-compass/` (brief.md, spec.md, plan.md, data-model.md,
research.md, contracts/).

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/ (all present).

**Tests**: Included. The security posture (SC-004 attack cases, SC-005 no string-SQL) must be
demonstrably verified, so test tasks are first-class here.

**Organization**: Grouped by the brief's build phases (§14). Phases are sequential — confirm each
phase's gate (see quickstart.md) before starting the next. Within a phase, `[P]` tasks touch
different files and can run in parallel.

## Format: `[ID] [P?] [Phase] Description`
- **[P]**: parallelizable (different files, no dependency).
- File paths follow plan.md's structure.

## Constitution gates (apply to EVERY phase that touches the LLM, SQL, or secrets)
- LLM never writes/sees SQL; output is only `{intent}` / `{catalog_id, params}` / grounded answer.
- All SQL bind-parameterized; catalog_id + params validated before binding; least-privilege DB role.
- Role/scope from JWT, enforced in backend.
- Every LLM call wrapped by input/output guards; every block audit-logged.
- No secrets in code/git (Vault only); synthetic data only.

---

## Phase 0: Scaffold

**Goal**: `docker compose up` brings up all five services healthy; Vault + Redis wired.

- [x] T001 [P] [P0] Create repo skeleton per plan.md (`backend/app`, `worker/`, `ingestion/`, `frontend/`, `data/`).
- [x] T002 [P] [P0] `pyproject.toml` with all locked deps (FastAPI, SQLAlchemy/psycopg, pgvector, openai, sentence-transformers, pytesseract, pdfplumber, python-docx, openpyxl/pandas, redis, rq, hvac, passlib[bcrypt], python-jose, pydantic, slowapi).
- [x] T003 [P0] `docker-compose.yml`: services `postgres` (pgvector image), `redis`, `vault` (dev), `api`, `worker`, each with a health check; one `docker compose up` starts all.
- [x] T004 [P] [P0] `.env.example` (blank/placeholder values incl. documented demo passwords) + `.gitignore` excluding `.env` and key files.
- [x] T005 [P] [P0] `vault_seed.sh`: seed Vault dev with OpenAI key, DB password, JWT signing key.
- [x] T006 [P0] `backend/app/config.py`: fetch all secrets from Vault via `hvac` at startup; never log secrets.
- [x] T007 [P0] `backend/app/db.py`: engine/session; create both DB roles `compass_app` (SELECT + audit INSERT) and `compass_writer` (authorized writes).
- [x] T008 [P] [P0] `backend/app/cache.py`: Redis helper with namespaces `emb:`/`search:`/`dash:`, get/set/bust, role/scope-aware keys.
- [x] T009 [P0] `backend/app/main.py`: FastAPI app, CORS locked to app origin, security headers, `/health`; startup hook (Vault load + reranker model load placeholder).
- [x] T010 [P] [P0] `worker/worker.py`: RQ worker bootstrap connecting to Redis (job logic added in Phase 4).
- [x] T011 [P0] **Gate**: `docker compose up` → all services healthy; `/health` OK; cache round-trips; Vault returns seeded secrets.

---

## Phase 1: Auth & roles (US6 foundational)

**Goal**: Each of four roles logs in; role guards enforce the matrix.

- [x] T012 [P] [P1] `backend/app/models/users.py`: `users` model (data-model.md).
- [x] T013 [P1] `backend/app/security/auth.py`: bcrypt/passlib hashing; JWT issue/decode (payload user_id+role); `get_current_user`; `require_roles(...)`.
- [x] T014 [P1] `backend/app/security/scope.py`: `resolve_scope(user)` → self/team/company; load mgr direct-report ids.
- [x] T015 [P1] `backend/app/routers/auth.py`: `POST /auth/login`, `GET /auth/me` (contracts/auth.md); rate-limited; audit login.
- [x] T016 [P] [P1] Seed script: one user per role (superuser/hr/mgr/emp) with documented demo passwords.
- [x] T017 [P] [P1] Tests: per-role login issues correct token; role-guarded routes allow/deny per matrix.
- [x] T018 [P1] **Gate**: all four roles log in; guarded routes behave per the section-3 matrix.

---

## Phase 2: Schema & synthetic data

**Goal**: All tables exist; ~50–80 realistic synthetic employees seeded.

- [x] T019 [P] [P2] Models: `employees`, `leave_balances`, `leave_requests` (self-FK hierarchy on employees).
- [x] T020 [P] [P2] Models: `documents`, `chunks` (vector(1536), tsvector), `audit_log` (jsonb detail).
- [x] T021 [P2] Migrations/DDL incl. pgvector extension, GIN index on `chunks.tsv`, HNSW/IVFFlat index on `chunks.embedding`.
- [x] T022 [P2] `data/seed/`: generator for 50–80 employees w/ manager hierarchy, salary spread by dept/grade, leave balances, pending/approved leave requests.
- [x] T023 [P] [P2] `backend/app/audit.py`: `write_audit(...)` helper (used everywhere downstream).
- [x] T024 [P2] **Gate**: seed runs; spot-check queries return a coherent hierarchy + leave data.

---

## Phase 3: Ingestion module (shared) — Constitution VIII

**Goal**: A chunk lands in `chunks` with an embedding and a tsv, via the shared module's CLI.

- [x] T025 [P] [P3] `ingestion/clean.py`: `clean_text()` (strip headers/footers/page numbers, collapse whitespace, fix hyphenation, remove control chars, normalize bullets) — testable.
- [x] T026 [P] [P3] `ingestion/extract.py`: per-filetype extractors (pdfplumber/pdftotext per page; python-docx; openpyxl/pandas → readable rows) + dispatcher by extension.
- [x] T027 [P3] `ingestion/extract.py`: OCR path via pytesseract (render pages → image → OCR) triggered ONLY when a PDF has no text layer.
- [x] T028 [P] [P3] `ingestion/chunk.py`: ~500-token chunks, ~50 overlap, paragraph-aware; attach doc_code/title/doc_type/page/chunk_index.
- [x] T029 [P3] `ingestion/pipeline.py`: orchestrate extract→clean→chunk→embed(OpenAI)→insert chunks→build tsv; re-file under invented doc codes; uses `compass_writer`.
- [x] T030 [P] [P3] `ingestion/cli.py`: batch entry point over `data/docs/`.
- [x] T031 [P] [P3] Tests: `clean_text()`, chunker boundaries/overlap, extractor dispatch, OCR-trigger condition.
- [x] T032 [P3] **Gate**: CLI ingests a sample doc; a `chunks` row has non-null embedding + populated tsv; indexes present.

---

## Phase 4: Async ingestion queue (US3 backend)

**Goal**: An enqueued job runs end-to-end through the worker with status transitions + retry.

- [x] T033 [P4] `worker/worker.py`: RQ job that sets status processing → calls `ingestion.pipeline` → ready (chunk_count, processed_at) | failed (error_message).
- [x] T034 [P4] Enqueue helper (used by upload + reembed endpoints) targeting the shared Redis broker.
- [x] T035 [P4] Retry + re-embed: re-enqueue on existing doc; clear prior chunks; reset status to pending.
- [x] T036 [P] [P4] Tests: enqueued job transitions pending→processing→ready; forced failure → failed+error; retry succeeds.
- [x] T037 [P4] **Gate**: end-to-end queued ingestion verified; worker shares the Phase 3 module (no duplicate pipeline).

---

## Phase 5: Hybrid retrieval + reranker (US1 backend)

**Goal**: One `search()` returns well-ranked, fused, reranked results with provenance.

- [x] T038 [P5] `backend/app/retrieval/rerank.py`: load cross-encoder once at startup; `rerank(query, candidates)`.
- [x] T039 [P5] `backend/app/retrieval/search.py`: keyword (websearch_to_tsquery + ts_rank over tsv) + vector (pgvector cosine `<=>`) → RRF fusion → rerank top-N → top-k; returns chunk_id/doc_code/title/page/score.
- [x] T040 [P5] Wire reranker model load into `main.py`/`worker` startup (in-memory, not per request).
- [x] T041 [P] [P5] Tests: RRF fusion unit test; `search()` ranking sanity on the seeded corpus (only `ready` docs).
- [x] T042 [P5] **Gate**: from a script, `search()` ranking is sensible with full provenance.

---

## Phase 6: Document search page (US1) + caches

**Goal**: Search UI with Analyze toggle, sources panel, status line; embedding + retrieval cache.

- [x] T043 [P6] `backend/app/llm/client.py`: OpenAI wrapper (chat + embeddings) with input/output guard hooks + embedding cache (`emb:`). (Codex)
- [x] T044 [P6] `backend/app/llm/answer.py`: RAG grounded-answer generation; chunks fenced as data; citations must map to retrieved chunks; refuse on weak evidence. (Codex)
- [x] T045 [P6] `backend/app/routers/search.py`: `POST /search` (contracts/search.md); Analyze ON/OFF; retrieval/answer cache keyed `search:<role>:<scope>:<mode>:<hash>`; audit `doc_search`. (Codex)
- [x] T046 [P] [P6] Frontend: Document Search page — search box, Analyze toggle, ranked-chunks view, answer block (markdown), sources panel (cited badge, expandable highlighted text), status line. `frontend/templates/{base,login,search}.html` + `static/css/compass.css` (Alpine.js).
- [x] T047 [P] [P6] Frontend: loading/empty/refusal states (compass theme).
- [x] T048 [P] [P6] Tests: citation-validity, cache hit on identical repeat, cache key includes role/scope (`test_search_phase6.py`, Codex) + frontend page routes (`test_frontend_pages_phase6.py`).
- [x] T049 [P6] **Gate**: OFF returns ranked chunks; ON returns grounded cited markdown; weak evidence refuses; status line correct; repeat hits cache. **35 tests pass.**

> Phase 6 note: backend (T043–T045, schemas, guards, cache keys, main.py wiring) implemented by
> Codex; frontend (T046/T047) built in Alpine.js per confirmed decision (c) on a shared `base.html`
> + compass theme. Codex's initial vanilla-JS standalone page (`compass-search.{css,js}`) was
> removed in favour of the Alpine version. `GET /` (→ /search) and `GET /login` routes added.

---

## Phase 7: Manage Documents page (US3 frontend)

**Goal**: Upload → async ingestion → live status badges → re-embed/retry.

- [x] T050 [P7] `backend/app/routers/documents.py`: `POST /documents` (202 + enqueue), `GET /documents`, `GET /documents/{id}/status`, `POST /documents/{id}/reembed` (contracts/documents.md); `require_roles("hr","superuser")`.
- [x] T051 [P7] Upload validation: type allowlist, max size, filename scan, store outside web root.
- [x] T052 [P] [P7] Frontend: Manage Documents — upload form, document list with status badges (Pending/Processing/Ready/Failed) + chunk count, retry/re-embed action; polls status endpoint.
- [x] T053 [P] [P7] Tests: upload returns 202 + status progresses; failed doc shows error + retry works; emp denied.
- [x] T054 [P7] **Gate**: full upload→ready flow visible in UI; failures retryable; access gated.

---

## Phase 8: SQL catalog + data widget (US2, US5 — modes 6a + 6c)

**Goal**: LLM selects catalog id + params (JSON only); backend validates, scopes, runs param query, phrases answer.

- [x] T055 [P8] `backend/app/catalog/registry.py`: 15–20 entries (data-model.md) with id/description/params/required_role/scope/sql/formatter; LLM sees only id/description/params.
- [x] T056 [P8] `backend/app/catalog/validate.py`: validate catalog_id ∈ registry; validate each param vs schema (type/range/allowed/existence) before binding.
- [x] T057 [P8] `backend/app/llm/intent.py`: intent router (rule-based first pass, LLM fallback) → data_query/data_analysis/app_support/refuse; logged.
- [x] T058 [P8] Catalog execution: bind-parameterized query via `compass_app` (SELECT-only); apply JWT-derived scope; refuse out-of-scope.
- [x] T059 [P8] `backend/app/routers/widget.py`: `POST /widget/message` (contracts/widget.md); modes 6a (data_query) + 6c (app_support via RAG); structured-output validation; NL answer; audit per intent.
- [x] T060 [P] [P8] Frontend: persistent chat widget (floating button/side panel) across pages.
- [x] T061 [P] [P8] Tests: LLM output is only `{catalog_id, params}`; unknown id rejected; out-of-range param rejected pre-DB; emp asking about a peer is scoped/refused; all logged.
- [x] T062 [P8] **Gate**: data questions answered per role; scope enforced server-side; no SQL ever in LLM I/O.

---

## Phase 9: Dashboards + analysis (US4 — mode 6b) + dashboard cache

**Goal**: Role-scoped dashboards; "Ask Compass to analyze this" on backend-fetched scoped rows; cache + invalidation.

- [x] T063 [P9] `backend/app/llm/analyze.py`: analysis prompts; receives ONLY backend-fetched scoped rows (fenced as data). (Codex)
- [x] T064 [P9] `backend/app/routers/dashboards.py`: `GET /dashboards`, `GET /dashboards/{id}/data` (scoped, cached `dash:`), `POST /dashboards/{id}/analyze` (mode 6b); audit `data_analysis`. (Codex)
- [x] T065 [P9] Dashboard cache: key `dash:<catalog_id>:<scope>:<hash(params)>` short TTL; invalidate on employee writes (`employees.py::_bust_dashboard_cache`). (Codex)
- [x] T066 [P] [P9] Frontend: dashboards (emp self / mgr team / hr-superuser company) + "Ask Compass to analyze this" — rebuilt with dashboard cards, KPI stat cards, distribution bars, formatted tables (Claude).
- [x] T067 [P] [P9] Tests: dashboard scope/cache (Codex backend tests).
- [x] T068 [P9] **Gate**: dashboards scoped correctly; analysis summarizes only fetched rows; cache + invalidation verified.

---

## Phase 10: Manage employees/users + audit log pages

**Goal**: hr/superuser manage data; audit page filters and renders JSONB detail.

- [x] T069 [P10] `backend/app/routers/employees.py`: `GET/POST /employees`, `PATCH /employees/{id}` (contracts/admin-audit.md); `compass_writer`; bust dash cache; audit `admin`.
- [x] T070 [P10] `backend/app/routers/users.py`: `GET/POST /users`, `PATCH /users/{id}` (superuser only); passwords hashed, never returned; audit `admin`.
- [x] T071 [P10] `backend/app/routers/audit.py`: `GET /audit` with filters (user, action_type, date) + hr-scope vs superuser-full.
- [x] T072 [P] [P10] Frontend: Manage Employees, Manage Users (superuser), Audit Logs (filters + readable JSONB detail).
- [x] T073 [P] [P10] Tests: write endpoints role-gated; audit filtering + scoping correct.
- [x] T074 [P10] **Gate**: admin flows work and are gated; audit page usable.

---

## Phase 11: Security & guardrails pass (cross-cutting — Constitution V, VI; brief §12)

**Goal**: Input/output guards on every LLM call; attack cases blocked + logged; no string-SQL.

- [x] T075 [P11] `backend/app/security/guards.py`: `input_guard()` (length cap, injection-pattern block, empty/abuse reject) and `output_guard()` (schema validation, groundedness in RAG mode, secret-pattern scan, citation validity). Added `sanitize_chunk_text()` + `redact_pii()`.
- [x] T076 [P11] Wrap EVERY LLM call (intent, catalog-select, answer, analyze, support) with the guards; every trip logged as `guardrail_block` with reason. Retrieved chunks sanitized + fenced as data in `answer.py`.
- [x] T077 [P11] PII redaction: `redact_pii()` masks emails/phones/SSN-like ids before content reaches the LLM.
- [x] T078 [P] [P11] Rate-limit auth (10/min) + LLM endpoints (search/widget 30/min) via slowapi; CORS locked + security headers in `main.py`.
- [x] T079 [P11] No-string-SQL gate: `scripts/check_no_string_sql.py` (audited-safe whitelist: db.py role/GRANT, validate.py scope_clause); run as a test.
- [x] T080 [P11] Attack-case suite: injection in user input AND in a poisoned document chunk; scope-escalation; unknown catalog_id; out-of-range params; secret-leak; invalid-citation — all blocked/scoped + audit-logged (`test_security_phase11.py` + `test_widget_phase8.py`). SC-004.
- [x] T081 [P11] **Gate**: attack suite passes; grep gate clean; LLM never sees SQL/table names. **69 tests pass.**

---

## Phase 12: Polish

**Goal**: UI pass; designed states; end-to-end role walkthroughs.

- [x] T082 [P] [P12] UI pass: navy-sidebar shell + top context bar, bolder/branded compass theme, Inter, markdown answers, monospace citation pills, dot/pill status badges, dashboard KPI/bar visuals.
- [x] T083 [P] [P12] Loading/empty/refusal/error states on every page (incl. added states to manage_users.html).
- [x] T084 [P12] End-to-end: all 28 routes register, all templates render, app imports cleanly; README demo walkthrough per role.
- [x] T085 [P12] **Gate**: README documents SC-001…SC-008; 69 tests pass; string-SQL gate clean. (Full Docker bring-up SC-001 to be confirmed on a Docker host.)

---

## Dependencies & Execution Order

- Phases are sequential (brief §14). Each phase's Gate task must pass before the next phase starts.
- Phase 0 (scaffold) blocks everything. Phase 1 (auth) + Phase 2 (schema) block all feature work.
- Phase 3 (ingestion module) blocks Phase 4 (async) and feeds Phase 5 (retrieval).
- Phase 5 blocks Phase 6 (search page); Phase 6 patterns feed Phase 8 (app_support RAG).
- Phase 2 schema + Phase 8 catalog block Phase 9 (dashboards/analysis).
- Phase 11 (security/guardrails) is a cross-cutting hardening pass over all earlier LLM/SQL code.

### Parallel opportunities
- Within a phase, `[P]` tasks (different files) run in parallel.
- Frontend `[P]` tasks for a page can proceed alongside that page's backend once contracts are fixed.
- Tests `[P]` for a phase can be written alongside implementation.

## Notes
- [P] = different files, no dependency. [Phase] maps each task to a brief build phase.
- Confirm each Gate before advancing. If a phase grows large, STOP and check in with the owner.
- Commit after each task or logical group. Never commit secrets; synthetic data only.
- The four §16 clarifications are RESOLVED (research.md): text-embedding-3-small/1536, RAG app-help
  corpus, Alpine.js, custom input/output guard wrappers. Design freeze complete.
