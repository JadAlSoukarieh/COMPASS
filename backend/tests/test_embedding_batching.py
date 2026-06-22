"""Regression test: embed_texts must batch under OpenAI's per-request token/input limits.

A large document once produced a single embeddings request of ~314k tokens, exceeding the
300k-tokens-per-request cap (BadRequestError max_tokens_per_request). embed_texts now splits
missing texts into batches under both the token and input-count limits.
"""

from __future__ import annotations

from backend.app.llm.client import (
    _CHARS_PER_TOKEN,
    _MAX_INPUTS_PER_REQUEST,
    _MAX_TOKENS_PER_REQUEST,
    _embedding_batches,
)


def _est_tokens(text: str) -> int:
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def test_batches_respect_token_budget() -> None:
    # 1000 chunks of ~1000 tokens each = ~1M tokens -> must split into several batches.
    texts = ["x" * 4000] * 1000
    indexes = list(range(len(texts)))
    batches = _embedding_batches(indexes, texts)

    assert len(batches) > 1
    for batch_indexes, batch_texts in batches:
        assert len(batch_texts) <= _MAX_INPUTS_PER_REQUEST
        assert sum(_est_tokens(t) for t in batch_texts) <= _MAX_TOKENS_PER_REQUEST
        assert len(batch_indexes) == len(batch_texts)


def test_batches_cover_all_indexes_in_order() -> None:
    texts = ["small text"] * 5000  # trips the input-count limit, not the token limit
    indexes = list(range(len(texts)))
    batches = _embedding_batches(indexes, texts)

    flat = [i for batch_indexes, _ in batches for i in batch_indexes]
    assert flat == indexes
    for _, batch_texts in batches:
        assert len(batch_texts) <= _MAX_INPUTS_PER_REQUEST


def test_single_batch_when_small() -> None:
    batches = _embedding_batches([0, 1, 2], ["a", "b", "c"])
    assert len(batches) == 1
    assert batches[0] == ([0, 1, 2], ["a", "b", "c"])
