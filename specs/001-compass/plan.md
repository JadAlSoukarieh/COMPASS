# Implementation Plan: Compass

**Branch**: `001-compass` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-compass/spec.md` (derived from `brief.md`).

## Summary

Build a role-aware internal assistant with two pillars: (1) meaning-based document search with
hybrid retrieval (Postgres FTS + pgvector, RRF-fused, cross-encoder reranked) and grounded cited
answers; (2) a chat widget that answers company-data questions by having the LLM *select* from a
fixed SQL catalog (returning only `{catalog_id, params}`) while the backend validates, enforces
role/scope, and runs pre-written parameterized queries. Async document ingestion runs on an RQ
worker. Secrets live in Vault; Redis is both the RQ broker and the app cache. The governing rule:
**the LLM is never a security boundary** — see [constitution](../../.specify/memory/constitution.md).

## Technical Context

**Language/Version**: Python 3.12 (backend, worker, ingestion CLI), HTML/CSS/JS (frontend).

**Primary Dependencies**: FastAPI, uvicorn, SQLAlchemy/psycopg, pgvector, openai, sentence-transformers
(cross-encoder), pytesseract + poppler, pdfplumber, python-docx, openpyxl/pandas, redis + rq, hvac,
passlib[bcrypt], python-jose (JWT), pydantic, slowapi (rate limiting). Frontend: Alpine.js or htmx +
a markdown renderer.

**Storage**: PostgreSQL + pgvector (`vector(1536)`), Redis (broker + cache), local file store for
uploads (outside web root). HashiCorp Vault (dev) for secrets.

**Testing**: pytest (unit: clean_text, chunker, RRF fusion, param validation, scope checks, guards;
integration: search(), ingestion job, role walkthroughs, attack cases). Tests are included because
the security posture (SC-004, SC-005) must be demonstrably verified.

**Target Platform**: Linux server via Docker Compose (local dev / academic demo).

**Project Type**: Web application (FastAPI backend + worker + static/templated frontend).

**Performance Goals**: Interactive search latency surfaced in the status line; caching keeps repeat
searches and dashboard loads near-instant. Ingestion is async and off the request path.

**Constraints**: No string-built SQL anywhere; LLM never sees table names or SQL; least-privilege DB
role; all secrets via Vault; synthetic data only; cache keys include role/scope.

**Scale/Scope**: ~50–80 synthetic employees; small document corpus; 15–20 catalog entries; 6 pages +
a persistent widget; 5 Docker services.

## Constitution Check

*GATE: Must pass before Phase 0. Re-check after each phase.*

| Principle | How this plan complies |
|---|---|
| I. LLM not a security boundary | Backend validates/executes everything; LLM output only selects an id + params; design makes injection harmless. |
| II. LLM never writes/sees SQL | Catalog exposes only id/description/params to the model; `sql` field never serialized to a prompt. |
| III. Bind params only | All catalog queries parameterized; param-schema validation before binding; grep/lint gate (Phase 8/11). |
| IV. Backend role/scope | role/scope from JWT via `get_current_user`; `require_roles` guards; scope injected server-side. |
| V. All LLM text hostile | System/data separation; chunks fenced as data; structured outputs validated. |
| VI. Guardrails + audit | `input_guard`/`output_guard` around every LLM call; `audit_log` for all actions + `guardrail_block`. |
| VII. No secrets / synthetic only | Vault via hvac at startup; `.env`/keys gitignored; synthetic seed data. |
| VIII. One pipeline two entry points | Shared `ingestion` module; CLI batch + RQ job both call it. |

**Result**: PASS (no violations; no entries in Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/001-compass/
├── brief.md             # Verbatim owner brief (source of truth)
├── spec.md              # Feature specification
├── plan.md              # This file
├── data-model.md        # Entities, schema, SQL-catalog registry design
├── quickstart.md        # How to bring the system up and verify each phase
├── research.md          # Decisions on the 4 open clarifications + tech notes
├── contracts/           # API endpoint contracts (OpenAPI-style markdown)
│   ├── auth.md
│   ├── search.md
│   ├── widget.md
│   ├── documents.md
│   ├── dashboards.md
│   └── admin-audit.md
└── tasks.md             # Phase-by-phase task list (the implementation backlog)
```

### Source Code (repository root)

