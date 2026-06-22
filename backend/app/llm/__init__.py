"""LLM client and prompt orchestration package."""

from backend.app.llm.answer import build_grounded_answer
from backend.app.llm.analyze import analyze_dashboard_rows
from backend.app.llm.client import chat_json, embed_texts, get_openai_client
from backend.app.llm.intent import classify_intent, select_catalog
from backend.app.llm.query import phrase_catalog_answer
from backend.app.llm.support import answer_app_support

__all__ = [
    "answer_app_support",
    "analyze_dashboard_rows",
    "build_grounded_answer",
    "chat_json",
    "classify_intent",
    "embed_texts",
    "get_openai_client",
    "phrase_catalog_answer",
    "select_catalog",
]
