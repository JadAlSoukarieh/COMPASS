from __future__ import annotations

from collections.abc import Sequence
from math import sqrt
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from backend.app.db import session_scope
from backend.app.models import Chunk, Document
from backend.app.retrieval.rerank import rerank
from ingestion.pipeline import build_embeddings

RRF_K = 60
DEFAULT_CANDIDATE_LIMIT = 20
DEFAULT_TOP_K = 5
DEFAULT_MAX_PER_DOC = 2  # cap chunks from a single document in the displayed top-k (diversity)
SNIPPET_LENGTH = 240


def diversify_by_document(
    ranked: list[dict[str, Any]],
    *,
    top_k: int,
    max_per_doc: int,
) -> list[dict[str, Any]]:
    """Select top_k from a reranked list, capping how many chunks come from one document.

    A 762-page handbook can have many matching chunks; without this the top-k is dominated by a
    single document. We greedily take the highest-scoring chunks while respecting max_per_doc, then
    backfill from the remainder if the cap left fewer than top_k results.
    """
    selected: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []
    per_doc: dict[str, int] = {}
    for item in ranked:  # ranked is already sorted high→low
        doc = item.get("doc_code")
        if per_doc.get(doc, 0) < max_per_doc:
            selected.append(item)
            per_doc[doc] = per_doc.get(doc, 0) + 1
        else:
            leftovers.append(item)
        if len(selected) >= top_k:
            return selected[:top_k]
    # Backfill if capping left us short (e.g. only one relevant document exists).
    selected.extend(leftovers[: top_k - len(selected)])
    return selected[:top_k]


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[int]],
    *,
    rrf_k: int = RRF_K,
) -> dict[int, float]:
    fused_scores: dict[int, float] = {}
    for ranked_list in ranked_lists:
        for rank, item_id in enumerate(ranked_list, start=1):
            fused_scores[item_id] = fused_scores.get(item_id, 0.0) + (1.0 / (rrf_k + rank))
    return fused_scores


def _snippet(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= SNIPPET_LENGTH:
        return normalized
    return normalized[: SNIPPET_LENGTH - 3].rstrip() + "..."


def _cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _base_candidate_query() -> Select[Any]:
    return (
        select(
            Chunk.id.label("chunk_id"),
            Document.id.label("document_id"),
            Document.doc_code,
            Document.title,
            Chunk.page,
            Chunk.text,
            Chunk.embedding,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.embedding_status == "ready")
    )


def _keyword_candidates_postgres(session: Session, query: str, limit: int) -> list[dict[str, Any]]:
    ts_query = func.websearch_to_tsquery("english", query)
    score = func.ts_rank_cd(Chunk.tsv, ts_query)
    statement = (
        _base_candidate_query()
        .add_columns(score.label("keyword_score"))
        .where(Chunk.tsv.op("@@")(ts_query))
        .order_by(desc(score), Chunk.id)
        .limit(limit)
    )
    rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def _vector_candidates_postgres(
    session: Session,
    query_embedding: Sequence[float],
    limit: int,
) -> list[dict[str, Any]]:
    distance = Chunk.embedding.cosine_distance(list(query_embedding))
    similarity = (1 - distance).label("vector_score")
    statement = (
        _base_candidate_query()
        .add_columns(similarity)
        .where(Chunk.embedding.is_not(None))
        .order_by(distance, Chunk.id)
        .limit(limit)
    )
    rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def _keyword_candidates_sqlite(session: Session, query: str, limit: int) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().split() if term]
    rows = session.execute(_base_candidate_query()).mappings().all()
    scored: list[dict[str, Any]] = []
    for row in rows:
        text = str(row["text"]).lower()
        score = float(sum(text.count(term) for term in terms))
        if score <= 0:
            continue
        candidate = dict(row)
        candidate["keyword_score"] = score
        scored.append(candidate)
    scored.sort(key=lambda item: (item["keyword_score"], -item["chunk_id"]), reverse=True)
    return scored[:limit]


def _vector_candidates_sqlite(
    session: Session,
    query_embedding: Sequence[float],
    limit: int,
) -> list[dict[str, Any]]:
    rows = session.execute(_base_candidate_query()).mappings().all()
    scored: list[dict[str, Any]] = []
    for row in rows:
        score = _cosine_similarity(row["embedding"], query_embedding)
        if score <= 0:
            continue
        candidate = dict(row)
        candidate["vector_score"] = score
        scored.append(candidate)
    scored.sort(key=lambda item: (item["vector_score"], -item["chunk_id"]), reverse=True)
    return scored[:limit]


