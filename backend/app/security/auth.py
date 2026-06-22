from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_app_session
from backend.app.models.users import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)
ACCESS_TOKEN_EXPIRE_MINUTES = 60


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: int
    username: str
    role: UserRole
    employee_id: int | None
    is_active: bool
    direct_report_ids: list[int] = field(default_factory=list)


def get_jwt_signing_key() -> str:
    return get_settings().jwt_signing_key.get_secret_value()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(
    *,
    user: User,
    expires_delta: timedelta | None = None,
    signing_key: str | None = None,
) -> str:
    now = datetime.now(UTC)
    expire_at = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user.id),
        "user_id": user.id,
        "role": user.role.value,
        "employee_id": user.employee_id,
        "exp": expire_at,
        "iat": now,
    }
    return jwt.encode(payload, signing_key or get_jwt_signing_key(), algorithm="HS256")


def decode_access_token(token: str, signing_key: str | None = None) -> dict[str, Any]:
    try:
        return jwt.decode(token, signing_key or get_jwt_signing_key(), algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_app_session),
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("user_id")
    role = payload.get("role")

    if user_id is None or role is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload.")

    user = session.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user.")

    if user.role.value != role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Role mismatch.")

    from backend.app.security.scope import load_direct_report_ids

    return AuthenticatedUser(
        user_id=user.id,
        username=user.username,
        role=user.role,
        employee_id=user.employee_id,
        is_active=user.is_active,
        direct_report_ids=load_direct_report_ids(session, user),
    )


def require_roles(*allowed_roles: UserRole | str):
    normalized_roles = {role.value if isinstance(role, UserRole) else role for role in allowed_roles}

    def dependency(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if current_user.role.value not in normalized_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role.")
        return current_user

    return dependency

