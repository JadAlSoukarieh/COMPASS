from __future__ import annotations

from functools import lru_cache
import logging
from threading import Thread
from typing import Any, Mapping, MutableMapping, Sequence

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


def _predict_scores(model: Any, query: str, candidates: Sequence[Mapping[str, Any]]) -> list[float]:
    pairs = [(query, str(candidate["text"])) for candidate in candidates]
    if hasattr(model, "predict"):
        scores = model.predict(pairs)
    elif callable(model):
        scores = model(pairs)
    else:  # pragma: no cover - defensive branch
        raise TypeError("Reranker model must define predict(...) or be callable.")
    return [float(score) for score in scores]


@lru_cache(maxsize=2)
def load_reranker(model_name: str | None = None) -> Any:
    from sentence_transformers import CrossEncoder

    resolved_model_name = model_name or get_settings().reranker_model
    return CrossEncoder(resolved_model_name)


def _set_preload_state(
    target: MutableMapping[str, Any] | None,
    *,
    loaded: bool,
    instance: Any | None = None,
    error: str | None = None,
) -> None:
    if target is None:
        return
    target["loaded"] = loaded
    target["instance"] = instance
    target["error"] = error


def preload_reranker(
    model_name: str | None = None,
    *,
    target: MutableMapping[str, Any] | None = None,
    async_load: bool = True,
) -> Thread | Any | None:
    resolved_model_name = model_name or get_settings().reranker_model

    def _load() -> Any | None:
        try:
            model = load_reranker(resolved_model_name)
        except Exception as exc:  # pragma: no cover - network/model cache failures
            logger.warning("Reranker preload deferred: %s", exc.__class__.__name__)
            _set_preload_state(target, loaded=False, instance=None, error=str(exc))
            return None

        _set_preload_state(target, loaded=True, instance=model, error=None)
        return model

    if not async_load:
        return _load()

    if target is not None and target.get("preload_started"):
        return None
    if target is not None:
        target["preload_started"] = True

    thread = Thread(target=_load, name="compass-reranker-preload", daemon=True)
    thread.start()
    return thread


def rerank(
    query: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    model: Any | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    active_model = model or load_reranker()
    scores = _predict_scores(active_model, query, candidates)

    ranked: list[dict[str, Any]] = []
    for candidate, score in zip(candidates, scores, strict=True):
        enriched = dict(candidate)
        enriched["base_score"] = float(candidate.get("score", 0.0))
        enriched["rerank_score"] = score
        enriched["score"] = score
        ranked.append(enriched)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    if top_n is not None:
        return ranked[:top_n]
    return ranked
