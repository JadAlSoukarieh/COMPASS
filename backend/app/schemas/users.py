from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.models import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    role: UserRole
    employee_id: int | None = None
    is_active: bool = True


class UserPatch(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=1, max_length=128)
    role: UserRole | None = None
    employee_id: int | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    employee_id: int | None
    is_active: bool
