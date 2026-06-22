from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.db import ensure_database_roles, get_database_url, get_engine


APP_GRANTS = (
    "GRANT SELECT ON users, employees, leave_balances, leave_requests, documents, chunks, audit_log TO compass_app",
    "GRANT INSERT ON audit_log TO compass_app",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO compass_app",
)

WRITER_GRANTS = (
    "GRANT SELECT, INSERT, UPDATE, DELETE ON users, employees, leave_balances, leave_requests, documents, chunks, audit_log TO compass_writer",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO compass_writer",
)


def _alembic_config() -> Config:
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("script_location", str(Path("alembic").resolve()))
    config.set_main_option("sqlalchemy.url", get_database_url("admin"))
    return config


def run_migrations() -> None:
    command.upgrade(_alembic_config(), "head")


def apply_role_grants(engine: Engine | None = None) -> None:
    active_engine = engine or get_engine("admin")
    with active_engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            return
        for statement in APP_GRANTS:
            conn.execute(text(statement))
        for statement in WRITER_GRANTS:
            conn.execute(text(statement))


def bootstrap_schema() -> None:
    ensure_database_roles()
    run_migrations()
    apply_role_grants(get_engine("admin"))
