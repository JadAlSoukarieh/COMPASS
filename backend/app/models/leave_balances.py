from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base

if TYPE_CHECKING:
    from backend.app.models.employees import Employee


class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), primary_key=True)
    leave_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    days_total: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    days_used: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)

    employee: Mapped[Employee] = relationship("Employee", back_populates="leave_balances")

