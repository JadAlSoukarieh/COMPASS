from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.models.users import UserRole


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    role: UserRole
    employee_id: int | None
    is_active: bool

