from __future__ import annotations

from data.evals import load_golden_dataset
from backend.app.catalog.registry import CATALOG_BY_ID
from backend.app.llm.support import APP_SUPPORT_CORPUS
from backend.app.models import UserRole
from backend.app.routers.dashboards import DASHBOARDS_BY_ID


ALLOWED_KINDS = {
    "search_retrieval",
    "search_answer",
    "widget_data_query",
    "widget_app_support",
    "widget_refuse",
    "dashboard_analysis",
    "safety_guardrail",
}


def test_golden_dataset_has_unique_case_ids() -> None:
    dataset = load_golden_dataset()
    case_ids = [case["id"] for case in dataset["cases"]]

    assert dataset["dataset_id"] == "compass-golden-v1"
    assert dataset["version"] == 1
    assert len(case_ids) == len(set(case_ids))
    assert len(case_ids) >= 12


def test_golden_dataset_references_known_roles_and_kinds() -> None:
    dataset = load_golden_dataset()
    valid_roles = {role.value for role in UserRole}

    for case in dataset["cases"]:
        assert case["kind"] in ALLOWED_KINDS
        assert case["role"] in valid_roles
        assert case["fixture_profile"] in dataset["fixture_profiles"]
        assert isinstance(case["request"], dict)
        assert isinstance(case["expected"], dict)


def test_golden_dataset_catalog_and_dashboard_references_exist() -> None:
    dataset = load_golden_dataset()

    for case in dataset["cases"]:
        expected = case["expected"]
        if "catalog_id" in expected:
            assert expected["catalog_id"] in CATALOG_BY_ID
        if case["kind"] == "dashboard_analysis":
            assert case["request"]["dashboard_id"] in DASHBOARDS_BY_ID


def test_golden_dataset_support_doc_codes_exist() -> None:
    dataset = load_golden_dataset()
    support_doc_codes = {item["doc_code"] for item in APP_SUPPORT_CORPUS}

    for case in dataset["cases"]:
        for doc_code in case["expected"].get("source_doc_codes", []):
            assert doc_code in support_doc_codes


def test_golden_dataset_search_cases_use_stable_doc_identifiers() -> None:
    dataset = load_golden_dataset()

    for case in dataset["cases"]:
        if case["kind"] == "search_retrieval":
            assert case["expected"]["primary_doc_code"]
            assert case["expected"]["relevant_doc_codes"]
        if case["kind"] == "search_answer":
            assert "must_refuse" in case["expected"]
            assert "cited_doc_codes" in case["expected"]
