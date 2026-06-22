from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.employees import Employee
from backend.app.models.users import User, UserRole
from backend.app.security.auth import AuthenticatedUser


@dataclass(slots=True)
class ScopeContext:
    scope: str
    employee_id: int | None
    allowed_employee_ids: list[int] = field(default_factory=list)


def load_direct_report_ids(session: Session, user: User | AuthenticatedUser) -> list[int]:
    if user.role != UserRole.MGR or user.employee_id is None:
        return []

    rows = session.scalars(select(Employee.id).where(Employee.manager_id == user.employee_id)).all()
    return list(rows)


def resolve_scope(current_user: AuthenticatedUser, session: Session) -> ScopeContext:
    if current_user.role in {UserRole.SUPERUSER, UserRole.HR}:
        return ScopeContext(scope="company", employee_id=current_user.employee_id)
    if current_user.role == UserRole.MGR:
        direct_reports = current_user.direct_report_ids or load_direct_report_ids(session, current_user)
        return ScopeContext(
            scope="team",
            employee_id=current_user.employee_id,
            allowed_employee_ids=direct_reports,
        )
    return ScopeContext(
        scope="self",
        employee_id=current_user.employee_id,
        allowed_employee_ids=[current_user.employee_id] if current_user.employee_id is not None else [],
    )

