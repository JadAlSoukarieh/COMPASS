# Compass — Build Brief (verbatim source of truth)

> This is the original Build Brief provided by the project owner, preserved verbatim as the
> single source of truth. The spec.md, plan.md, and tasks.md in this directory are derived
> from it. If anything in the derived files conflicts with this brief, this brief wins —
> raise the conflict with the owner.

---

## 1. What Compass is

Compass is an AI-assisted internal assistant for a company. It does two things:

1. **Document search (main feature)** — staff find policies and how-to guides by *meaning*, not by document code, and get answers grounded in the source with citations.
2. **ERP/data assistant via a SQL catalog (the structured side)** — an in-app chat widget answers questions about company data (leave balances, salary distributions, headcount, etc.) by selecting from a fixed catalog of safe, pre-approved SQL queries. The LLM never writes raw SQL.

It is role-aware: what a user can see and ask depends on their role.

This is a standalone academic project on **synthetic data only**. No real company data.

## 2. Tech stack (locked — do not substitute)

- Backend: Python + FastAPI
- Database: PostgreSQL with pgvector
- Embeddings: OpenAI embeddings API (`text-embedding-3-small`, 1536-dim) in a `vector` column
- LLM: OpenAI (chat/completions) for routing, answer generation, data analysis
- Reranker: cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2` via sentence-transformers) local
- OCR: Tesseract via `pytesseract` — only for scanned/image PDFs
- Secrets: HashiCorp Vault (dev mode) via `hvac`
- Job queue & cache: Redis — RQ job broker for async ingestion AND application cache; one service
- Frontend: HTML/CSS/JS; Alpine.js or htmx allowed; no heavy SPA
- Containerization: Docker Compose — postgres(pgvector), redis, vault(dev), api, worker

## 3. Roles & permissions

Four roles: superuser, hr, mgr, emp. Capability matrix (see spec.md for the full table). Critical
rule: role/scope enforcement happens in the BACKEND, never in the LLM and never only in the
frontend. The LLM may select a catalog query and extract parameters, but the backend validates the
requesting user's role and scope before executing, and filters/refuses if out of scope.

## 4. Auth system

JWT auth (access token; refresh optional). bcrypt/passlib. Login issues token with user_id + role.
`get_current_user` dependency. `require_roles(...)` guards. Seed one user per role with documented
demo passwords in `.env.example`.

## 5. Database schema (synthetic)

users, employees, leave_balances, leave_requests, documents, chunks, audit_log (see spec.md /
data-model.md for fields). Generate ~50–80 synthetic employees with realistic hierarchy, salary
spread, leave balances, and pending/approved leave requests.

## 6. The chat widget

Three request kinds via a lightweight intent step:
- 6a Data questions via SQL catalog — LLM returns `{catalog_id, params}`; backend validates,
  enforces scope, executes parameterized query, LLM phrases result.
- 6b Dashboard / data analysis — backend runs scoped catalog queries, passes rows to LLM with an
  analysis prompt; LLM analyzes backend-fetched rows only.
- 6c Support / how-to — answered from a small app-help corpus via RAG (preferred) or static FAQ.
Intent routing: data_query / data_analysis / app_support / refuse. Rule-based first, LLM fallback. Log it.

## 7. SQL catalog

Registry of entries: id, description, params, required_role, scope (self|team|company), sql
(bind params only), formatter. Build ~15–20 entries across self/team/company/signal categories
(see spec.md and data-model.md for the full list). The LLM never sees the sql field — only id,
description, params. All queries use bind parameters.

## 8. Document search page

Search box + results; "Analyze with AI" toggle (ON = grounded cited answer, refuse on weak
evidence; OFF = ranked raw chunks). Hybrid retrieval: Postgres FTS over tsv + pgvector cosine,
fused via RRF; then cross-encoder rerank top-N → top-k. Sources panel with cited badge, expandable
highlighted source text. Status line: model · hybrid · reranked · N retrieved · k cited · latency ms.

## 9. Ingestion pipeline

Offline script + shared module: extract per file type preserving pages (pdftotext/pdfplumber;
Tesseract OCR for scanned PDFs; python-docx; openpyxl/pandas), regex `clean_text()`, ~500-token
chunks w/ ~50 overlap, OpenAI embeddings, tsv + GIN index, HNSW/IVFFlat index, re-file under
invented doc codes. Modular extractor: one function per file type + dispatcher; OCR only when no
text layer.

### 9b. Async ingestion via Redis + RQ

Upload → API saves file, creates documents row (pending), enqueues RQ job, returns 202 + id.
Worker: pending→processing, runs pipeline, →ready (+processed_at, chunk_count). On failure →failed
(+error_message); retryable + re-embeddable. UI shows per-document status badge; doc searchable
only when ready. Worker shares the same ingestion module as the offline script.

## 10. Pages / screens

Login; Document Search (all); Dashboards (emp minimal, mgr team-scoped, hr/superuser company) with
"Ask Compass to analyze this"; Manage Employees (hr, superuser); Manage Documents (hr, superuser)
with status badges + re-embed/retry; Audit Logs (hr scoped, superuser full); persistent chat widget.

## 11. Audit logging

Every meaningful action writes an audit_log row (logins, doc searches with query/chunk ids/k
cited/latency, data queries with intent/catalog_id/params/scope decision/latency, analysis, support,
admin). Audit page reads it. Graded production-mindedness feature — make it thorough.

## 12. Security & secrets

Secrets from Vault via hvac; `.gitignore` excludes `.env`/keys; commit `.env.example` blank; never
log secrets; never interpolate user input into SQL; validate catalog params before execution.

- 12a Threat model: SQL injection, prompt injection, privilege/scope escalation, sensitive-data
  leakage. Core philosophy: the LLM is never trusted as a security boundary.
- 12b SQL injection defenses: LLM never emits SQL; bind params only; validate catalog_id + params;
  least-privilege DB role (SELECT-only).
- 12c Prompt injection defenses: treat all text (user + chunks) as hostile; separate
  instruction/data; model has no authority by design; structured output validation; scope injected
  server-side; refusal behavior; never echo secrets/system prompt.
- 12d Guardrails layer: library (NeMo/Guardrails AI) OR custom input_guard()/output_guard()
  (input: length cap, injection-pattern strip/flag, off-topic/abuse reject, rate-limit; output:
  schema validation, groundedness check, secret scan, citation validity; PII redaction). Every
  guardrail trip logged as guardrail_block.
- 12e General hardening: upload validation (type allowlist, max size, outside web root, filename
  scan); rate-limit auth + LLM; CORS locked; security headers; never trust client role/scope.
- 12f Caching (Redis): embedding cache (long TTL); retrieval/answer cache keyed by
  (query, mode, role-scope) (short TTL); dashboard data cache keyed by (catalog_id, scope, params)
  (short TTL, invalidate on writes); reranker model loaded once at startup; namespaced keys, always
  include role/scope for permission-sensitive results.

## 13. UI direction

Clean modern trustworthy. Palette: bg `#F8F7F4`, navy `#0F1F3D`, amber `#F59E0B`, answer tint
`#FFFBEB` w/ amber left border, cited badge green `#16A34A`, highlight `#FCD34D`. Font Inter. Render
LLM answers as markdown. Citation pills monospace. Design loading/empty/refusal states.

