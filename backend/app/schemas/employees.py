from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    department: str = Field(min_length=1, max_length=128)
    grade: str = Field(min_length=1, max_length=32)
    manager_id: int | None = None
    hire_date: date
    contract_end_date: date | None = None
    salary: Decimal = Field(gt=0)
    status: str = Field(default="active", min_length=1, max_length=32)


class EmployeePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, min_length=1, max_length=128)
    grade: str | None = Field(default=None, min_length=1, max_length=32)
    manager_id: int | None = None
    hire_date: date | None = None
    contract_end_date: date | None = None
    salary: Decimal | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, min_length=1, max_length=32)


class EmployeeResponse(BaseModel):
    id: int
    full_name: str
    department: str
    grade: str
    manager_id: int | None
    hire_date: date
    contract_end_date: date | None
    salary: float
    status: str
