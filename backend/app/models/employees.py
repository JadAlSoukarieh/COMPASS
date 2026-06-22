from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base

if TYPE_CHECKING:
    from backend.app.models.leave_balances import LeaveBalance
    from backend.app.models.leave_requests import LeaveRequest
    from backend.app.models.users import User


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    grade: Mapped[str] = mapped_column(String(32), nullable=False)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    contract_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    manager: Mapped[Employee | None] = relationship(
        "Employee",
        remote_side="Employee.id",
        back_populates="reports",
    )
    reports: Mapped[list[Employee]] = relationship("Employee", back_populates="manager")
    user: Mapped[User | None] = relationship("User", back_populates="employee", uselist=False)
    leave_balances: Mapped[list[LeaveBalance]] = relationship(
        "LeaveBalance",
        back_populates="employee",
        cascade="all, delete-orphan",
    )
    leave_requests: Mapped[list[LeaveRequest]] = relationship(
        "LeaveRequest",
        foreign_keys="LeaveRequest.employee_id",
        back_populates="employee",
        cascade="all, delete-orphan",
    )
    approvals: Mapped[list[LeaveRequest]] = relationship(
        "LeaveRequest",
        foreign_keys="LeaveRequest.approver_id",
        back_populates="approver",
    )
