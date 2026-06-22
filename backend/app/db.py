from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import RuntimeSettings, get_settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base."""


def _quote_identifier(connection: Connection | Engine, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _role_statement(connection: Connection, template: str, *, password: str) -> str:
    return connection.execute(
        text(f"SELECT format({template!r}, CAST(:password AS text))"),
        {"password": password},
    ).scalar_one()


def _database_url(settings: RuntimeSettings, role: str) -> str:
    if role == "admin":
        username = settings.postgres_admin_user
        password = settings.postgres_password.get_secret_value()
    elif role == "writer":
        username = "compass_writer"
        password = settings.compass_writer_password.get_secret_value()
    else:
        username = "compass_app"
        password = settings.compass_app_password.get_secret_value()

    encoded_password = quote_plus(password)
    return (
        f"postgresql+psycopg://{username}:{encoded_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def get_database_url(role: str = "app") -> str:
    return _database_url(get_settings(), role)


@lru_cache(maxsize=3)
def get_engine(role: str = "app") -> Engine:
    settings = get_settings()
    return create_engine(_database_url(settings, role), pool_pre_ping=True, future=True)


@lru_cache(maxsize=2)
def get_session_factory(role: str = "app") -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(role), autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(role: str = "app") -> Session:
    session = get_session_factory(role)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_app_session():
    with session_scope("app") as session:
        yield session


def get_writer_session():
    with session_scope("writer") as session:
        yield session


def ensure_database_roles() -> None:
    settings = get_settings()
    engine = get_engine("admin")

    with engine.begin() as conn:
        quoted_database = _quote_identifier(conn, settings.postgres_db)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        app_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'compass_app'")
        ).scalar_one_or_none()
        writer_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'compass_writer'")
        ).scalar_one_or_none()

        if app_exists is None:
            conn.exec_driver_sql(
                _role_statement(
                    conn,
                    "CREATE ROLE compass_app LOGIN PASSWORD %L NOINHERIT",
                    password=settings.compass_app_password.get_secret_value(),
                )
            )
        else:
            conn.exec_driver_sql(
                _role_statement(
                    conn,
                    "ALTER ROLE compass_app LOGIN PASSWORD %L NOINHERIT",
                    password=settings.compass_app_password.get_secret_value(),
                )
            )

        if writer_exists is None:
            conn.exec_driver_sql(
                _role_statement(
                    conn,
                    "CREATE ROLE compass_writer LOGIN PASSWORD %L NOINHERIT",
                    password=settings.compass_writer_password.get_secret_value(),
                )
            )
        else:
            conn.exec_driver_sql(
                _role_statement(
                    conn,
                    "ALTER ROLE compass_writer LOGIN PASSWORD %L NOINHERIT",
                    password=settings.compass_writer_password.get_secret_value(),
                )
            )

        conn.execute(text(f"GRANT CONNECT ON DATABASE {quoted_database} TO compass_app"))
        conn.execute(text(f"GRANT CONNECT ON DATABASE {quoted_database} TO compass_writer"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO compass_app"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO compass_writer"))


def database_healthcheck() -> bool:
    with get_engine("app").connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
