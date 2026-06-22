"""Phase 7 frontend page route for Manage Documents."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers.documents import manage_documents_page


def _build_app() -> FastAPI:
    app = FastAPI()
    app.get("/manage-documents")(manage_documents_page)
    return app


client = TestClient(_build_app())


def test_manage_documents_page_renders_upload_and_status_ui() -> None:
    response = client.get("/manage-documents")
    assert response.status_code == 200
    body = response.text
    assert "manageDocumentsPage()" in body
    assert "Upload a document" in body
    assert "Corpus documents" in body
    assert "/documents" in body
    assert "Retry" in body
