from __future__ import annotations

from typing import Any

from backend.app.llm.answer import build_grounded_answer


APP_SUPPORT_CORPUS: tuple[dict[str, Any], ...] = (
    {
        "chunk_id": 9001,
        "doc_code": "APP-LOGIN",
        "title": "sign in help",
        "page": 1,
        "text": (
            "To sign in, use the login page and enter your username and password. "
            "After sign-in, Compass keeps your bearer token in the browser session so the document search page and widget stay authenticated."
        ),
    },
    {
        "chunk_id": 9002,
        "doc_code": "APP-SEARCH",
        "title": "document search help",
        "page": 1,
        "text": (
            "Use Document Search when you want to find policies or how-to guides. "
            "Analyze with AI returns a grounded answer with citations, while turning analysis off returns ranked source chunks only."
        ),
    },
    {
        "chunk_id": 9003,
        "doc_code": "APP-LEAVE",
        "title": "leave request help",
        "page": 1,
        "text": (
            "To request leave in this app, open the assistant or document search and ask for the leave policy or process. "
            "Managers approve leave requests for their direct reports, and HR can review company-wide balances."
        ),
    },
    {
        "chunk_id": 9004,
        "doc_code": "APP-DOCS",
        "title": "manage documents help",
        "page": 1,
        "text": (
            "HR and superusers can upload policy and how-to documents from the Manage Documents page. "
            "Uploads are queued asynchronously, and the status badge moves from Pending to Processing to Ready or Failed."
        ),
    },
)


def answer_app_support(message: str) -> dict[str, Any]:
    scored = []
    query_terms = {term for term in message.lower().split() if len(term) > 2}
    for item in APP_SUPPORT_CORPUS:
        haystack = f"{item['title']} {item['text']}".lower()
        score = sum(haystack.count(term) for term in query_terms)
        if score > 0:
            scored.append(
                {
                    **item,
                    "score": float(score),
                    "snippet": item["text"][:240],
                }
            )
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    results = scored[:3]
    answer = build_grounded_answer(message, results)
    return {
        "answer_markdown": answer["answer_markdown"],
        "citations": answer["citations"],
        "sources": answer["sources"],
        "refused": answer["refused"],
    }
