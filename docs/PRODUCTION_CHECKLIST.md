# Production Checklist

Compass is intended to move from a synthetic-data proof of concept to a production deployment. Use
this checklist before connecting real users, real documents, or real HR/business data.

## Secrets

- Replace Vault dev mode with durable Vault or a managed secret store.
- Rotate all development credentials.
- Store `OPENAI_API_KEY`, JWT signing keys, database passwords, and object-storage credentials only
  in the secret manager.
- Verify application logs never print secret values.

## Infrastructure

- Run PostgreSQL with backups, restore testing, monitoring, and least-privilege roles.
- Run Redis with appropriate network restrictions.
- Run object storage with private buckets and scoped credentials.
- Serve the app over TLS.
- Configure production domain, CORS, cookies, and session settings.
- Disable development reload flags in production containers.

## Data

- Classify the document corpus before ingestion.
- Decide which roles can access each document category.
- Keep proprietary documents outside Git.
- Validate retention and deletion requirements.
- Confirm whether salary, leave, and employee data require additional legal or HR approval.

## AI Controls

- Keep the LLM limited to intent selection, grounded answer generation, and scoped analysis.
- Do not allow generated SQL.
- Do not include raw database schema or secrets in prompts.
- Keep citation validation enabled.
- Keep refusals for weak evidence, invalid citations, and out-of-scope requests.
- Re-run prompt-injection tests after prompt or retrieval changes.

## Observability

- Centralize application logs.
- Retain audit logs for admin writes, data questions, refusals, and guardrail blocks.
- Monitor ingestion failures, OpenAI failures, latency, and cache hit rate.
- Add alerting for repeated guardrail blocks or unusual query volume.

## Validation

Run before cutover:

```bash
python -m pytest backend/tests -q
python scripts/check_no_string_sql.py
```

Verify manually:

- employee cannot retrieve peer/private data;
- manager sees only team-scoped data;
- HR sees company HR data but cannot bypass catalog constraints;
- superuser actions are audit logged;
- poisoned document text cannot override system behavior;
- weak-evidence document answers refuse instead of hallucinating;
- uploaded documents move through pending, processing, ready, and failed states correctly.
