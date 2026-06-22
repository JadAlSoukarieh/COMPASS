from __future__ import annotations

import pytest

import backend.app.llm.answer as answer_module
import backend.app.llm.query as query_module
from backend.app.llm.answer import build_grounded_answer
from backend.app.llm.analyze import analyze_dashboard_rows
from backend.app.llm.intent import select_catalog
from backend.app.llm.query import phrase_catalog_answer


def test_select_catalog_heuristically_extracts_employee_name_and_department() -> None:
    selection = select_catalog("How many annual leave days does Dana Rahal in Operations have?")

    assert selection["catalog_id"] == "EMP_LEAVE_BALANCE"
    assert selection["params"]["employee_name"] == "Dana Rahal"
    assert selection["params"]["department"] == "Operations"
    assert selection["params"]["leave_type"] == "annual"


def test_select_catalog_heuristically_extracts_employee_name_with_trailing_still() -> None:
    selection = select_catalog("How many annual leave days does Jad Karam still have?")

    assert selection["catalog_id"] == "EMP_LEAVE_BALANCE"
    assert selection["params"]["employee_name"] == "Jad Karam"
    assert selection["params"]["leave_type"] == "annual"


def test_phrase_catalog_answer_falls_back_when_chat_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_module, "chat_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    answer = phrase_catalog_answer(
        "How many annual leave days does Dana Rahal have?",
        catalog_id="EMP_LEAVE_BALANCE",
        formatter_hint="Summarize remaining leave by type.",
        rows=[
            {
                "employee_id": 16,
                "full_name": "Dana Rahal",
                "leave_type": "annual",
                "year": 2026,
                "days_total": 24.0,
                "days_used": 10.0,
                "days_remaining": 14.0,
            }
        ],
    )

    assert answer == "Dana Rahal has 14 annual leave days remaining for 2026."


def test_analyze_dashboard_rows_falls_back_when_chat_errors() -> None:
    analysis = analyze_dashboard_rows(
        dashboard_id="company-leave-utilization",
        title="Leave utilization by department",
        scope="company",
        rows=[
            {"department": "Engineering", "days_total": 48.0, "days_used": 12.0},
            {"department": "HR", "days_total": 24.0, "days_used": 18.0},
        ],
        chat_client=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert "Dashboard `Leave utilization by department` returned 2 scoped row(s)." in analysis
    assert "department=Engineering, days_total=48.0, days_used=12.0" in analysis


def test_build_grounded_answer_returns_refusal_when_chat_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_module, "chat_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = build_grounded_answer(
        "How do I assign an open position to an employee?",
        [
            {
                "chunk_id": 45,
                "document_id": 1,
                "doc_code": "HOW-9F4A22",
                "title": "HCMS User Guide",
                "page": 1,
                "score": 0.9,
                "snippet": "Search for a position and assign it to an employee.",
                "text": "Search for a position and assign it to an employee.",
            }
        ],
    )

    assert payload["refused"] is False
    assert payload["citations"] == [{"chunk_id": 45, "doc_code": "HOW-9F4A22", "page": 1}]
    assert payload["sources"][0]["chunk_id"] == 45
    assert "Search for a position and assign it to an employee." in payload["answer_markdown"]
    assert "`HOW-9F4A22 p.1`" in payload["answer_markdown"]
