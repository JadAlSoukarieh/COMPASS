# Compass

Compass is a role-aware internal company assistant for finding documents, answering approved data
questions, and analyzing scoped business data without turning the LLM into a security boundary.

For recruiters and reviewers: this is not a toy chatbot wrapper. Compass is a production-oriented
RAG and data-assistant system built around secure retrieval, scoped authorization, auditability, and
LLM guardrails.

The application is moving toward production use for a real company deployment with a target corpus of
about 4,000 internal documents. This repository is prepared for GitHub with synthetic/demo data only:
real customer documents, production secrets, and private deployment configuration must stay outside
the repo.

## What Compass Does

- **Semantic document search:** users search by meaning instead of exact document code or title.
- **Grounded answers:** generated answers cite retrieved chunks and refuse when evidence is weak.
- **SQL catalog assistant:** the LLM selects from pre-approved query intents; it never writes raw SQL.
- **Scoped dashboards:** HR, manager, employee, and superuser views only expose data allowed by role.
- **Admin operations:** document ingestion, employee/user management, and audit logs are built in.
- **Security-first AI flow:** prompts can suggest, but deterministic backend checks decide.

Core principle:

> The AI suggests. The backend decides.

## Production Status

Compass started as a proof of concept with synthetic data and is being prepared for production
deployment. The production direction is:

- scale the document corpus to roughly 4,000 internal documents;
- keep OpenAI keys and signing secrets in Vault, never in source control;
- keep proprietary documents out of the repository and load them through controlled ingestion;
- preserve backend-enforced authorization for every document, dashboard, and data answer;
- keep the LLM constrained to catalog selection, grounded answer generation, and analysis.

Before a production cutover, use [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md).

## Architecture

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 16 with pgvector |
| Embeddings | OpenAI `text-embedding-3-small` |
| Chat model | OpenAI `gpt-4.1-mini` by default |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Queue/cache | Redis + RQ |
| Secrets | HashiCorp Vault |
| Object storage | MinIO/S3-compatible storage |
| Frontend | Jinja templates, Alpine.js, custom CSS |
| Containers | Docker Compose |

```text
backend/app/   FastAPI app, routers, security, catalog, LLM, retrieval, cache
ingestion/     Extract, clean, chunk, embed, and index pipeline
worker/        RQ worker for async document ingestion
frontend/      Templates and static assets
data/seed/     Synthetic employees, users, leave balances, demo fixtures
data/evals/    Golden evaluation dataset
specs/         Product spec, plan, contracts, and task notes
alembic/       Database migrations
```

## Security Model

Compass is designed so that an LLM failure does not become an authorization failure.

- The LLM never receives raw SQL and never writes SQL.
- Catalog queries are parameterized and validated server-side.
- Role and scope come from signed JWT claims and database state, not from the browser or the model.
- Search and dashboard cache keys include role/scope to avoid cross-permission leakage.
- Retrieved chunks are treated as untrusted data and passed through guardrails.
- Answers must cite retrieved chunks; invalid or unsupported citations are rejected.
- Secrets are loaded from Vault and are ignored by Git.
- Audit logs record sensitive actions, refusals, and guardrail blocks.

More detail: [SECURITY.md](SECURITY.md).

## Local Setup

Prerequisites:

- Docker and Docker Compose
- Python 3.12 if running tests locally outside Docker
- An OpenAI API key

Create your local environment:

```bash
cp .env.example .env
```

Put your key in `.env`:

```bash
OPENAI_API_KEY=sk-...
```

Start the stack:

```bash
docker compose up -d
```

Open:

```text
http://localhost:8000
```

Vault dev mode stores secrets in memory, so the compose stack includes `vault-init` and `vault-sync`
to seed Vault from `.env` whenever the dev Vault loses its data.

## Demo Users

The demo login screen includes one-click sign-in options for:

- `superuser`
- `hr`
- `mgr`
- `emp`

The local demo passwords are configured in `.env`. Do not commit real passwords.

## Ingest Documents

Local documents can be placed under `data/docs/`, but that directory is intentionally ignored by Git.
This prevents internal PDFs, Word files, Excel files, or customer material from being pushed.

Run ingestion:

```bash
docker compose exec api python -m ingestion.cli data/docs
```

Uploaded documents are stored in MinIO by default. The document table stores an `s3://...` locator;
the worker fetches the file back during processing.

## Tests

Install local dev dependencies if needed:

```bash
python -m pip install -e .[dev]
```

Run tests:

```bash
python -m pytest backend/tests -q
```

Run the SQL safety gate:

```bash
python scripts/check_no_string_sql.py
```

Golden retrieval metrics live in:

```text
data/evals/compass_golden_v1.json
```

## GitHub Hygiene

Before committing:

- Confirm `.env` is not staged.
- Confirm `data/docs/` is not staged.
- Confirm generated local files such as `.runtime/`, `.venv/`, model caches, and `DEMO_SCRIPT.pdf`
  are not staged.
- Review the diff for proprietary document names, customer data, or keys.

Recommended first commit after `git init`:

```bash
git add README.md SECURITY.md CONTRIBUTING.md docs/PRODUCTION_CHECKLIST.md .gitignore .dockerignore .gitattributes .env.example
git commit -m "Prepare Compass repository documentation"
```

If adding source code in the same push, stage it explicitly and review with:

```bash
git diff --cached --stat
git diff --cached
```

## License

No open-source license has been selected yet. Until a license is added, treat this repository as
all-rights-reserved/private project code.
