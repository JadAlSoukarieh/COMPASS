from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.models import Chunk, Document, Employee, User, UserRole
from backend.app.security.auth import hash_password
from worker import worker as worker_module


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Employee.__table__, User.__table__, Document.__table__, Chunk.__table__],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_document(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        employee = Employee(
            full_name="HR Demo",
            department="HR",
            grade="G7",
            manager_id=None,
            hire_date=date(2024, 1, 1),
            contract_end_date=None,
            salary=6000,
            status="active",
        )
        session.add(employee)
        session.flush()
        user = User(
            username="hr",
            password_hash=hash_password("pw"),
            role=UserRole.HR,
            employee_id=employee.id,
            is_active=True,
        )
        session.add(user)
        session.flush()
        document = Document(
            doc_code="DOC-TEST",
            title="Test",
            doc_type="policy",
            source_path="/tmp/test.txt",
            page_count=1,
            embedding_status="pending",
            uploaded_by=user.id,
        )
        session.add(document)
        session.commit()
        return document.id


def test_process_document_ingestion_success(monkeypatch) -> None:
    session_factory = _build_session_factory()
    document_id = _seed_document(session_factory)

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
    ):
        document = session.get(Document, document_id)
        assert document is not None
        assert document.embedding_status == "processing"
        document.embedding_status = "ready"
        document.chunk_count = 2
        document.processed_at = datetime.now(UTC)
        session.add(
            Chunk(document_id=document.id, page=1, chunk_index=0, text="Chunk one", embedding=None, tsv="Chunk one")
        )
        session.add(
            Chunk(document_id=document.id, page=1, chunk_index=1, text="Chunk two", embedding=None, tsv="Chunk two")
        )
        return {"document_id": document.id, "chunk_count": 2}

    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)

    worker_module.process_document_ingestion(
        document_id=document_id,
        source_path="/tmp/test.txt",
        uploaded_by_user_id=1,
    )

    with session_factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        assert document.embedding_status == "ready"
        assert document.chunk_count == 2
        assert session.query(Chunk).filter(Chunk.document_id == document_id).count() == 2


def test_process_document_ingestion_failure_marks_document_failed(monkeypatch) -> None:
    session_factory = _build_session_factory()
    document_id = _seed_document(session_factory)

    @contextmanager
    def fake_session_scope(role: str = "writer"):
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def fake_run_ingestion_pipeline(*args, **kwargs):
        raise RuntimeError("embedding failure")

    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)

    try:
        worker_module.process_document_ingestion(
            document_id=document_id,
            source_path="/tmp/test.txt",
            uploaded_by_user_id=1,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected RuntimeError")

    with session_factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        assert document.embedding_status == "failed"
        assert document.error_message == "embedding failure"


def test_enqueue_document_ingestion_uses_queue() -> None:
    class FakeQueue:
        def __init__(self) -> None:
            self.calls = []

        def enqueue(self, fn, **kwargs):
            self.calls.append((fn, kwargs))
            return "job-1"

    queue = FakeQueue()
    job_id = worker_module.enqueue_document_ingestion(
        document_id=4,
        source_path="/tmp/test.txt",
        uploaded_by_user_id=2,
        queue=queue,
    )

    assert job_id == "job-1"
    assert queue.calls[0][0] is worker_module.process_document_ingestion
    assert queue.calls[0][1]["document_id"] == 4


def test_process_document_ingestion_retry_succeeds_after_failure(monkeypatch) -> None:
    session_factory = _build_session_factory()
    document_id = _seed_document(session_factory)
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

    def fake_run_ingestion_pipeline(
        source_path: str,
        *,
        uploaded_by_user_id: int,
        document_id: int | None,
        embedder,
        session: Session,
        doc_type: str | None,
    ):
        attempts["count"] += 1
        document = session.get(Document, document_id)
        assert document is not None
        if attempts["count"] == 1:
            raise RuntimeError("transient failure")

        document.embedding_status = "ready"
        document.chunk_count = 1
        document.processed_at = datetime.now(UTC)
        document.error_message = None
        return {"document_id": document.id, "chunk_count": 1}

    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_module, "run_ingestion_pipeline", fake_run_ingestion_pipeline)

    with pytest.raises(RuntimeError):
        worker_module.process_document_ingestion(
            document_id=document_id,
            source_path="/tmp/test.txt",
            uploaded_by_user_id=1,
        )

    with session_factory() as session:
        failed_document = session.get(Document, document_id)
        assert failed_document is not None
        assert failed_document.embedding_status == "failed"
        assert failed_document.error_message == "transient failure"

    result = worker_module.process_document_ingestion(
        document_id=document_id,
        source_path="/tmp/test.txt",
        uploaded_by_user_id=1,
    )

    assert result["chunk_count"] == 1
    with session_factory() as session:
        recovered_document = session.get(Document, document_id)
        assert recovered_document is not None
        assert recovered_document.embedding_status == "ready"
        assert recovered_document.error_message is None
        assert recovered_document.chunk_count == 1


def test_reembed_document_ingestion_clears_chunks_and_resets_status(monkeypatch) -> None:
    session_factory = _build_session_factory()
    document_id = _seed_document(session_factory)
    with session_factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        document.embedding_status = "failed"
        document.error_message = "old"
        document.chunk_count = 1
        document.processed_at = datetime.now(UTC)
        session.add(Chunk(document_id=document_id, page=1, chunk_index=0, text="old", embedding=None, tsv="old"))
        session.commit()

    @contextmanager
    def fake_session_scope(role: str = "writer"):
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    class FakeQueue:
        def __init__(self) -> None:
            self.calls = []

        def enqueue(self, fn, **kwargs):
            self.calls.append((fn, kwargs))
            return "job-2"

    queue = FakeQueue()
    monkeypatch.setattr(worker_module, "session_scope", fake_session_scope)

    result = worker_module.reembed_document_ingestion(
        document_id=document_id,
        source_path="/tmp/test.txt",
        uploaded_by_user_id=1,
        queue=queue,
    )

    assert result == "job-2"
    with session_factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        assert document.embedding_status == "pending"
        assert document.error_message is None
        assert document.chunk_count is None
        assert document.processed_at is None
        assert session.query(Chunk).filter(Chunk.document_id == document_id).count() == 0
