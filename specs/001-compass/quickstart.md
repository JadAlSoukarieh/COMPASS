# Quickstart: Compass

How to bring the system up and verify each phase. Synthetic data only; never use real secrets.

## Prerequisites
- Docker + Docker Compose
- An OpenAI API key (placed in Vault dev, never committed)
- Python 3.12 + the repo `.venv` (already created at repo root) for running the ingestion CLI/tests locally

## First run
```bash
cp .env.example .env            # fill in non-secret config; secrets go in Vault, not here
./vault_seed.sh                 # seed Vault (dev mode) with OpenAI key, DB password, JWT signing key
docker compose up               # brings up postgres(pgvector), redis, vault(dev), api, worker
```
Then open the app (default `http://localhost:8000`). All five services expose health checks; wait
until each is healthy.

## Seeded demo users
One user per role (superuser / hr / mgr / emp). Demo passwords are documented in `.env.example`
(blank/placeholder there — never commit real secrets). Use them to walk the role matrix.

## Verify each phase (gates from plan.md)
- **Phase 0**: `docker compose up` → all services healthy; `/health` endpoints return OK; Redis cache
  helper round-trips a value; Vault returns seeded secrets at API startup.
- **Phase 1**: Log in as each of the four roles → JWT issued with user_id+role; role-guarded routes
  allow/deny per the matrix.
- **Phase 2**: Seed script populates ~50–80 employees with a manager hierarchy, salary spread, leave
  balances, and pending/approved leave requests; spot-check with a read query.
- **Phase 3**: Run the ingestion CLI on a sample doc → a row in `chunks` has a non-null `embedding`
  and a populated `tsv`; GIN + HNSW indexes exist.
- **Phase 4**: Enqueue an ingestion job → worker moves the document pending→processing→ready, sets
  `chunk_count`/`processed_at`; force a failure → failed + `error_message`; retry succeeds.
- **Phase 5**: From a script, call `search()` → fused + reranked results are sensibly ranked with
  doc_code/page/score provenance.
- **Phase 6**: Document Search page → Analyze OFF returns ranked chunks; Analyze ON returns grounded
  markdown with citations that map to retrieved chunks; weak evidence → refusal; status line shows
  model · hybrid · reranked · N retrieved · k cited · latency; repeat search hits cache.
- **Phase 7**: Manage Documents upload → 202 + live status badge progresses to Ready; failed doc
  shows error + working retry; emp denied access.
- **Phase 8**: Widget data question → LLM returns only `{catalog_id, params}`; backend validates +
  scopes + runs parameterized query + phrases answer; emp asking about a peer is refused/scoped;
  unknown catalog_id or out-of-range param rejected before any DB call; all logged.
- **Phase 9**: Dashboards scoped per role; "Ask Compass to analyze this" summarizes only backend-
  fetched scoped rows; repeat dashboard loads hit cache; a write busts the relevant keys.
- **Phase 10**: Manage Employees/Users works for hr/superuser; Audit Logs page filters by user,
  action_type, date and renders JSONB detail.
- **Phase 11**: Run the attack-case suite (injection in user input and in documents, scope
  escalation, unknown catalog id, out-of-range param) → all blocked/scoped and audit-logged as
  `guardrail_block` where applicable; grep/lint gate confirms zero string-built SQL.
- **Phase 12**: End-to-end walkthrough as each role; loading/empty/refusal states present; answers
  render as markdown with citation pills.

## Security smoke checks (run before any demo)
- `grep -rnE "f\".*SELECT|\.format\(.*SELECT|%.*SELECT" backend/ ingestion/` → no matches (no
  string-built SQL).
- Confirm no prompt-building code path serializes the catalog `sql` field or any table name.
- Confirm `.env` and key files are git-ignored and absent from the index.
- Confirm cache keys for search/dashboard include role/scope.
