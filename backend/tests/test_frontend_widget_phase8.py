"""Phase 8 frontend widget shell in shared base template."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers.search import search_page


def _build_app() -> FastAPI:
    app = FastAPI()
    app.get("/search")(search_page)
    return app


client = TestClient(_build_app())


def test_search_page_includes_persistent_widget_shell() -> None:
    response = client.get("/search")
    assert response.status_code == 200
    body = response.text
    assert "Ask Compass" in body
    assert "compassWidget()" in body
    assert "/widget/message" in body
