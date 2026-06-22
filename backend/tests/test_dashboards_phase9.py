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

from backend.app.cache import CacheClient
from backend.app.db import Base, get_app_session, get_writer_session
from backend.app.models import AuditLog, Employee, User, UserRole
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.routers.dashboards import router as dashboards_router
from backend.app.routers.employees import router as employees_router
from backend.app.routers.widget import router as widget_router
from backend.app.security import auth as auth_module


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.bust_calls: list[str] = []

    def build_dashboard_key(self, catalog_id: str, scope: str, params: dict[str, Any]) -> str:
        return CacheClient.build_dashboard_key(catalog_id, scope, params)

    def get_json(self, key: str) -> Any | None:
        return self.store.get(key)

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.store[key] = value

    def bust_namespace(self, namespace: str) -> int:
        self.bust_calls.append(namespace)
        keys = [key for key in self.store if key.startswith(f"{namespace}:")]
        for key in keys:
            del self.store[key]
        return len(keys)


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
        manager = Employee(
            full_name="Manager One",
            department="Operations",
            grade="G8",
            hire_date=date(2022, 1, 1),
            contract_end_date=None,
            salary=8000,
            status="active",
        )
        report_a = Employee(
            full_name="Report A",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 1, 1),
            contract_end_date=None,
            salary=3000,
            status="active",
        )
        report_b = Employee(
            full_name="Report B",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2024, 2, 1),
            contract_end_date=None,
            salary=3200,
            status="active",
        )
        other_manager = Employee(
            full_name="Other Manager",
            department="Engineering",
            grade="G8",
            hire_date=date(2020, 1, 1),
            contract_end_date=None,
            salary=9000,
            status="active",
        )
        non_report = Employee(
            full_name="Non Report",
            department="Operations",
            grade="G5",
            manager=other_manager,
            hire_date=date(2024, 3, 1),
            contract_end_date=None,
            salary=9000,
            status="active",
        )
        session.add_all([manager, report_a, report_b, other_manager, non_report])
        session.flush()
        session.add_all(
            [
                User(username="hr", password_hash=auth_module.hash_password("pw-hr"), role=UserRole.HR),
                User(
                    username="mgr",
                    password_hash=auth_module.hash_password("pw-mgr"),
                    role=UserRole.MGR,
                    employee_id=manager.id,
                ),
                User(
                    username="emp",
                    password_hash=auth_module.hash_password("pw-emp"),
                    role=UserRole.EMP,
                    employee_id=report_a.id,
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
    app.include_router(dashboards_router)
    app.include_router(employees_router)
    app.include_router(widget_router)
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


def test_mgr_dashboard_data_scoped_to_direct_reports_and_cached(client: TestClient) -> None:
    headers = _login(client, "mgr", "pw-mgr")

    first = client.get("/dashboards/team-headcount/data", headers=headers)
    second = client.get("/dashboards/team-headcount/data", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["scope"] == "team"
    assert first_payload["cached"] is False
    assert second_payload["cached"] is True
    assert first_payload["rows"] == [{"grade": "G5", "headcount": 2}]


def test_mgr_analysis_receives_only_backend_scoped_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_analyze(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "Scoped analysis."

    monkeypatch.setattr("backend.app.routers.dashboards.analyze_dashboard_rows", fake_analyze)
    headers = _login(client, "mgr", "pw-mgr")

    response = client.post("/dashboards/team-salary-summary/analyze", headers=headers)

    assert response.status_code == 200
    assert response.json()["analysis_markdown"] == "Scoped analysis."
    assert captured["scope"] == "team"
    assert captured["rows"] == [
        {
            "department": "Operations",
            "grade": "G5",
            "employee_count": 2,
            "avg_salary": 3100.0,
            "min_salary": 3000.0,
            "max_salary": 3200.0,
        }
    ]


def test_hr_company_dashboard_is_company_wide(client: TestClient) -> None:
    headers = _login(client, "hr", "pw-hr")

    response = client.get("/dashboards/company-headcount/data", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "company"
    assert payload["rows"] == [
        {"department": "Operations", "headcount": 4},
        {"department": "Engineering", "headcount": 1},
    ]


def test_employee_write_busts_dashboard_cache(
    client: TestClient,
    fake_cache: FakeCache,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    fake_cache.store["dash:cached"] = [{"stale": True}]

    response = client.patch("/employees/2", json={"status": "inactive"}, headers=headers)

    assert response.status_code == 200
    assert fake_cache.bust_calls == ["dash"]
    assert fake_cache.store == {}


def test_widget_dashboard_analysis_uses_dashboard_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_analysis")
    monkeypatch.setattr("backend.app.routers.widget.analyze_dashboard_rows", lambda **kwargs: "Widget scoped analysis.")
    headers = _login(client, "mgr", "pw-mgr")

    response = client.post(
        "/widget/message",
        json={
            "message": "analyze this dashboard",
            "context": {"page": "dashboards-page", "dashboard_id": "team-headcount"},
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "data_analysis"
    assert payload["catalog_id"] == "TEAM_HEADCOUNT_BY_GRADE"
    assert payload["scope_decision"] == "scoped"
    with session_factory() as session:
        audit = session.execute(
            select(AuditLog).where(AuditLog.action_type == "data_analysis").order_by(AuditLog.id.desc())
        ).scalars().first()
        assert audit is not None
        assert audit.detail["dashboard_id"] == "team-headcount"
