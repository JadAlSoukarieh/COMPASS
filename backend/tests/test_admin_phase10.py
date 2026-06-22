from __future__ import annotations

from collections.abc import Generator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_app_session, get_writer_session
from backend.app.models import AuditLog, Employee, User, UserRole
from backend.app.routers.audit import router as audit_router
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.routers.employees import router as employees_router
from backend.app.routers.users import router as users_router
from backend.app.security import auth as auth_module
from backend.app.security.auth import verify_password


class FakeCache:
    def __init__(self) -> None:
        self.bust_calls: list[str] = []

    def bust_namespace(self, namespace: str) -> int:
        self.bust_calls.append(namespace)
        return 3


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[Employee.__table__, User.__table__, AuditLog.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture()
def app(
    session_factory: sessionmaker[Session],
    fake_cache: FakeCache,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    with session_factory() as session:
        employee = Employee(
            full_name="Employee Demo",
            department="Operations",
            grade="G5",
            hire_date=date(2024, 1, 1),
            contract_end_date=None,
            salary=3000,
            status="active",
        )
        session.add(employee)
        session.flush()
        superuser = User(username="superuser", password_hash=auth_module.hash_password("pw-super"), role=UserRole.SUPERUSER)
        hr = User(username="hr", password_hash=auth_module.hash_password("pw-hr"), role=UserRole.HR)
        emp = User(
            username="emp",
            password_hash=auth_module.hash_password("pw-emp"),
            role=UserRole.EMP,
            employee_id=employee.id,
        )
        session.add_all([superuser, hr, emp])
        session.flush()
        session.add_all(
            [
                AuditLog(
                    user_id=superuser.id,
                    role=UserRole.SUPERUSER.value,
                    action_type="admin",
                    result_status="success",
                    detail={"operation": "seed_superuser"},
                ),
                AuditLog(
                    user_id=hr.id,
                    role=UserRole.HR.value,
                    action_type="data_query",
                    result_status="success",
                    detail={"catalog_id": "CO_HEADCOUNT_BY_DEPT"},
                ),
                AuditLog(
                    user_id=emp.id,
                    role=UserRole.EMP.value,
                    action_type="support",
                    result_status="success",
                    detail={"intent": "app_support"},
                ),
            ]
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(auth_module, "get_jwt_signing_key", lambda: "test-signing-key")
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.state.cache = fake_cache
    app.state.settings = SimpleNamespace(cache_ttl_dash_seconds=180)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router)
    app.include_router(employees_router)
    app.include_router(users_router)
    app.include_router(audit_router)
    app.dependency_overrides[get_app_session] = override_session
    app.dependency_overrides[get_writer_session] = override_session
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_employee_endpoints_are_role_gated(client: TestClient) -> None:
    emp_headers = _login(client, "emp", "pw-emp")
    hr_headers = _login(client, "hr", "pw-hr")

    assert client.get("/employees", headers=emp_headers).status_code == 403
    assert client.get("/employees", headers=hr_headers).status_code == 200


def test_create_and_patch_employee_audit_and_bust_cache(
    client: TestClient,
    fake_cache: FakeCache,
    session_factory: sessionmaker[Session],
) -> None:
    headers = _login(client, "hr", "pw-hr")
    create_response = client.post(
        "/employees",
        json={
            "full_name": "New Employee",
            "department": "Finance",
            "grade": "G4",
            "manager_id": None,
            "hire_date": "2026-01-10",
            "contract_end_date": None,
            "salary": "4200.00",
            "status": "active",
        },
        headers=headers,
    )

    assert create_response.status_code == 201
    employee_id = create_response.json()["id"]
    patch_response = client.patch(f"/employees/{employee_id}", json={"status": "inactive"}, headers=headers)
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "inactive"
    assert fake_cache.bust_calls == ["dash", "dash"]

    with session_factory() as session:
        audit = session.execute(
            select(AuditLog).where(AuditLog.action_type == "admin").order_by(AuditLog.id.desc())
        ).scalars().first()
        assert audit is not None
        assert audit.detail["operation"] == "patch_employee"
        assert audit.detail["employee_id"] == employee_id


def test_user_management_superuser_only_and_hashes_password(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    hr_headers = _login(client, "hr", "pw-hr")
    super_headers = _login(client, "superuser", "pw-super")

    assert client.get("/users", headers=hr_headers).status_code == 403
    create_response = client.post(
        "/users",
        json={
            "username": "newuser",
            "password": "new-password",
            "role": "emp",
            "employee_id": 1,
            "is_active": True,
        },
        headers=super_headers,
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload == {
        "id": payload["id"],
        "username": "newuser",
        "role": "emp",
        "employee_id": 1,
        "is_active": True,
    }
    assert "password_hash" not in payload
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == "newuser"))
        assert user is not None
        assert user.password_hash != "new-password"
        assert verify_password("new-password", user.password_hash)


def test_audit_filters_and_hr_scope(client: TestClient) -> None:
    hr_headers = _login(client, "hr", "pw-hr")
    super_headers = _login(client, "superuser", "pw-super")

    hr_response = client.get("/audit", headers=hr_headers)
    super_response = client.get("/audit?action_type=admin", headers=super_headers)

    assert hr_response.status_code == 200
    assert super_response.status_code == 200
    hr_rows = hr_response.json()
    super_rows = super_response.json()
    assert all(row["role"] != "superuser" for row in hr_rows)
    assert any(row["role"] == "superuser" for row in super_rows)
    assert all(row["action_type"] == "admin" for row in super_rows)
