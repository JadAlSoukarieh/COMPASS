from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.db import get_app_session
from backend.app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from backend.app.security.auth import (
    AuthenticatedUser,
    authenticate_user,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def login(
    request: Request,
    payload_raw: dict = Body(...),
    session: Session = Depends(get_app_session),
) -> LoginResponse:
    try:
        payload = LoginRequest.model_validate(payload_raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    user = authenticate_user(session, payload.username, payload.password)
    if user is None:
        write_audit(
            action_type="login",
            role="anonymous",
            result_status="refused",
            detail={"username": payload.username},
            session=session,
        )
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    access_token = create_access_token(user=user)
    write_audit(
        action_type="login",
        role=user.role.value,
        result_status="success",
        user_id=user.id,
        detail={"username": user.username},
        session=session,
    )
    return LoginResponse(access_token=access_token, role=user.role, user_id=user.id)


@router.get("/me", response_model=MeResponse, status_code=status.HTTP_200_OK)
def me(current_user: AuthenticatedUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user_id=current_user.user_id,
        role=current_user.role,
        employee_id=current_user.employee_id,
        is_active=current_user.is_active,
    )
