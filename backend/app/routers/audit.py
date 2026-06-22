from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_app_session
from backend.app.models import AuditLog, UserRole
from backend.app.schemas.audit import AuditLogItem
from backend.app.security.auth import AuthenticatedUser, require_roles

router = APIRouter(tags=["audit"])
templates = Jinja2Templates(directory="frontend/templates")


def _audit_response(row: AuditLog) -> AuditLogItem:
    return AuditLogItem(
        id=row.id,
        ts=row.ts,
        user_id=row.user_id,
        role=row.role,
        action_type=row.action_type,
        detail=row.detail,
        result_status=row.result_status,
    )


@router.get("/audit-log", response_class=HTMLResponse, include_in_schema=False)
def audit_log_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="audit_log.html",
        context={"page_title": "Audit Log · Compass"},
    )


@router.get("/audit", response_model=list[AuditLogItem], status_code=status.HTTP_200_OK)
def list_audit_logs(
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_app_session),
    user_id: int | None = Query(default=None),
    action_type: str | None = Query(default=None, max_length=64),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLogItem]:
    statement = select(AuditLog)
    if current_user.role != UserRole.SUPERUSER:
        statement = statement.where(AuditLog.role != UserRole.SUPERUSER.value)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)
    if action_type:
        statement = statement.where(AuditLog.action_type == action_type)
    if date_from is not None:
        statement = statement.where(AuditLog.ts >= datetime.combine(date_from, time.min))
    if date_to is not None:
        statement = statement.where(AuditLog.ts <= datetime.combine(date_to, time.max))

    rows = session.scalars(statement.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).offset(offset).limit(limit)).all()
    return [_audit_response(row) for row in rows]
