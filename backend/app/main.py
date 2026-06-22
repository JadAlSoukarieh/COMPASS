from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from backend.app.cache import get_cache
from backend.app.config import get_bootstrap_settings, get_settings
from backend.app.db import database_healthcheck
from backend.app.retrieval import preload_reranker
from backend.app.routers.auth import limiter
from backend.app.routers.audit import router as audit_router
from backend.app.routers.auth import router as auth_router
from backend.app.routers.dashboards import router as dashboards_router
from backend.app.routers.documents import router as documents_router
from backend.app.routers.employees import router as employees_router
from backend.app.routers.search import router as search_router
from backend.app.routers.users import router as users_router
from backend.app.routers.widget import router as widget_router
from backend.app.schema import bootstrap_schema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.cache = get_cache()
    app.state.reranker = {
        "model_name": settings.reranker_model,
        "loaded": False,
        "instance": None,
        "error": None,
        "preload_started": False,
    }

    try:
        bootstrap_schema()
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("Database bootstrap deferred: %s", exc.__class__.__name__)

    preload_reranker(settings.reranker_model, target=app.state.reranker, async_load=True)

    yield


app = FastAPI(title="Compass API", version="0.1.0", lifespan=lifespan)
static_dir = Path("frontend/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
bootstrap_settings = get_bootstrap_settings()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[bootstrap_settings.app_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(dashboards_router)
app.include_router(documents_router)
app.include_router(employees_router)
app.include_router(search_router)
app.include_router(users_router)
app.include_router(widget_router)

templates = Jinja2Templates(directory="frontend/templates")


@app.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/search")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"page_title": "Sign in · Compass"},
    )


@app.get("/health")
async def healthcheck() -> JSONResponse:
    checks: dict[str, bool] = {
        "vault": True,
        "redis": False,
        "postgres": False,
    }

    try:
        checks["redis"] = get_cache().ping()
    except Exception as exc:  # pragma: no cover - health endpoint behavior
        logger.warning("Redis healthcheck failed: %s", exc.__class__.__name__)

    try:
        checks["postgres"] = database_healthcheck()
    except Exception as exc:  # pragma: no cover - health endpoint behavior
        logger.warning("Postgres healthcheck failed: %s", exc.__class__.__name__)

    healthy = all(checks.values())
    status_code = 200 if healthy else 503
    payload = {
        "status": "ok" if healthy else "degraded",
        "checks": checks,
        "reranker_loaded": bool(getattr(app.state, "reranker", {}).get("loaded", False)),
    }
    return JSONResponse(status_code=status_code, content=payload)


def run() -> None:
    uvicorn.run(
        "backend.app.main:app",
        host=bootstrap_settings.api_host,
        port=bootstrap_settings.api_port,
        reload=True,
    )
