from __future__ import annotations

from collections.abc import Generator
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_app_session
from backend.app.models import AuditLog, Employee, LeaveBalance, LeaveRequest, User, UserRole
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.routers.widget import router as widget_router
from backend.app.security import auth as auth_module


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Employee.__table__,
            User.__table__,
            LeaveBalance.__table__,
            LeaveRequest.__table__,
            AuditLog.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def app(session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> FastAPI:
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
        peer = Employee(
            full_name="Peer Demo",
            department="Operations",
            grade="G5",
            manager=manager,
            hire_date=date(2023, 7, 1),
            contract_end_date=None,
            salary=3200,
            status="active",
        )
        session.add_all([manager, employee, peer])
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
                    employee_id=employee.id,
                ),
            ]
        )
        session.add_all(
            [
                LeaveBalance(employee_id=employee.id, leave_type="annual", year=date.today().year, days_total=18, days_used=4),
                LeaveBalance(employee_id=peer.id, leave_type="annual", year=date.today().year, days_total=18, days_used=1),
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
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router)
    app.include_router(widget_router)
    app.dependency_overrides[get_app_session] = override_session
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}


def test_widget_rejects_unknown_catalog_id(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr("backend.app.routers.widget.select_catalog", lambda *args, **kwargs: {"catalog_id": "NOPE", "params": {}})

    response = client.post("/widget/message", json={"message": "show me some data", "context": {}}, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown_catalog_id"
    with session_factory() as session:
        audit = session.execute(
            select(AuditLog).where(AuditLog.action_type == "data_query").order_by(AuditLog.id.desc())
        ).scalars().first()
        assert audit is not None
        assert audit.action_type == "data_query"
        assert audit.result_status == "refused"
        assert audit.detail["reason"] == "unknown_catalog_id"


def test_widget_rejects_out_of_range_param_pre_db(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr(
        "backend.app.routers.widget.select_catalog",
        lambda *args, **kwargs: {"catalog_id": "CO_CONTRACTS_EXPIRING", "params": {"days": 9999}},
    )

    response = client.post("/widget/message", json={"message": "contracts expiring", "context": {}}, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "param_above_max:days"


def test_widget_refuses_emp_peer_scope_escalation(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "emp", "pw-emp")
    peer_id = 3
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr(
        "backend.app.routers.widget.select_catalog",
        lambda *args, **kwargs: {"catalog_id": "EMP_LEAVE_BALANCE", "params": {"employee_id": peer_id, "year": date.today().year}},
    )

    response = client.post("/widget/message", json={"message": "peer leave balance", "context": {}}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "data_query"
    assert payload["refused"] is True
    assert payload["scope_decision"] == "refused"
    with session_factory() as session:
        audit = session.execute(select(AuditLog).order_by(AuditLog.id.desc())).scalars().first()
        assert audit is not None
        assert audit.detail["reason"] == "employee_scope_refused"


def test_widget_scopes_emp_leave_balance_to_self(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "emp", "pw-emp")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr(
        "backend.app.routers.widget.select_catalog",
        lambda *args, **kwargs: {"catalog_id": "EMP_LEAVE_BALANCE", "params": {"year": date.today().year}},
    )
    monkeypatch.setattr(
        "backend.app.routers.widget.phrase_catalog_answer",
        lambda question, **kwargs: "You have 14 annual leave days remaining.",
    )

    response = client.post("/widget/message", json={"message": "my leave balance", "context": {}}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_id"] == "EMP_LEAVE_BALANCE"
    assert payload["used_params"]["employee_id"] == 2
    assert payload["scope_decision"] == "scoped"
    assert payload["refused"] is False
    with session_factory() as session:
        audit = session.execute(select(AuditLog).order_by(AuditLog.id.desc())).scalars().first()
        assert audit is not None
        assert audit.result_status == "success"
        assert audit.detail["scope_decision"] == "scoped"


def test_widget_resolves_employee_name_for_hr_query(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr(
        "backend.app.routers.widget.select_catalog",
        lambda *args, **kwargs: {"catalog_id": "EMP_LEAVE_BALANCE", "params": {"employee_name": "Peer Demo", "year": date.today().year}},
    )
    monkeypatch.setattr(
        "backend.app.routers.widget.phrase_catalog_answer",
        lambda question, **kwargs: "Peer Demo has 17 annual leave days remaining.",
    )

    response = client.post("/widget/message", json={"message": "how many leave days does Peer Demo have", "context": {}}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_id"] == "EMP_LEAVE_BALANCE"
    assert payload["used_params"]["employee_id"] == 3
    assert payload["refused"] is False


def test_widget_resolves_employee_name_with_department_hint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "data_query")
    monkeypatch.setattr(
        "backend.app.routers.widget.select_catalog",
        lambda *args, **kwargs: {
            "catalog_id": "EMP_LEAVE_BALANCE",
            "params": {
                "employee_name": "Peer Demo",
                "department": "Operations",
                "year": date.today().year,
            },
        },
    )
    monkeypatch.setattr(
        "backend.app.routers.widget.phrase_catalog_answer",
        lambda question, **kwargs: "Peer Demo has 17 annual leave days remaining.",
    )

    response = client.post(
        "/widget/message",
        json={"message": "how many leave days does Peer Demo in Operations have", "context": {}},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_id"] == "EMP_LEAVE_BALANCE"
    assert payload["used_params"]["employee_id"] == 3
    assert payload["used_params"]["department"] == "Operations"
    assert payload["refused"] is False


def test_widget_app_support_returns_grounded_sources(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "mgr", "pw-mgr")
    monkeypatch.setattr("backend.app.routers.widget.classify_intent", lambda *args, **kwargs: "app_support")
    monkeypatch.setattr(
        "backend.app.routers.widget.answer_app_support",
        lambda message: {
            "answer_markdown": "Use the Manage Documents page to upload files.",
            "citations": [],
            "sources": [
                {
                    "chunk_id": 9004,
                    "doc_code": "APP-DOCS",
                    "title": "manage documents help",
                    "page": 1,
                    "cited": True,
                    "text": "HR and superusers can upload policy and how-to documents from the Manage Documents page.",
                }
            ],
            "refused": False,
        },
    )

    response = client.post("/widget/message", json={"message": "how do I upload documents", "context": {}}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "app_support"
    assert payload["sources"][0]["doc_code"] == "APP-DOCS"
    assert payload["refused"] is False
