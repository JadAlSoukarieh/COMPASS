"""Phase 6 frontend page routes (index redirect, login page, search page).

These cover the server-rendered HTML shells added for the Alpine.js Document Search UI.
They assert the templates render and carry the expected Alpine hooks / theme assets, without
needing Vault, Postgres, or Redis (the page routes are static template responses).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from backend.app.routers.documents import manage_documents_page
from backend.app.routers.search import search_page

templates = Jinja2Templates(directory="frontend/templates")


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:  # mirrors backend.app.main.index
        return RedirectResponse(url="/search")

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request) -> HTMLResponse:  # mirrors backend.app.main.login_page
        return templates.TemplateResponse(
            request=request, name="login.html", context={"page_title": "Sign in · Compass"}
        )

    # Page-shell routes are static template responses (auth happens client-side via the JWT helper).
    app.get("/search", response_class=HTMLResponse)(search_page)
    app.get("/manage-documents", response_class=HTMLResponse)(manage_documents_page)
    return app


client = TestClient(_build_app())


def test_index_redirects_to_search() -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/search"


def test_login_page_renders_alpine_form() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    body = response.text
    assert "loginForm()" in body          # Alpine component
    assert "/auth/login" in body          # posts to the auth API
    assert "alpinejs" in body             # Alpine is loaded via base.html


def test_search_page_renders_analyze_toggle_and_status_line() -> None:
    response = client.get("/search")
    assert response.status_code == 200
    body = response.text
    assert "searchPage()" in body                       # Alpine component
    assert "Analyze with AI" in body                     # the toggle (brief §8)
    assert "Find the right document" in body             # required subtitle (brief §8)
    assert "statusText()" in body                        # status line wiring
    assert 'x-model="analyze"' in body                   # toggle bound to state
    assert "/static/css/compass.css" in body             # compass theme applied


def test_app_shell_has_sidebar_nav() -> None:
    body = client.get("/search").text
    assert 'class="sidebar"' in body                     # navy sidebar rail
    assert "nav-item" in body                            # nav items
    assert "Compass.canManageDocuments()" in body        # role-gated Manage Documents link
    assert "active === 'search'" in body                 # active-nav highlight


def test_manage_documents_page_renders_table_and_badges() -> None:
    response = client.get("/manage-documents")
    assert response.status_code == 200
    body = response.text
    assert "manageDocumentsPage()" in body               # Alpine component
    assert 'table class="data"' in body                  # table layout (agreed design)
    assert 'class="badge"' in body and 'class="dot"' in body  # dot + pill status badges
    assert "Re-embed" in body and "Retry" in body         # per-row retry/re-embed
    assert "pollStatuses" in body                         # live status polling
