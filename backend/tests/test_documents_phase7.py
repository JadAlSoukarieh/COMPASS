from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_app_session, get_writer_session
from backend.app.models import AuditLog, Chunk, Document, Employee, User, UserRole
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.routers.documents import router as documents_router
from backend.app.security import auth as auth_module
from worker import worker as worker_module


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def enqueue(self, fn, **kwargs):
        allowed = {"document_id", "source_path", "uploaded_by_user_id", "doc_type"}
        self.calls.append((fn, {key: value for key, value in kwargs.items() if key in allowed}))
        return SimpleNamespace(id=f"job-{len(self.calls)}")


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Employee.__table__, User.__table__, Document.__table__, Chunk.__table__, AuditLog.__table__],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def upload_root(tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    return root


@pytest.fixture()
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture()
def app(
    session_factory: sessionmaker[Session],
    upload_root: Path,
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    with session_factory() as session:
        manager = Employee(
            full_name="Manager Demo",
            department="Operations",
            grade="G8",
            manager_id=None,
            hire_date=date(2024, 1, 1),
            contract_end_date=None,
            salary=7000,
            status="active",
        )
        employee = Employee(
            full_name="Employee Demo",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 2, 1),
            contract_end_date=None,
            salary=3000,
            status="active",
        )
        session.add_all([manager, employee])
        session.flush()
        session.add_all(
            [
                User(username="superuser", password_hash=auth_module.hash_password("pw-super"), role=UserRole.SUPERUSER),
                User(username="hr", password_hash=auth_module.hash_password("pw-hr"), role=UserRole.HR),
                User(
                    username="emp",
                    password_hash=auth_module.hash_password("pw-emp"),
                    role=UserRole.EMP,
                    employee_id=employee.id,
                ),
            ]
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(auth_module, "get_jwt_signing_key", lambda: "test-signing-key")
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.state.limiter = limiter
    app.state.settings = SimpleNamespace(upload_root=str(upload_root))
    app.state.ingestion_queue = fake_queue
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.dependency_overrides[get_app_session] = override_session
    app.dependency_overrides[get_writer_session] = override_session
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}


def test_upload_returns_202_and_status_progresses(
    client: TestClient,
    session_factory: sessionmaker[Session],
    upload_root: Path,
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")

    @contextmanager
    def fake_session_scope(role: str = "writer"):
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def fake_run_ingestion_pipeline(
        source_path: str,
        *,
        uploaded_by_user_id: int,
        document_id: int | None,
        embedder,
        session: Session,
        doc_type: str | None,
        doc_code: str | None = None,
        title: str | None = None,
    ):
        document = session.get(Document, document_id)
        assert document is not None
        assert Path(source_path).exists()
        document.embedding_status = "ready"
        document.chunk_count = 3
        document.processed_at = datetime.now(UTC)
        return {"document_id": document.id, "chunk_count": 3}

    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)

    response = client.post(
        "/documents",
        headers=headers,
        data={"doc_code": "POL-UPLOAD-1", "title": "Upload Test", "doc_type": "policy"},
        files={"file": ("upload.csv", b"col1,col2\nalpha,beta\n", "text/csv")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["embedding_status"] == "pending"
    assert len(fake_queue.calls) == 1

    with session_factory() as session:
        document = session.get(Document, payload["document_id"])
        assert document is not None
        assert document.doc_code == "POL-UPLOAD-1"
        assert document.title == "Upload Test"
        assert document.embedding_status == "pending"
        assert Path(document.source_path).parent == upload_root
        assert Path(document.source_path).exists()

    job_fn, job_kwargs = fake_queue.calls[0]
    job_fn(**job_kwargs)

    status_response = client.get(f"/documents/{payload['document_id']}/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["embedding_status"] == "ready"
    assert status_response.json()["chunk_count"] == 3


def test_failed_document_can_retry_and_recover(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_queue: FakeQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "superuser", "pw-super")
    attempts = {"count": 0}

    @contextmanager
    def fake_session_scope(role: str = "writer"):
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def flaky_run_ingestion_pipeline(
        source_path: str,
        *,
        uploaded_by_user_id: int,
        document_id: int | None,
        embedder,
        session: Session,
        doc_type: str | None,
        doc_code: str | None = None,
        title: str | None = None,
    ):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("embedding failure")
        document = session.get(Document, document_id)
        assert document is not None
        document.embedding_status = "ready"
        document.chunk_count = 1
        document.processed_at = datetime.now(UTC)
        document.error_message = None
        return {"document_id": document.id, "chunk_count": 1}

    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_module, "run_ingestion_pipeline", flaky_run_ingestion_pipeline)

    create_response = client.post(
        "/documents",
        headers=headers,
        data={"doc_code": "HOW-RETRY-1", "title": "Retry Doc", "doc_type": "howto"},
        files={"file": ("retry.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert create_response.status_code == 202
    document_id = create_response.json()["document_id"]

    job_fn, job_kwargs = fake_queue.calls[0]
    with pytest.raises(RuntimeError):
        job_fn(**job_kwargs)

    failed_status = client.get(f"/documents/{document_id}/status", headers=headers)
    assert failed_status.status_code == 200
    assert failed_status.json()["embedding_status"] == "failed"
    assert failed_status.json()["error_message"] == "embedding failure"

    retry_response = client.post(f"/documents/{document_id}/reembed", headers=headers)
    assert retry_response.status_code == 202
    assert len(fake_queue.calls) == 2

    retry_fn, retry_kwargs = fake_queue.calls[1]
    retry_fn(**retry_kwargs)

    recovered = client.get(f"/documents/{document_id}/status", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["embedding_status"] == "ready"
    assert recovered.json()["error_message"] is None


def test_emp_is_denied_manage_documents_api(client: TestClient) -> None:
    headers = _login(client, "emp", "pw-emp")

    list_response = client.get("/documents", headers=headers)
    upload_response = client.post(
        "/documents",
        headers=headers,
        data={"doc_code": "POL-DENY-1", "title": "Denied", "doc_type": "policy"},
        files={"file": ("deny.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert list_response.status_code == 403
    assert upload_response.status_code == 403
