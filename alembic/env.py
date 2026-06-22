from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app.config import get_bootstrap_settings, get_settings
from backend.app.db import Base, _database_url
from backend.app.models import AuditLog, Chunk, Document, Employee, LeaveBalance, LeaveRequest, User

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolved_database_url() -> str:
    try:
        settings = get_settings()
        return _database_url(settings, "admin")
    except Exception:
        bootstrap = get_bootstrap_settings()
        password = Path(".env").exists() and "postgres" or "postgres"
        return (
            f"postgresql+psycopg://{bootstrap.postgres_admin_user}:{password}"
            f"@{bootstrap.postgres_host}:{bootstrap.postgres_port}/{bootstrap.postgres_db}"
        )


def run_migrations_offline() -> None:
    context.configure(
        url=_resolved_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolved_database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

