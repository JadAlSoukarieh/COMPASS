"""Pydantic schemas package."""

from backend.app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from backend.app.schemas.audit import AuditLogItem
from backend.app.schemas.dashboards import DashboardAnalyzeResponse, DashboardDataResponse, DashboardSummary
from backend.app.schemas.documents import (
    DocumentListItem,
    DocumentPreviewChunkResponse,
    DocumentQueuedResponse,
    DocumentStatusResponse,
)
from backend.app.schemas.employees import EmployeeCreate, EmployeePatch, EmployeeResponse
from backend.app.schemas.search import SearchAnswerResponse, SearchRequest, SearchRetrievalResponse
from backend.app.schemas.users import UserCreate, UserPatch, UserResponse
from backend.app.schemas.widget import WidgetMessageRequest, WidgetMessageResponse

__all__ = [
    "AuditLogItem",
    "DashboardAnalyzeResponse",
    "DashboardDataResponse",
    "DashboardSummary",
    "EmployeeCreate",
    "EmployeePatch",
    "EmployeeResponse",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "DocumentListItem",
    "DocumentPreviewChunkResponse",
    "DocumentQueuedResponse",
    "DocumentStatusResponse",
    "SearchAnswerResponse",
    "SearchRequest",
    "SearchRetrievalResponse",
    "UserCreate",
    "UserPatch",
    "UserResponse",
    "WidgetMessageRequest",
    "WidgetMessageResponse",
]
