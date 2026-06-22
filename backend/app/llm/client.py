from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from openai import OpenAI

from backend.app.cache import CacheClient, get_cache
from backend.app.config import get_settings

Message = dict[str, str]
InputGuardHook = Callable[[str], str]
OutputGuardHook = Callable[[dict[str, Any]], dict[str, Any]]


def get_openai_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key.get_secret_value())


def embed_texts(
    texts: Sequence[str],
    *,
    model: str | None = None,
    cache: CacheClient | None = None,
    ttl_seconds: int | None = None,
    input_guard_hook: InputGuardHook | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    resolved_model = model or settings.openai_embedding_model
    resolved_cache = cache or get_cache()
    resolved_ttl = ttl_seconds or settings.cache_ttl_embed_seconds

    # Guard against a single oversized chunk exceeding the model's 8192-token input limit
    # (~32k chars). Chunks target ~500 tokens, but OCR/table serialization can overflow.
    normalized_texts = [
        (input_guard_hook(text) if input_guard_hook else text)[:24_000] for text in texts
    ]
    cache_hits: list[list[float] | None] = [None] * len(normalized_texts)
    missing_texts: list[str] = []
    missing_indexes: list[int] = []

    for index, text in enumerate(normalized_texts):
        cache_key = resolved_cache.build_embedding_key(resolved_model, text)
        cached_vector = resolved_cache.get_json(cache_key)
        if isinstance(cached_vector, list):
            cache_hits[index] = [float(value) for value in cached_vector]
            continue
        missing_indexes.append(index)
        missing_texts.append(text)

    if missing_texts:
        client = get_openai_client()
        for batch_indexes, batch_texts in _embedding_batches(missing_indexes, missing_texts):
            response = client.embeddings.create(model=resolved_model, input=batch_texts)
            for index, item in zip(batch_indexes, response.data, strict=True):
                vector = list(item.embedding)
                cache_hits[index] = vector
                cache_key = resolved_cache.build_embedding_key(resolved_model, normalized_texts[index])
                resolved_cache.set_json(cache_key, vector, resolved_ttl)

    return [vector or [] for vector in cache_hits]


# OpenAI embeddings cap each request at 300k tokens / 2048 inputs. We batch well under both.
# We estimate tokens conservatively as chars/2.5 (dense technical/OCR text packs more tokens per
# char than typical prose) and target a 120k budget — large headroom below the 300k hard cap so a
# mis-estimate can't blow the request limit, while still sending efficient multi-doc batches.
_CHARS_PER_TOKEN = 2.5
_MAX_TOKENS_PER_REQUEST = 120_000
_MAX_INPUTS_PER_REQUEST = 512


def _embedding_batches(
    indexes: list[int], texts: list[str]
) -> list[tuple[list[int], list[str]]]:
    batches: list[tuple[list[int], list[str]]] = []
    cur_idx: list[int] = []
    cur_txt: list[str] = []
    cur_tokens = 0
    for index, text in zip(indexes, texts, strict=True):
        est_tokens = max(1, int(len(text) / _CHARS_PER_TOKEN))
        if cur_txt and (cur_tokens + est_tokens > _MAX_TOKENS_PER_REQUEST or len(cur_txt) >= _MAX_INPUTS_PER_REQUEST):
            batches.append((cur_idx, cur_txt))
            cur_idx, cur_txt, cur_tokens = [], [], 0
        cur_idx.append(index)
        cur_txt.append(text)
        cur_tokens += est_tokens
    if cur_txt:
        batches.append((cur_idx, cur_txt))
    return batches


def chat_json(
    messages: Sequence[Message],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    input_guard_hook: InputGuardHook | None = None,
    output_guard_hook: OutputGuardHook | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    resolved_messages: list[Message] = []
    for message in messages:
        content = message["content"]
        if input_guard_hook is not None and message.get("role") == "user":
            content = input_guard_hook(content)
        resolved_messages.append({"role": message["role"], "content": content})

    response = get_openai_client().chat.completions.create(
        model=model or settings.openai_chat_model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=list(resolved_messages),
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    if output_guard_hook is not None:
        return output_guard_hook(payload)
    return payload
