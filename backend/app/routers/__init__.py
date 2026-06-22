"""API router package."""

from backend.app.routers.audit import router as audit_router
from backend.app.routers.auth import router as auth_router
from backend.app.routers.dashboards import router as dashboards_router
from backend.app.routers.documents import router as documents_router
from backend.app.routers.employees import router as employees_router
from backend.app.routers.search import router as search_router
from backend.app.routers.users import router as users_router
from backend.app.routers.widget import router as widget_router

__all__ = [
    "audit_router",
    "auth_router",
    "dashboards_router",
    "documents_router",
    "employees_router",
    "search_router",
    "users_router",
    "widget_router",
]