def _hybrid_candidates(
    session: Session,
    query: str,
    query_embedding: Sequence[float],
    *,
    candidate_limit: int,
) -> list[dict[str, Any]]:
    dialect = session.get_bind().dialect.name if session.get_bind() is not None else "sqlite"
    if dialect == "postgresql":
        keyword_candidates = _keyword_candidates_postgres(session, query, candidate_limit)
        vector_candidates = _vector_candidates_postgres(session, query_embedding, candidate_limit)
    else:
        keyword_candidates = _keyword_candidates_sqlite(session, query, candidate_limit)
        vector_candidates = _vector_candidates_sqlite(session, query_embedding, candidate_limit)

    candidate_map: dict[int, dict[str, Any]] = {}
    for candidate in keyword_candidates:
        candidate_map[candidate["chunk_id"]] = {
            **candidate,
            "keyword_score": float(candidate.get("keyword_score", 0.0)),
            "vector_score": 0.0,
        }
    for candidate in vector_candidates:
        existing = candidate_map.setdefault(
            candidate["chunk_id"],
            {
                **candidate,
                "keyword_score": 0.0,
            },
        )
        existing["vector_score"] = float(candidate.get("vector_score", 0.0))

    fused_scores = reciprocal_rank_fusion(
        [
            [candidate["chunk_id"] for candidate in keyword_candidates],
            [candidate["chunk_id"] for candidate in vector_candidates],
        ]
    )

    fused: list[dict[str, Any]] = []
    for chunk_id, fused_score in fused_scores.items():
        candidate = dict(candidate_map[chunk_id])
        candidate["score"] = fused_score
        candidate["snippet"] = _snippet(str(candidate["text"]))
        fused.append(candidate)

    fused.sort(key=lambda item: item["score"], reverse=True)
    return fused


def _keyword_only_candidates(
    session: Session,
    query: str,
    *,
    candidate_limit: int,
) -> list[dict[str, Any]]:
    dialect = session.get_bind().dialect.name if session.get_bind() is not None else "sqlite"
    if dialect == "postgresql":
        keyword_candidates = _keyword_candidates_postgres(session, query, candidate_limit)
    else:
        keyword_candidates = _keyword_candidates_sqlite(session, query, candidate_limit)

    ranked: list[dict[str, Any]] = []
    for candidate in keyword_candidates:
        item = dict(candidate)
        item["score"] = float(item.get("keyword_score", 0.0))
        item["snippet"] = _snippet(str(item["text"]))
        ranked.append(item)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def search(
    query: str,
    *,
    session: Session | None = None,
    embedder: Any | None = None,
    reranker: Any | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    top_k: int = DEFAULT_TOP_K,
    max_per_doc: int = DEFAULT_MAX_PER_DOC,
) -> list[dict[str, Any]]:
    candidate_limit = max(candidate_limit, top_k)
    try:
        query_embedding = (embedder or build_embeddings)([query])[0]
    except Exception:
        query_embedding = None

    def _run(active_session: Session) -> list[dict[str, Any]]:
        if query_embedding is None:
            fused_candidates = _keyword_only_candidates(
                active_session,
                query,
                candidate_limit=candidate_limit,
            )
        else:
            fused_candidates = _hybrid_candidates(
                active_session,
                query,
                query_embedding,
                candidate_limit=candidate_limit,
            )
        # Rerank the full fused pool (no early truncation), then diversify down to top_k so a
        # single large document can't fill every slot.
        reranked_all = rerank(
            query,
            fused_candidates[:candidate_limit],
            model=reranker,
            top_n=None,
        )
        reranked = diversify_by_document(reranked_all, top_k=top_k, max_per_doc=max_per_doc)
        return [
            {
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "doc_code": item["doc_code"],
                "title": item["title"],
                "page": item["page"],
                "snippet": item["snippet"],
                "score": float(item["score"]),
                "text": item["text"],
            }
            for item in reranked
        ]

    if session is not None:
        return _run(session)

    with session_scope("app") as active_session:
        return _run(active_session)
