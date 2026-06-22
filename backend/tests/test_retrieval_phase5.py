from __future__ import annotations

from datetime import date
import importlib
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.models import Chunk, Document, Employee, User, UserRole
from backend.app.retrieval.search import reciprocal_rank_fusion, search
from backend.app.security.auth import hash_password

rerank_module = importlib.import_module("backend.app.retrieval.rerank")


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


def _seed_ready_corpus(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        employee = Employee(
            full_name="Search Demo",
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
            username="searcher",
            password_hash=hash_password("pw"),
            role=UserRole.HR,
            employee_id=employee.id,
            is_active=True,
        )
        session.add(user)
        session.flush()

        ready_leave = Document(
            doc_code="POL-LEAVE",
            title="Leave Policy",
            doc_type="policy",
            source_path="/tmp/leave.txt",
            page_count=1,
            embedding_status="ready",
            uploaded_by=user.id,
        )
        ready_travel = Document(
            doc_code="POL-TRAVEL",
            title="Travel Policy",
            doc_type="policy",
            source_path="/tmp/travel.txt",
            page_count=1,
            embedding_status="ready",
            uploaded_by=user.id,
        )
        pending_leave = Document(
            doc_code="POL-PENDING",
            title="Pending Leave Draft",
            doc_type="policy",
            source_path="/tmp/pending.txt",
            page_count=1,
            embedding_status="pending",
            uploaded_by=user.id,
        )
        session.add_all([ready_leave, ready_travel, pending_leave])
        session.flush()

        session.add_all(
            [
                Chunk(
                    document_id=ready_leave.id,
                    page=1,
                    chunk_index=0,
                    text="New joiners receive 15 days of annual leave in their first year.",
                    embedding=[1.0, 0.0, 0.0],
                    tsv="annual leave new joiners first year",
                ),
                Chunk(
                    document_id=ready_travel.id,
                    page=1,
                    chunk_index=0,
                    text="Travel claims must be submitted within 30 days of return.",
                    embedding=[0.0, 1.0, 0.0],
                    tsv="travel claims expenses reimbursement",
                ),
                Chunk(
                    document_id=pending_leave.id,
                    page=1,
                    chunk_index=0,
                    text="Pending draft says annual leave may change.",
                    embedding=[1.0, 0.0, 0.0],
                    tsv="annual leave pending draft",
                ),
            ]
        )
        session.commit()


class FakeReranker:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for _, text in pairs:
            if "annual leave" in text.lower():
                scores.append(0.95)
            else:
                scores.append(0.2)
        return scores


def test_reciprocal_rank_fusion_prefers_shared_hits() -> None:
    fused = reciprocal_rank_fusion([[10, 11, 12], [11, 10, 13]])
    assert fused[11] > fused[12]
    assert fused[10] > fused[13]


def test_search_ranks_ready_documents_with_provenance() -> None:
    session_factory = _build_session_factory()
    _seed_ready_corpus(session_factory)

    with session_factory() as session:
        results = search(
            "how much annual leave do new joiners get",
            session=session,
            embedder=lambda texts: [[1.0, 0.0, 0.0] for _ in texts],
            reranker=FakeReranker(),
            candidate_limit=5,
            top_k=3,
        )

    assert results[0]["doc_code"] == "POL-LEAVE"
    assert results[0]["page"] == 1
    assert "annual leave" in results[0]["snippet"].lower()
    assert all(result["doc_code"] != "POL-PENDING" for result in results)


def test_search_respects_top_k_limit() -> None:
    session_factory = _build_session_factory()
    _seed_ready_corpus(session_factory)

    with session_factory() as session:
        results = search(
            "leave travel annual claims",
            session=session,
            embedder=lambda texts: [[1.0, 1.0, 0.0] for _ in texts],
            reranker=FakeReranker(),
            candidate_limit=2,
            top_k=1,
        )

    assert len(results) == 1


def test_search_falls_back_to_keyword_only_when_embedding_fails() -> None:
    session_factory = _build_session_factory()
    _seed_ready_corpus(session_factory)

    with session_factory() as session:
        results = search(
            "annual leave new joiners",
            session=session,
            embedder=lambda texts: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
            reranker=FakeReranker(),
            candidate_limit=5,
            top_k=3,
        )

    assert results
    assert results[0]["doc_code"] == "POL-LEAVE"
    assert "annual leave" in results[0]["snippet"].lower()


def test_preload_reranker_updates_state(monkeypatch) -> None:
    loaded = Event()

    def fake_load_reranker(model_name: str | None = None):
        loaded.set()
        return {"model_name": model_name or "demo"}

    state = {"loaded": False, "instance": None, "error": None, "preload_started": False}
    monkeypatch.setattr(rerank_module, "load_reranker", fake_load_reranker)

    rerank_module.preload_reranker("demo-reranker", target=state, async_load=False)

    assert loaded.is_set()
    assert state["loaded"] is True
    assert state["instance"] == {"model_name": "demo-reranker"}
    assert state["error"] is None
