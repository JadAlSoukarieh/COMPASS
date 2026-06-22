from __future__ import annotations

from datetime import date
from math import log2

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.models import Chunk, Document, Employee, User, UserRole
from backend.app.retrieval.search import search
from backend.app.security.auth import hash_password
from data.evals import load_golden_dataset


class FakeReranker:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for _, text in pairs:
            lowered = text.lower()
            if "annual leave" in lowered:
                scores.append(0.95)
            elif "travel claims" in lowered or "reimbursement" in lowered:
                scores.append(0.90)
            else:
                scores.append(0.10)
        return scores


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


def _embedding_for_query(query: str) -> list[float]:
    lowered = query.lower()
    if "travel" in lowered or "reimbursement" in lowered or "claims" in lowered:
        return [0.0, 1.0, 0.0]
    return [1.0, 0.0, 0.0]


def _reciprocal_rank(doc_codes: list[str], relevant_doc_codes: set[str]) -> float:
    for index, doc_code in enumerate(doc_codes, start=1):
        if doc_code in relevant_doc_codes:
            return 1.0 / index
    return 0.0


def _dcg(doc_codes: list[str], relevant_doc_codes: set[str]) -> float:
    score = 0.0
    for index, doc_code in enumerate(doc_codes, start=1):
        gain = 1.0 if doc_code in relevant_doc_codes else 0.0
        if gain:
            score += gain / log2(index + 1)
    return score


def test_golden_dataset_validates_hybrid_search_metrics() -> None:
    dataset = load_golden_dataset()
    cases = [case for case in dataset["cases"] if case["kind"] == "search_retrieval"]
    session_factory = _build_session_factory()
    _seed_ready_corpus(session_factory)

    hit_count = 0
    mrr_total = 0.0
    ndcg_total = 0.0
    forbidden_hits = 0

    with session_factory() as session:
        for case in cases:
            query = case["request"]["query"]
            expected = case["expected"]
            relevant_doc_codes = set(expected["relevant_doc_codes"])
            forbidden_doc_codes = set(expected["forbidden_doc_codes"])

            results = search(
                query,
                session=session,
                embedder=lambda texts, query=query: [_embedding_for_query(query) for _ in texts],
                reranker=FakeReranker(),
                candidate_limit=5,
                top_k=5,
            )
            returned_doc_codes = [item["doc_code"] for item in results]

            hit_count += int(any(doc_code in relevant_doc_codes for doc_code in returned_doc_codes))
            mrr_total += _reciprocal_rank(returned_doc_codes, relevant_doc_codes)
            dcg = _dcg(returned_doc_codes, relevant_doc_codes)
            idcg = _dcg(list(relevant_doc_codes), relevant_doc_codes)
            ndcg_total += 0.0 if idcg == 0.0 else dcg / idcg
            forbidden_hits += int(any(doc_code in forbidden_doc_codes for doc_code in returned_doc_codes))

            assert returned_doc_codes[0] == expected["primary_doc_code"]
            assert sum(1 for doc_code in returned_doc_codes if doc_code in relevant_doc_codes) >= expected["min_relevant_count_in_top_k"]
            assert not any(doc_code in forbidden_doc_codes for doc_code in returned_doc_codes)

    case_count = len(cases)
    metrics = {
        "hit_at_5": hit_count / case_count,
        "mrr": mrr_total / case_count,
        "ndcg_at_5": ndcg_total / case_count,
        "forbidden_doc_leakage_rate": forbidden_hits / case_count,
    }

    assert metrics == {
        "hit_at_5": 1.0,
        "mrr": 1.0,
        "ndcg_at_5": 1.0,
        "forbidden_doc_leakage_rate": 0.0,
    }
