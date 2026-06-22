# Security Policy

Compass is an internal assistant that can retrieve company documents and answer scoped data
questions. Treat every deployment as security-sensitive.

## Supported Versions

This repository is currently pre-1.0. Security fixes should be applied to the active `main` branch
and any production deployment branch.

## Reporting a Vulnerability

Do not open a public issue with exploit details, secrets, customer data, or private document content.

Report security issues privately to the project maintainer or repository owner. Include:

- affected route or component;
- expected behavior;
- observed behavior;
- reproduction steps using synthetic data where possible;
- impact assessment;
- screenshots or logs only after removing secrets and personal data.

## Security Boundaries

The LLM is not a security boundary. Compass must remain safe if a model:

- follows a malicious instruction;
- returns malformed JSON;
- chooses an invalid catalog id;
- invents citations;
- attempts to reveal prompt content or secrets;
- is exposed to prompt injection inside a retrieved document.

Backend controls must enforce authorization, query allow-lists, parameter validation, output
validation, and audit logging.

## Required Controls

- Secrets must live in Vault or a production-grade secret manager.
- `.env` files, key files, and production configs must not be committed.
- The LLM must never receive raw SQL, table names, database credentials, or privileged secrets.
- Data questions must execute only pre-approved parameterized catalog queries.
- Role and scope must be derived server-side from authenticated identity.
- Document retrieval must respect user role/scope before answer generation.
- Generated answers must cite retrieved chunks or refuse.
- Admin writes must use explicit backend authorization and audit logging.
- Cache keys must include permission scope.
- Uploaded files must be treated as untrusted input.

## Production Requirements

Before production:

- replace Vault dev mode with a durable Vault/secret-manager deployment;
- rotate all development passwords, JWT signing keys, and MinIO credentials;
- use TLS for every external endpoint;
- configure CORS and cookie settings for the production domain only;
- enable database backups and restore drills;
- enable centralized application and audit logging;
- configure rate limits and upload size limits;
- restrict object-storage bucket access;
- review all documents for classification and access policy;
- run the security and regression test suites.

See [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md).

## Data Handling

The Git repository should contain only synthetic data and non-sensitive evaluation fixtures. Do not
commit:

- real company documents;
- customer data;
- employee personal data;
- salaries from a real HR system;
- production exports;
- OpenAI keys;
- Vault tokens;
- JWT signing keys;
- database passwords.

`data/docs/` is intentionally ignored. Load proprietary corpora through controlled deployment or
local ingestion, not through Git.
