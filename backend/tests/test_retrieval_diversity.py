"""Retrieval diversity: a single large document must not fill the entire top-k."""

from __future__ import annotations

from backend.app.retrieval.search import diversify_by_document


def _item(chunk_id: int, doc_code: str, score: float) -> dict:
    return {"chunk_id": chunk_id, "doc_code": doc_code, "score": score}


def test_caps_chunks_per_document_when_enough_diversity() -> None:
    # Enough distinct docs exist to fill top_k under the cap → BIG is limited to max_per_doc.
    ranked = [
        _item(1, "BIG", 9.0),
        _item(2, "BIG", 8.5),
        _item(3, "BIG", 8.0),
        _item(4, "OTHER", 7.5),
        _item(5, "THIRD", 7.0),
        _item(6, "FOURTH", 6.5),
    ]
    selected = diversify_by_document(ranked, top_k=5, max_per_doc=2)
    codes = [s["doc_code"] for s in selected]
    assert codes.count("BIG") == 2          # capped (not 3)
    assert len(selected) == 5
    assert len(set(codes)) == 4             # BIG, OTHER, THIRD, FOURTH


def test_backfill_can_exceed_cap_only_when_needed() -> None:
    # Only 3 distinct docs but top_k=5 → backfill fills the last slot from the dominant doc.
    ranked = [
        _item(1, "BIG", 9.0), _item(2, "BIG", 8.5), _item(3, "BIG", 8.0),
        _item(4, "OTHER", 7.0), _item(5, "THIRD", 6.5),
    ]
    selected = diversify_by_document(ranked, top_k=5, max_per_doc=2)
    codes = [s["doc_code"] for s in selected]
    assert len(selected) == 5
    assert codes.count("BIG") == 3          # backfilled the 5th slot
    assert {"OTHER", "THIRD"} <= set(codes)


def test_backfills_when_only_one_document_matches() -> None:
    # If only one doc is relevant, we still return top_k from it (no artificial starvation).
    ranked = [_item(i, "ONLY", 9.0 - i) for i in range(5)]
    selected = diversify_by_document(ranked, top_k=5, max_per_doc=2)
    assert len(selected) == 5
    assert all(s["doc_code"] == "ONLY" for s in selected)


def test_preserves_score_order_within_selection() -> None:
    ranked = [_item(1, "A", 9.0), _item(2, "B", 8.0), _item(3, "A", 7.0), _item(4, "C", 6.0)]
    selected = diversify_by_document(ranked, top_k=3, max_per_doc=1)
    # max_per_doc=1 → one chunk each from A, B, C in score order.
    assert [s["doc_code"] for s in selected] == ["A", "B", "C"]
