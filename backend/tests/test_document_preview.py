"""Document preview/download route behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.models import AuditLog, Chunk, Document, Employee, User, UserRole
from backend.app.routers.documents import document_chunk_preview, document_file
from backend.app.security.auth import AuthenticatedUser


class FakeStorage:
    def __init__(self) -> None:
        self.objects = {"s3://compass-documents/POL-1.pdf": b"%PDF-1.4 fake pdf bytes"}

    def get(self, locator):
        return self.objects[locator]

    def exists(self, locator):
        return locator in self.objects


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
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.add(User(id=1, username="emp", password_hash="pw-emp", role=UserRole.EMP))
        session.add_all(
            [
                Document(
                    id=1,
                    doc_code="POL-1",
                    title="Leave Policy",
                    doc_type="policy",
                    source_path="s3://compass-documents/POL-1.pdf",
                    page_count=1,
                    embedding_status="ready",
                    uploaded_by=1,
                    chunk_count=1,
                ),
                Document(
                    id=2,
                    doc_code="POL-2",
                    title="Other Policy",
                    doc_type="policy",
                    source_path="s3://compass-documents/POL-1.pdf",
                    page_count=1,
                    embedding_status="ready",
                    uploaded_by=1,
                    chunk_count=1,
                ),
            ]
        )
        session.add_all(
            [
                Chunk(
                    id=10,
                    document_id=1,
                    page=4,
                    chunk_index=0,
                    text="New joiners receive annual leave after probation.",
                    embedding=None,
                    tsv="annual leave probation",
                ),
                Chunk(
                    id=20,
                    document_id=2,
                    page=1,
                    chunk_index=0,
                    text="This chunk belongs to another document.",
                    embedding=None,
                    tsv="other",
                ),
            ]
        )
        session.commit()
    return factory


@pytest.fixture()
def current_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        username="emp",
        role=UserRole.EMP,
        employee_id=None,
        is_active=True,
    )


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(storage=FakeStorage())))


def test_preview_returns_file_bytes_inline_for_pdf(
    session_factory: sessionmaker[Session],
    current_user: AuthenticatedUser,
) -> None:
    with session_factory() as session:
        response = document_file(1, request=_request(), current_user=current_user, session=session)

    assert response.body.startswith(b"%PDF")
    assert response.media_type == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert "POL-1.pdf" in response.headers["content-disposition"]


def test_preview_404_for_unknown_document(
    session_factory: sessionmaker[Session],
    current_user: AuthenticatedUser,
) -> None:
    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            document_file(999, request=_request(), current_user=current_user, session=session)

    assert exc.value.status_code == 404


def test_chunk_preview_returns_selected_retrieval_chunk(
    session_factory: sessionmaker[Session],
    current_user: AuthenticatedUser,
) -> None:
    with session_factory() as session:
        payload = document_chunk_preview(1, 10, current_user=current_user, session=session)

    assert payload.document_id == 1
    assert payload.chunk_id == 10
    assert payload.page == 4
    assert payload.text == "New joiners receive annual leave after probation."


def test_chunk_preview_rejects_chunk_from_other_document(
    session_factory: sessionmaker[Session],
    current_user: AuthenticatedUser,
) -> None:
    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            document_chunk_preview(1, 20, current_user=current_user, session=session)

    assert exc.value.status_code == 404
