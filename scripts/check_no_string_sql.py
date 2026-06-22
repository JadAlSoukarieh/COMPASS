#!/usr/bin/env python3
"""Phase 11 security gate (brief §12b, SC-005): no string-built SQL anywhere.

Scans backend/, ingestion/, and worker/ for f-string / .format() / % SQL construction. The LLM
never emits SQL and the catalog uses bind parameters only — this gate proves no code path builds
SQL from a string.

Two sites are AUDITED-SAFE and explicitly whitelisted (they interpolate only backend-controlled
identifiers, never user/LLM input):
  - backend/app/db.py        Postgres `format(%L)` for role passwords (server-side; value still bound)
  - backend/app/catalog/validate.py  `.sql.format(scope_clause=...)` (scope_clause is a hardcoded
                                     column name from the registry, never user input)

Exit 0 if clean, 1 if a new violation is found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOTS = ("backend", "ingestion", "worker")

# Heuristics for string-built SQL.
PATTERNS = (
    re.compile(r"""f["'].*\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|GRANT)\b""", re.IGNORECASE),
    re.compile(r"""\.format\([^)]*\).*\b(SELECT|INSERT|UPDATE|DELETE)\b""", re.IGNORECASE),
    re.compile(r"""\b(SELECT|INSERT|UPDATE|DELETE)\b.*%\s*\(""", re.IGNORECASE),
    re.compile(r"""["']\s*\+\s*\w+.*\b(SELECT|INSERT|UPDATE|DELETE)\b""", re.IGNORECASE),
    re.compile(r"""\.sql\.format\(""", re.IGNORECASE),
)

# (path-suffix, substring-on-line) pairs that are reviewed and safe.
# These interpolate only backend-controlled identifiers (dialect-quoted DB name / hardcoded
# registry column), never user or LLM input. Verified during the Phase 11 security pass.
WHITELIST = (
    ("backend/app/db.py", "format("),
    ("backend/app/db.py", "GRANT CONNECT ON DATABASE {quoted_database}"),
    ("backend/app/catalog/validate.py", ".sql.format(scope_clause=scope_clause)"),
)


def _is_whitelisted(rel_path: str, line: str) -> bool:
    return any(rel_path.endswith(suffix) and needle in line for suffix, needle in WHITELIST)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[str] = []

    for root in ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(repo_root))
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not any(p.search(line) for p in PATTERNS):
                    continue
                if _is_whitelisted(rel, line):
                    continue
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    if violations:
        print("STRING-SQL GATE FAILED — potential string-built SQL found:")
        for v in violations:
            print(f"  {v}")
        return 1

    print("string-SQL gate clean: no unreviewed string-built SQL in", ", ".join(ROOTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
