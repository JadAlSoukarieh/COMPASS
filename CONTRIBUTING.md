# Contributing

Compass is built security-first. Changes that touch authentication, authorization, retrieval,
catalog queries, LLM prompts, or document ingestion should be reviewed carefully.

## Local Development

```bash
cp .env.example .env
docker compose up -d
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

## Pull Request Checklist

- Keep secrets out of the diff.
- Keep real documents out of the diff.
- Add or update tests for behavior changes.
- Preserve backend scope enforcement.
- Do not add raw SQL generation by the LLM.
- Do not expose catalog SQL or table names to prompts.
- Update README or docs when setup, security, or production behavior changes.

## Commit Hygiene

Stage files explicitly. Avoid `git add -A` unless you have reviewed every changed file.

Useful checks:

```bash
git diff --stat
git diff
git status -sb
```

If you see `.env`, `data/docs/`, `.runtime/`, model caches, or proprietary files in the staged diff,
unstage them before pushing.
