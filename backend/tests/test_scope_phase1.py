from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.models import Employee, User, UserRole
from backend.app.security.auth import AuthenticatedUser
from backend.app.security.scope import load_direct_report_ids, resolve_scope


def test_resolve_scope_for_all_roles() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[Employee.__table__, User.__table__])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as session:
        manager = Employee(
            full_name="Manager Demo",
            department="Operations",
            grade="G8",
            manager_id=None,
            hire_date=date(2024, 1, 1),
            contract_end_date=None,
            salary=7000,
            status="active",
        )
        employee = Employee(
            full_name="Employee Demo",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 2, 1),
            contract_end_date=None,
            salary=3200,
            status="active",
        )
        session.add_all([manager, employee])
        session.flush()

        hr_user = User(username="hr", password_hash="x", role=UserRole.HR, employee_id=None)
        superuser = User(username="superuser", password_hash="x", role=UserRole.SUPERUSER, employee_id=None)
        mgr_user = User(username="mgr", password_hash="x", role=UserRole.MGR, employee_id=manager.id)
        emp_user = User(username="emp", password_hash="x", role=UserRole.EMP, employee_id=employee.id)
        session.add_all([hr_user, superuser, mgr_user, emp_user])
        session.commit()

        mgr_reports = load_direct_report_ids(session, mgr_user)
        assert mgr_reports == [employee.id]

        company_scope = resolve_scope(
            AuthenticatedUser(
                user_id=1,
                username="superuser",
                role=UserRole.SUPERUSER,
                employee_id=None,
                is_active=True,
            ),
            session,
        )
        assert company_scope.scope == "company"

        hr_scope = resolve_scope(
            AuthenticatedUser(
                user_id=2,
                username="hr",
                role=UserRole.HR,
                employee_id=None,
                is_active=True,
            ),
            session,
        )
        assert hr_scope.scope == "company"

        mgr_scope = resolve_scope(
            AuthenticatedUser(
                user_id=3,
                username="mgr",
                role=UserRole.MGR,
                employee_id=manager.id,
                is_active=True,
                direct_report_ids=mgr_reports,
            ),
            session,
        )
        assert mgr_scope.scope == "team"
        assert mgr_scope.allowed_employee_ids == [employee.id]

        emp_scope = resolve_scope(
            AuthenticatedUser(
                user_id=4,
                username="emp",
                role=UserRole.EMP,
                employee_id=employee.id,
                is_active=True,
            ),
            session,
        )
        assert emp_scope.scope == "self"
        assert emp_scope.allowed_employee_ids == [employee.id]
