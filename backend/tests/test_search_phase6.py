from __future__ import annotations

from collections.abc import Generator
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_app_session
from backend.app.llm.answer import build_grounded_answer
from backend.app.models import AuditLog, Employee, User, UserRole
from backend.app.routers.auth import limiter, router as auth_router
from backend.app.routers.search import router as search_router
from backend.app.security import auth as auth_module


class FakeCache:
    def __init__(self) -> None:
        self.storage: dict[str, dict] = {}

    @staticmethod
    def build_search_key(role: str, scope: str, mode: str, query: str) -> str:
        from backend.app.cache import CacheClient

        return CacheClient.build_search_key(role, scope, mode, query)

    def get_json(self, key: str):
        return self.storage.get(key)

    def set_json(self, key: str, value, ttl_seconds: int) -> None:
        self.storage[key] = value


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
    app.state.cache = FakeCache()
    app.state.settings = SimpleNamespace(
        openai_embedding_model="text-embedding-3-small",
        openai_chat_model="gpt-4.1-mini",
        cache_ttl_search_seconds=300,
    )
    app.state.reranker = {"instance": None}
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router)
    app.include_router(search_router)
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


def test_build_grounded_answer_citations_map_to_retrieved_chunks() -> None:
    results = [
        {
            "chunk_id": 11,
            "doc_code": "POL-LEAVE",
            "title": "Leave Policy",
            "page": 1,
            "snippet": "New joiners receive 18 days of annual leave.",
            "score": 0.91,
            "text": "New joiners receive 18 days of annual leave in their first year.",
        }
    ]

    payload = build_grounded_answer(
        "How much annual leave do new joiners get?",
        results,
        chat_client=lambda *args, **kwargs: {
            "refused": False,
            "answer_markdown": "New joiners receive 18 annual leave days in their first year. [chunk:11]",
        },
    )

    assert payload["refused"] is False
    assert payload["citations"] == [{"chunk_id": 11, "doc_code": "POL-LEAVE", "page": 1}]
    assert {item["chunk_id"] for item in payload["sources"] if item["cited"]} == {11}


def test_search_route_hits_cache_for_identical_repeat(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "hr", "pw-hr")
    calls = {"count": 0}

    def fake_search(*args, **kwargs):
        calls["count"] += 1
        return [
            {
                "chunk_id": 1,
                "document_id": 1,
                "doc_code": "POL-LEAVE",
                "title": "Leave Policy",
                "page": 1,
                "snippet": "Leave snippet",
                "score": 0.88,
                "text": "Leave text",
            }
        ]

    monkeypatch.setattr("backend.app.routers.search.search", fake_search)

    first = client.post("/search", json={"query": "annual leave", "analyze": False}, headers=headers)
    second = client.post("/search", json={"query": "annual leave", "analyze": False}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["count"] == 1
    assert len(app.state.cache.storage) == 1


def test_search_cache_key_includes_role_and_scope(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hr_headers = _login(client, "hr", "pw-hr")
    emp_headers = _login(client, "emp", "pw-emp")

    def fake_search(*args, **kwargs):
        return [
            {
                "chunk_id": 1,
                "document_id": 1,
                "doc_code": "POL-LEAVE",
                "title": "Leave Policy",
                "page": 1,
                "snippet": "Leave snippet",
                "score": 0.88,
                "text": "Leave text",
            }
        ]

    monkeypatch.setattr("backend.app.routers.search.search", fake_search)

    hr_response = client.post("/search", json={"query": "annual leave", "analyze": False}, headers=hr_headers)
    emp_response = client.post("/search", json={"query": "annual leave", "analyze": False}, headers=emp_headers)

    assert hr_response.status_code == 200
    assert emp_response.status_code == 200
    keys = sorted(app.state.cache.storage)
    assert any(key.startswith("search:hr:company:retrieval:") for key in keys)
    assert any(key.startswith("search:emp:self:retrieval:") for key in keys)


def test_search_route_returns_refusal_for_weak_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _login(client, "mgr", "pw-mgr")

    monkeypatch.setattr(
        "backend.app.routers.search.search",
        lambda *args, **kwargs: [
            {
                "chunk_id": 7,
                "doc_code": "POL-TRAVEL",
                "title": "Travel Policy",
                "page": 1,
                "snippet": "Travel snippet",
                "score": 0.11,
                "text": "Travel claims must be submitted within 30 days.",
            }
        ],
    )
    monkeypatch.setattr(
        "backend.app.routers.search.build_grounded_answer",
        lambda *args, **kwargs: {
            "answer_markdown": "I can't answer that from the retrieved documents.",
            "citations": [],
            "sources": [
                {
                    "chunk_id": 7,
                    "doc_code": "POL-TRAVEL",
                    "title": "Travel Policy",
                    "page": 1,
                    "cited": False,
                    "text": "Travel claims must be submitted within 30 days.",
                }
            ],
            "refused": True,
        },
    )

    response = client.post("/search", json={"query": "what is the cafeteria menu", "analyze": True}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "answer"
    assert payload["refused"] is True
    assert payload["citations"] == []