## 14. Build order (phases)

0 Scaffold · 1 Auth & roles · 2 Schema & synthetic data · 3 Ingestion module · 4 Async ingestion
queue · 5 Hybrid retrieval + reranker · 6 Document search page (+ caches) · 7 Manage Documents page
· 8 SQL catalog + data widget · 9 Dashboards + analysis (+ dashboard cache) · 10 Manage
employees/users + audit log · 11 Security & guardrails pass · 12 Polish. Confirm each works before
moving on; if a phase gets large, stop and check in.

## 15. Hard constraints (do NOT violate)

- LLM never writes or sees raw SQL — only picks a catalog id + params.
- Role/scope enforced in backend, always — never trust LLM/frontend/client role/scope.
- All SQL bind params; catalog params schema-validated before binding; least-privilege DB role.
- Treat all text reaching the LLM as untrusted (incl. chunks); a successful prompt injection must
  still be unable to run an unapproved query or cross scope — enforced by design.
- Every LLM call passes input/output guardrails; every block audit-logged.
- No secrets in code or git — Vault only.
- Synthetic data only.
- Don't build features not in this brief without asking first. If a phase gets large, stop and check in.

## 16. What to ask the owner before starting

Confirm: (a) embedding model + dimension; (b) app-support corpus RAG vs static FAQ; (c) Alpine.js
vs htmx vs vanilla JS; (d) guardrails: library vs custom wrapper. Then begin at Phase 0.
