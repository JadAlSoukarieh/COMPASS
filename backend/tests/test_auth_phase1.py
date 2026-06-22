from __future__ import annotations

from collections.abc import Generator
from datetime import date

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_app_session
from backend.app.models import AuditLog, Employee, User, UserRole
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.security import auth as auth_module
from backend.app.security.auth import AuthenticatedUser, decode_access_token, hash_password, require_roles


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
def app(session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    with session_factory() as session:
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
            salary=3000,
            status="active",
        )
        session.add_all([manager, employee])
        session.flush()
        session.add_all(
            [
                User(username="superuser", password_hash=hash_password("pw-super"), role=UserRole.SUPERUSER),
                User(username="hr", password_hash=hash_password("pw-hr"), role=UserRole.HR),
                User(
                    username="mgr",
                    password_hash=hash_password("pw-mgr"),
                    role=UserRole.MGR,
                    employee_id=manager.id,
                ),
                User(
                    username="emp",
                    password_hash=hash_password("pw-emp"),
                    role=UserRole.EMP,
                    employee_id=employee.id,
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

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router)

    @app.get("/protected/search")
    def protected_search(current_user: AuthenticatedUser = Depends(require_roles("emp", "mgr", "hr", "superuser"))):
        return {"role": current_user.role.value}

    @app.get("/protected/admin")
    def protected_admin(current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser"))):
        return {"role": current_user.role.value}

    @app.get("/protected/users")
    def protected_users(current_user: AuthenticatedUser = Depends(require_roles("superuser"))):
        return {"role": current_user.role.value}

    app.dependency_overrides[get_app_session] = override_session
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    ("username", "password", "role"),
    [
        ("superuser", "pw-super", "superuser"),
        ("hr", "pw-hr", "hr"),
        ("mgr", "pw-mgr", "mgr"),
        ("emp", "pw-emp", "emp"),
    ],
)
def test_login_issues_token_for_each_role(client: TestClient, username: str, password: str, role: str) -> None:
    response = client.post("/auth/login", json={"username": username, "password": password})

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == role
    assert payload["token_type"] == "bearer"

    decoded = decode_access_token(payload["access_token"], signing_key="test-signing-key")
    assert decoded["role"] == role
    assert int(decoded["user_id"]) == payload["user_id"]


def test_auth_me_returns_user_shape(client: TestClient) -> None:
    login_response = client.post("/auth/login", json={"username": "mgr", "password": "pw-mgr"})
    token = login_response.json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": 3,
        "role": "mgr",
        "employee_id": 1,
        "is_active": True,
    }


@pytest.mark.parametrize(
    ("username", "password", "expected"),
    [
        ("superuser", "pw-super", {"/protected/search": 200, "/protected/admin": 200, "/protected/users": 200}),
        ("hr", "pw-hr", {"/protected/search": 200, "/protected/admin": 200, "/protected/users": 403}),
        ("mgr", "pw-mgr", {"/protected/search": 200, "/protected/admin": 403, "/protected/users": 403}),
        ("emp", "pw-emp", {"/protected/search": 200, "/protected/admin": 403, "/protected/users": 403}),
    ],
)
def test_role_guard_matrix(
    client: TestClient,
    username: str,
    password: str,
    expected: dict[str, int],
) -> None:
    login_response = client.post("/auth/login", json={"username": username, "password": password})
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    for route, status_code in expected.items():
        response = client.get(route, headers=headers)
        assert response.status_code == status_code
