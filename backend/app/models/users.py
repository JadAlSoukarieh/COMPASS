from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base

if TYPE_CHECKING:
    from backend.app.models.audit_log import AuditLog
    from backend.app.models.documents import Document
    from backend.app.models.employees import Employee


class UserRole(StrEnum):
    SUPERUSER = "superuser"
    HR = "hr"
    MGR = "mgr"
    EMP = "emp"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="userrole",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    employee: Mapped[Employee | None] = relationship("Employee", back_populates="user")
    audit_events: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="user")
    uploaded_documents: Mapped[list[Document]] = relationship("Document", back_populates="uploader")
