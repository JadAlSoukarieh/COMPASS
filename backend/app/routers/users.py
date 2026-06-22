from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.db import get_app_session, get_writer_session
from backend.app.models import Employee, User
from backend.app.schemas.users import UserCreate, UserPatch, UserResponse
from backend.app.security.auth import AuthenticatedUser, hash_password, require_roles

router = APIRouter(tags=["users"])
templates = Jinja2Templates(directory="frontend/templates")


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        employee_id=user.employee_id,
        is_active=user.is_active,
    )


def _validate_employee(session: Session, employee_id: int | None) -> None:
    if employee_id is not None and session.get(Employee, employee_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Employee not found.")


def _username_exists(session: Session, username: str, *, exclude_user_id: int | None = None) -> bool:
    statement = select(User.id).where(User.username == username)
    if exclude_user_id is not None:
        statement = statement.where(User.id != exclude_user_id)
    return session.scalar(statement) is not None


@router.get("/manage-users", response_class=HTMLResponse, include_in_schema=False)
def manage_users_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="manage_users.html",
        context={"page_title": "Manage Users · Compass"},
    )


@router.get("/users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
def list_users(
    current_user: AuthenticatedUser = Depends(require_roles("superuser")),
    session: Session = Depends(get_app_session),
) -> list[UserResponse]:
    users = session.scalars(select(User).order_by(User.username, User.id)).all()
    return [_user_response(user) for user in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    current_user: AuthenticatedUser = Depends(require_roles("superuser")),
    session: Session = Depends(get_writer_session),
) -> UserResponse:
    username = payload.username.strip()
    if _username_exists(session, username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists.")
    _validate_employee(session, payload.employee_id)
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        employee_id=payload.employee_id,
        is_active=payload.is_active,
    )
    session.add(user)
    session.flush()
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "create_user",
            "target_user_id": user.id,
            "target_role": user.role.value,
            "is_active": user.is_active,
        },
    )
    return _user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
def patch_user(
    user_id: int,
    payload: UserPatch,
    current_user: AuthenticatedUser = Depends(require_roles("superuser")),
    session: Session = Depends(get_writer_session),
) -> UserResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "username" in updates:
        updates["username"] = str(updates["username"]).strip()
        if _username_exists(session, updates["username"], exclude_user_id=user.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists.")
    if "employee_id" in updates:
        _validate_employee(session, updates["employee_id"])

    password_updated = "password" in updates
    if password_updated:
        user.password_hash = hash_password(str(updates.pop("password")))

    for field, value in updates.items():
        setattr(user, field, value)

    session.flush()
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "patch_user",
            "target_user_id": user.id,
            "fields": sorted([*updates.keys(), *(["password"] if password_updated else [])]),
        },
    )
    return _user_response(user)
