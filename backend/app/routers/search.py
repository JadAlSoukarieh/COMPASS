from time import perf_counter
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.cache import CacheClient, get_cache
from backend.app.config import RuntimeSettings, get_settings
from backend.app.db import get_app_session
from backend.app.llm.answer import build_grounded_answer
from backend.app.llm.client import embed_texts
from backend.app.retrieval.search import search
from backend.app.routers.auth import limiter
from backend.app.schemas.search import SearchAnswerResponse, SearchRequest, SearchRetrievalResponse
from backend.app.security.auth import AuthenticatedUser, get_current_user
from backend.app.security.guards import GuardrailViolation, input_guard
from backend.app.security.scope import resolve_scope

SearchRequest.model_rebuild()
SearchRetrievalResponse.model_rebuild()
SearchAnswerResponse.model_rebuild()

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="frontend/templates")


def _cache_from_request(request: Request) -> CacheClient:
    return getattr(request.app.state, "cache", None) or get_cache()


def _settings_from_request(request: Request) -> RuntimeSettings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _audit_search(
    *,
    current_user: AuthenticatedUser,
    query: str,
    mode: str,
    scope: str,
    results: list[dict[str, Any]],
    k_cited: int,
    latency_ms: int,
    cached: bool,
    session: Session,
) -> None:
    write_audit(
        action_type="doc_search",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "query": query,
            "mode": mode,
            "scope": scope,
            "retrieved_chunk_ids": [int(item["chunk_id"]) for item in results],
            "k_cited": k_cited,
            "latency_ms": latency_ms,
            "cached": cached,
        },
    )


def _audit_guardrail(
    *,
    current_user: AuthenticatedUser | None,
    query: str,
    reason: str,
    session: Session,
) -> None:
    write_audit(
        action_type="guardrail_block",
        role=current_user.role.value if current_user is not None else "anonymous",
        result_status="blocked",
        user_id=current_user.user_id if current_user is not None else None,
        session=session,
        detail={"query": query, "reason": reason},
    )


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={"page_title": "Compass Document Search"},
    )


@router.post(
    "/search",
    response_model=SearchRetrievalResponse | SearchAnswerResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
def document_search(
    request: Request,
    payload: SearchRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> SearchRetrievalResponse | SearchAnswerResponse:
    started_at = perf_counter()
    scope_context = resolve_scope(current_user, session)
    cache = _cache_from_request(request)
    settings = _settings_from_request(request)
    mode = "answer" if payload.analyze else "retrieval"

    try:
        query = input_guard(payload.query)
    except GuardrailViolation as exc:
        _audit_guardrail(current_user=current_user, query=payload.query, reason=exc.reason, session=session)
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc

    cache_key = cache.build_search_key(current_user.role.value, scope_context.scope, mode, query)
    cached_payload = cache.get_json(cache_key)
    if isinstance(cached_payload, dict):
        cached_results = list(cached_payload.get("sources") or cached_payload.get("results") or [])
        _audit_search(
            current_user=current_user,
            query=query,
            mode=mode,
            scope=scope_context.scope,
            results=cached_results,
            k_cited=len(cached_payload.get("citations") or []),
            latency_ms=int((perf_counter() - started_at) * 1000),
            cached=True,
            session=session,
        )
        if mode == "answer":
            return SearchAnswerResponse.model_validate(cached_payload)
        return SearchRetrievalResponse.model_validate(cached_payload)

    try:
        results = search(
            query,
            session=session,
            embedder=lambda texts: embed_texts(texts, cache=cache),
            reranker=getattr(request.app.state, "reranker", {}).get("instance"),
        )
        latency_ms = int((perf_counter() - started_at) * 1000)
        if mode == "retrieval":
            response_payload = {
                "mode": "retrieval",
                "results": [
                    {
                        "chunk_id": item["chunk_id"],
                        "document_id": item["document_id"],
                        "doc_code": item["doc_code"],
                        "title": item["title"],
                        "page": item["page"],
                        "snippet": item["snippet"],
                        "score": item["score"],
                    }
                    for item in results
                ],
                "status_line": {
                    "model": settings.openai_embedding_model,
                    "retrieval": "hybrid",
                    "reranked": True,
                    "n_retrieved": len(results),
                    "k_cited": 0,
                    "latency_ms": latency_ms,
                },
            }
            cache.set_json(cache_key, response_payload, settings.cache_ttl_search_seconds)
            _audit_search(
                current_user=current_user,
                query=query,
                mode=mode,
                scope=scope_context.scope,
                results=results,
                k_cited=0,
                latency_ms=latency_ms,
                cached=False,
                session=session,
            )
            return SearchRetrievalResponse.model_validate(response_payload)

        answer_payload = build_grounded_answer(query, results, model=settings.openai_chat_model)
        response_payload = {
            "mode": "answer",
            "answer_markdown": answer_payload["answer_markdown"],
            "citations": answer_payload["citations"],
            "sources": answer_payload["sources"],
            "refused": answer_payload["refused"],
            "status_line": {
                "model": settings.openai_chat_model,
                "retrieval": "hybrid",
                "reranked": True,
                "n_retrieved": len(results),
                "k_cited": len(answer_payload["citations"]),
                "latency_ms": latency_ms,
            },
        }
        cache.set_json(cache_key, response_payload, settings.cache_ttl_search_seconds)
        _audit_search(
            current_user=current_user,
            query=query,
            mode=mode,
            scope=scope_context.scope,
            results=results,
            k_cited=len(answer_payload["citations"]),
            latency_ms=latency_ms,
            cached=False,
            session=session,
        )
        return SearchAnswerResponse.model_validate(response_payload)
    except GuardrailViolation as exc:
        _audit_guardrail(current_user=current_user, query=query, reason=exc.reason, session=session)
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc
