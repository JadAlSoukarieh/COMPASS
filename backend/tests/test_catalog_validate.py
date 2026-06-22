from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.catalog.validate import CatalogValidationError, validate_catalog_selection
from backend.app.db import Base
from backend.app.models import Employee, UserRole
from backend.app.security.auth import AuthenticatedUser


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[Employee.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_employees(session_factory: sessionmaker[Session]) -> dict[str, int]:
    with session_factory() as session:
        manager = Employee(
            full_name="Manager Demo",
            department="Operations",
            grade="G8",
            manager_id=None,
            hire_date=date(2022, 1, 1),
            contract_end_date=None,
            salary=7000,
            status="active",
        )
        unique = Employee(
            full_name="Peer Demo",
            department="QA",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 2, 1),
            contract_end_date=None,
            salary=3000,
            status="active",
        )
        duplicate_a = Employee(
            full_name="Lina Nassar",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 2, 1),
            contract_end_date=None,
            salary=3200,
            status="active",
        )
        duplicate_b = Employee(
            full_name="Lina Nassar",
            department="Support",
            grade="G7",
            manager_id=None,
            hire_date=date(2023, 3, 1),
            contract_end_date=None,
            salary=5000,
            status="active",
        )
        session.add_all([manager, unique, duplicate_a, duplicate_b])
        session.flush()
        session.commit()
        return {
            "manager": manager.id,
            "unique": unique.id,
            "duplicate_a": duplicate_a.id,
            "duplicate_b": duplicate_b.id,
        }


def test_validate_catalog_resolves_unique_employee_name(session_factory: sessionmaker[Session]) -> None:
    ids = _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        plan = validate_catalog_selection(
            "EMP_LEAVE_BALANCE",
            {"employee_name": "Peer Demo", "year": date.today().year},
            current_user=current_user,
            session=session,
        )

    assert plan.params["employee_id"] == ids["unique"]


def test_validate_catalog_rejects_ambiguous_employee_name(session_factory: sessionmaker[Session]) -> None:
    _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        with pytest.raises(CatalogValidationError, match="ambiguous_employee_name"):
            validate_catalog_selection(
                "EMP_LEAVE_BALANCE",
                {"employee_name": "Lina Nassar", "year": date.today().year},
                current_user=current_user,
                session=session,
            )


def test_validate_catalog_resolves_duplicate_employee_name_with_department(session_factory: sessionmaker[Session]) -> None:
    ids = _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        plan = validate_catalog_selection(
            "EMP_LEAVE_BALANCE",
            {
                "employee_name": "Lina Nassar",
                "department": "Support",
                "year": date.today().year,
            },
            current_user=current_user,
            session=session,
        )

    assert plan.params["employee_id"] == ids["duplicate_b"]


def test_validate_catalog_resolves_duplicate_employee_name_with_grade(session_factory: sessionmaker[Session]) -> None:
    ids = _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        plan = validate_catalog_selection(
            "EMP_LEAVE_BALANCE",
            {
                "employee_name": "Lina Nassar",
                "grade": "G5",
                "year": date.today().year,
            },
            current_user=current_user,
            session=session,
        )

    assert plan.params["employee_id"] == ids["duplicate_a"]


def test_validate_catalog_accepts_dynamic_department_from_db(session_factory: sessionmaker[Session]) -> None:
    _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        plan = validate_catalog_selection(
            "CO_SALARY_DISTRIBUTION",
            {"department": "QA"},
            current_user=current_user,
            session=session,
        )

    assert plan.params["department"] == "QA"


def test_validate_catalog_rejects_unknown_department(session_factory: sessionmaker[Session]) -> None:
    _seed_employees(session_factory)
    current_user = AuthenticatedUser(
        user_id=1,
        username="hr",
        role=UserRole.HR,
        employee_id=None,
        is_active=True,
    )

    with session_factory() as session:
        with pytest.raises(CatalogValidationError, match="unknown_department:department"):
            validate_catalog_selection(
                "CO_SALARY_DISTRIBUTION",
                {"department": "Legal"},
                current_user=current_user,
                session=session,
            )
