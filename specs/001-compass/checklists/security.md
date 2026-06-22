# Security Checklist: Compass

**Purpose**: Verify the non-negotiable security posture before any demo/merge.
**Created**: 2026-06-15
**Feature**: [spec.md](../spec.md) · [constitution](../../../.specify/memory/constitution.md)

## LLM is not a security boundary
- [ ] LLM output for data questions is ONLY `{catalog_id, params}` (no SQL, no table names).
- [ ] A successful prompt injection cannot run an unapproved query or cross a scope boundary (by design).
- [ ] Scope is taken from the validated JWT server-side, never from the message or the model.

## SQL injection
- [ ] No string-built SQL anywhere (grep/lint gate passes on `backend/` + `ingestion/`).
- [ ] Every catalog query uses bind parameters only.
- [ ] `catalog_id` validated against the registry before use.
- [ ] Every param validated vs its schema (type/range/allowed/existence) before binding.
- [ ] App request-path uses least-privilege `compass_app` (SELECT + audit INSERT only).

## Prompt injection / untrusted text
- [ ] System prompt holds rules; user input + retrieved chunks are fenced as labeled data.
- [ ] Structured outputs are schema-validated and repaired/rejected — never `eval`'d.
- [ ] The catalog `sql` field is never serialized into any prompt.

## Guardrails & audit
- [ ] `input_guard()` runs before every LLM call (length cap, injection flag, off-topic/abuse, rate limit).
- [ ] `output_guard()` runs after every LLM call (schema, groundedness in RAG, secret scan, citation validity).
- [ ] Every guardrail trip is audit-logged as `guardrail_block` with a reason.
- [ ] Every meaningful action writes an `audit_log` row with detail JSONB.

## Secrets & data
- [ ] All secrets fetched from Vault via hvac at startup; none in code/git.
- [ ] `.env` and key files are git-ignored; `.env.example` committed blank.
- [ ] Secrets never logged.
- [ ] Synthetic data only — no real company data.

## Hardening
- [ ] Uploads validated (type allowlist, max size, filename scan, stored outside web root).
- [ ] Auth + LLM endpoints rate-limited; CORS locked to app origin; security headers set.
- [ ] PII the requester isn't entitled to is redacted before reaching the LLM.

## Caching
- [ ] Permission-sensitive cache keys include role/scope.
- [ ] No cache entry can be served across a role/scope boundary.
- [ ] Dashboard cache busted on relevant writes.

## Attack-case suite (SC-004)
- [ ] Injection string in a user message → blocked + logged.
- [ ] Injection string inside a retrieved document chunk → harmless + logged.
- [ ] Scope-escalation attempt (emp→peer, mgr→non-report) → refused/scoped + logged.
- [ ] Unknown `catalog_id` → rejected before any DB call + logged.
- [ ] Out-of-range param → rejected before binding + logged.
