# Research & Decisions: Compass

Resolves the four open clarifications from brief section 16 and records key technical decisions.

## Clarifications (brief §16) — CONFIRMED by owner 2026-06-15

### (a) Embedding model + dimension
**Decision (CONFIRMED):** OpenAI `text-embedding-3-small`, 1536-dim, stored in `vector(1536)`.
**Rationale:** Named in the brief's locked stack; cheapest capable OpenAI model; 1536 is the native
dimension and keeps the pgvector column and indexes simple.

### (b) App-support corpus (6c): RAG vs static FAQ
**Decision (CONFIRMED):** RAG over a small app-help corpus in `data/app_help/`.
**Rationale:** The brief explicitly prefers RAG for consistency with the document feature, and it
reuses the Phase 5 retrieval path instead of a parallel code path.

### (c) Frontend library: Alpine.js vs htmx vs vanilla
**Decision (CONFIRMED):** Alpine.js layered on server-rendered templates; no SPA.
**Rationale:** The widget, status badges, and Analyze toggle need light reactivity; Alpine keeps state
in markup with minimal build tooling.

### (d) Guardrails: library vs custom wrappers
**Decision (CONFIRMED):** Custom `input_guard()` / `output_guard()` wrappers.
**Rationale:** The brief calls this "simpler, fine for the project"; it keeps the guard logic auditable
and directly wired to `audit_log` (`guardrail_block`).

## Technical decisions

### Hybrid retrieval & fusion
- Keyword: Postgres `websearch_to_tsquery` + `ts_rank` over `chunks.tsv`.
- Vector: pgvector cosine distance (`<=>`) over `chunks.embedding`.
- Fusion: Reciprocal Rank Fusion (RRF) over the two ranked lists into one candidate set.
- Rerank: cross-encoder `ms-marco-MiniLM-L-6-v2` on the fused top-N → keep top-k.
- Single `search()` function returns candidates with scores + provenance (doc_code, page, chunk_id).

### Reranker model lifecycle
Load the cross-encoder once at API/worker startup and hold it in process memory; never reload per
request (brief §12f). This is in-memory, not Redis.

### Ingestion — one pipeline, two entry points (Constitution VIII)
`ingestion/pipeline.py` exposes the full extract→clean→chunk→embed→insert→tsv flow. The CLI
(`ingestion/cli.py`) and the RQ job (`worker/worker.py`) both call it; no duplicated logic. OCR
(Tesseract) only triggers when a PDF has no text layer. Documents are re-filed under invented doc
codes regardless of original filename (preserves the "find by meaning, not code" story).

### Async ingestion (Redis + RQ)
Upload returns 202 immediately; the worker owns the status machine pending→processing→ready/failed,
sets `chunk_count`/`processed_at` on success, stores the exception in `error_message` on failure.
Jobs are retryable and docs re-embeddable. One Redis service is both the RQ broker and the app cache.

### Security architecture (Constitution I–VI)
- The LLM returns only `{intent}` or `{catalog_id, params}` or a grounded answer — never SQL, never a
  table name. The `sql` field is never serialized into any prompt.
- `catalog_id` is validated against the registry; every param against its declared schema (type,
  range, allowed values, existence) before binding. All queries use bind parameters.
- Scope (self/team/company) is resolved from the validated JWT server-side and applied by the backend,
  not asked of the model. A successful prompt injection still cannot run an unapproved query or cross scope.
- Two DB roles: `compass_app` (SELECT + audit INSERT) for the request path; `compass_writer` for
  authorized admin/ingestion writes.
- Every LLM call is wrapped by input/output guards; every block is audit-logged as `guardrail_block`.

### Caching keys (Constitution §"cache keys")
Namespaced `emb:` / `search:` / `dash:`. Permission-sensitive keys always include role/scope so a
cached result is never served across a permission boundary. Dashboard keys are busted on relevant writes.

### Testing strategy
Unit: `clean_text()`, chunker, RRF fusion, param-schema validation, scope resolution, guards. Integration:
`search()` ranking, end-to-end ingestion job, per-role page/route walkthroughs, and a battery of attack
cases (injection strings in user input and in documents, scope-escalation attempts, unknown catalog ids,
out-of-range params) — all must be blocked/scoped and audit-logged (SC-004, SC-005).

## Risks & mitigations
- **OpenAI rate limits / latency during ingestion** → async worker off the request path; retry support.
- **OCR cost on large scanned PDFs** → OCR only when no text layer; CPU-bound work isolated to worker.
- **Cache leakage across roles** → role/scope baked into every permission-sensitive key; default to
  not caching when in doubt.
- **Prompt injection via poisoned documents** → chunks fenced as data; model has no authority by design.