```text
compass/
├── docker-compose.yml
├── .env.example
├── vault_seed.sh
├── pyproject.toml
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, CORS, security headers, startup (Vault, model load)
│   │   ├── config.py               # settings; pulls secrets from Vault via hvac
│   │   ├── db.py                    # engine/session; least-privilege app role
│   │   ├── security/
│   │   │   ├── auth.py             # JWT issue/decode, get_current_user, require_roles
│   │   │   ├── scope.py            # self/team/company scope resolution from JWT
│   │   │   └── guards.py           # input_guard() / output_guard()
│   │   ├── models/                 # SQLAlchemy models (users, employees, leave_*, documents, chunks, audit_log)
│   │   ├── schemas/                # pydantic request/response + LLM structured-output schemas
│   │   ├── catalog/
│   │   │   ├── registry.py         # 15–20 catalog entries (id, desc, params, role, scope, sql, formatter)
│   │   │   └── validate.py         # catalog_id + param schema validation
│   │   ├── llm/
│   │   │   ├── client.py           # OpenAI wrapper (chat + embeddings) w/ guards + caching
│   │   │   ├── intent.py           # widget intent router
│   │   │   ├── answer.py           # RAG grounded-answer generation
│   │   │   └── analyze.py          # dashboard data-analysis prompts
│   │   ├── retrieval/
│   │   │   ├── search.py           # search(): keyword + vector + RRF + rerank
│   │   │   └── rerank.py           # cross-encoder, loaded once at startup
│   │   ├── cache.py                # Redis helpers: emb:/search:/dash: namespaces, role/scope keys
│   │   ├── audit.py                # write_audit(...) helper
│   │   └── routers/                # auth, search, widget, documents, dashboards, employees, users, audit
│   └── tests/
├── worker/
│   └── worker.py                   # RQ worker entry; calls shared ingestion module
├── ingestion/
│   ├── pipeline.py                 # shared: extract→clean→chunk→embed→insert→tsv (one pipeline)
│   ├── extract.py                  # per-filetype extractors + dispatcher; OCR only when no text layer
│   ├── clean.py                    # clean_text() (testable)
│   ├── chunk.py                    # ~500-token chunks, ~50 overlap, paragraph-aware
│   └── cli.py                      # batch entry point (offline)
├── frontend/                       # templates/static: login, search, dashboards, manage-*, audit, widget
└── data/
    ├── seed/                       # synthetic employees/leave generator
    ├── docs/                       # source documents (synthetic) for ingestion
    └── app_help/                   # app-support corpus (6c) for RAG
```

**Structure Decision**: Web application layout. Backend (`backend/app`), a separate `worker/`
process, and a shared `ingestion/` package imported by both the worker and the CLI (Principle VIII).
Frontend is server-rendered templates + light JS (Alpine/htmx), no SPA.

## Phased Approach (maps to brief section 14)

The build proceeds strictly in phase order; each phase has a "prove it works" gate before the next.
`tasks.md` expands each phase into concrete tasks.

- **Phase 0 — Scaffold**: Compose (postgres+pgvector, redis, vault dev, api, worker), project skeleton,
  Vault wiring, Redis cache helper, `.env.example`, per-service health checks.
- **Phase 1 — Auth & roles**: users table, login, JWT, role-guard deps, seed users; each role logs in.
- **Phase 2 — Schema & synthetic data**: all tables + seed generator (50–80 employees, hierarchy, leave).
- **Phase 3 — Ingestion module**: extractor + cleaner + chunker + embeddings + tsv + indexes as a
  shared module with a CLI batch entry; prove a chunk lands with embedding + tsv.
- **Phase 4 — Async ingestion queue**: Redis+RQ; worker runs Phase 3; status transitions; retry/re-embed.
- **Phase 5 — Hybrid retrieval + reranker**: keyword + vector + RRF + rerank as one `search()`.
- **Phase 6 — Document search page**: UI + Analyze toggle + sources panel + status line + caches.
- **Phase 7 — Manage Documents page**: upload → async ingestion → live status badges → re-embed/retry.
- **Phase 8 — SQL catalog + data widget**: registry (15–20), LLM tool-selection JSON, backend
  validation + scope + least-privilege execution + NL answer (modes 6a + 6c).
- **Phase 9 — Dashboards + analysis**: role-scoped dashboards + "Ask Compass to analyze this" (6b) +
  dashboard cache w/ write invalidation.
- **Phase 10 — Manage employees/users + audit log pages**.
- **Phase 11 — Security & guardrails pass**: input/output guards on every LLM call, prompt-injection
  handling, structured-output validation, upload validation + rate limiting, `guardrail_block` audit;
  deliberate attack test cases blocked + logged.
- **Phase 12 — Polish**: UI pass, refusal/empty/loading states, end-to-end role walkthroughs.

## Clarifications — RESOLVED (2026-06-15, see research.md)

(a) `text-embedding-3-small` / 1536-dim · (b) RAG app-help corpus · (c) Alpine.js · (d) custom
input/output guard wrappers. Design freeze complete — Phase 0 may begin.

## Complexity Tracking

No constitution violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
