from __future__ import annotations

import json
import re
from typing import Any

from backend.app.catalog import catalog_prompt_entries
from backend.app.llm.client import chat_json


INTENT_DATA_QUERY_PATTERNS = (
    re.compile(r"\bleave balance\b", re.IGNORECASE),
    re.compile(r"\bleave days\b", re.IGNORECASE),
    re.compile(r"\bdays remaining\b", re.IGNORECASE),
    re.compile(r"\bremaining leave\b", re.IGNORECASE),
    re.compile(r"\bheadcount\b", re.IGNORECASE),
    re.compile(r"\bsalary\b", re.IGNORECASE),
    re.compile(r"\bcontract", re.IGNORECASE),
    re.compile(r"\btenure\b", re.IGNORECASE),
    re.compile(r"\bapproval", re.IGNORECASE),
    re.compile(r"\bon leave\b", re.IGNORECASE),
    re.compile(r"\bwho is\b", re.IGNORECASE),
    re.compile(r"\binactive employees?\b", re.IGNORECASE),
    re.compile(r"\bshow employees?\b", re.IGNORECASE),
)

INTENT_SUPPORT_PATTERNS = (
    re.compile(r"\bhow do i\b", re.IGNORECASE),
    re.compile(r"\bin this app\b", re.IGNORECASE),
    re.compile(r"\brequest leave\b", re.IGNORECASE),
    re.compile(r"\bupload\b", re.IGNORECASE),
    re.compile(r"\bmanage documents\b", re.IGNORECASE),
    re.compile(r"\bdocument search\b", re.IGNORECASE),
    re.compile(r"\blog in\b", re.IGNORECASE),
)

INTENT_ANALYSIS_PATTERNS = (
    re.compile(r"\banaly[sz]e\b", re.IGNORECASE),
    re.compile(r"\btrend\b", re.IGNORECASE),
    re.compile(r"\binsight\b", re.IGNORECASE),
    re.compile(r"\bsummarize\b", re.IGNORECASE),
)

CATALOG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bleave balance\b|\bleave days\b|\bdays remaining\b|\bremaining leave\b", re.IGNORECASE), "EMP_LEAVE_BALANCE"),
    (re.compile(r"\bleave history\b|\bleave requests?\b", re.IGNORECASE), "EMP_LEAVE_HISTORY"),
    (re.compile(r"\bcontract end\b|\btenure\b|\bhire date\b", re.IGNORECASE), "EMP_TENURE"),
    (re.compile(r"\bupcoming leave\b|\bapproved leave\b", re.IGNORECASE), "EMP_UPCOMING_LEAVE"),
    (re.compile(r"\bwho is\b|\bemployee details\b|\bemployee info\b|\bshow employees?\b|\binactive employees?\b", re.IGNORECASE), "VISIBLE_EMPLOYEE_DIRECTORY"),
    (re.compile(r"\bheadcount\b.*\bgrade\b|\bgrade\b.*\bheadcount\b", re.IGNORECASE), "TEAM_HEADCOUNT_BY_GRADE"),
    (re.compile(r"\bon leave\b|\bwho.*leave\b", re.IGNORECASE), "TEAM_ON_LEAVE_PERIOD"),
    (re.compile(r"\bpending\b.*\bapproval\b|\bawaiting my approval\b", re.IGNORECASE), "TEAM_PENDING_MY_APPROVAL"),
    (re.compile(r"\bprobation\b|\bcontracts? expiring\b", re.IGNORECASE), "TEAM_PROBATION_ENDING"),
    (re.compile(r"\bburnout\b|\bno leave taken\b", re.IGNORECASE), "TEAM_BURNOUT_SIGNAL"),
    (re.compile(r"\bcarry.?over\b|\brisk losing\b", re.IGNORECASE), "TEAM_CARRYOVER_RISK"),
    (re.compile(r"\bheadcount\b.*\bdepartment\b|\bdepartment\b.*\bheadcount\b", re.IGNORECASE), "CO_HEADCOUNT_BY_DEPT"),
    (re.compile(r"\bsalary distribution\b|\baverage salary\b", re.IGNORECASE), "CO_SALARY_DISTRIBUTION"),
    (re.compile(r"\bheadcount\b.*\bstatus\b|\bstatus\b.*\bheadcount\b", re.IGNORECASE), "CO_HEADCOUNT_BY_STATUS"),
    (re.compile(r"\bnew hires?\b", re.IGNORECASE), "CO_NEW_HIRES"),
    (re.compile(r"\bleave utilization\b", re.IGNORECASE), "CO_LEAVE_UTILIZATION_BY_DEPT"),
    (re.compile(r"\boverdue approvals?\b", re.IGNORECASE), "SIG_OVERDUE_APPROVALS"),
    (re.compile(r"\bbottleneck\b", re.IGNORECASE), "SIG_APPROVAL_BOTTLENECK"),
)

EMPLOYEE_TARGETED_CATALOGS = {
    "EMP_LEAVE_BALANCE",
    "EMP_LEAVE_HISTORY",
    "EMP_TENURE",
    "EMP_UPCOMING_LEAVE",
}


def classify_intent(message: str, *, page: str | None = None, dashboard_id: str | None = None) -> str:
    if dashboard_id or page in {"dashboard", "dashboards", "dashboards-page"}:
        if any(pattern.search(message) for pattern in INTENT_ANALYSIS_PATTERNS):
            return "data_analysis"

    if any(pattern.search(message) for pattern in INTENT_SUPPORT_PATTERNS):
        return "app_support"
    if any(pattern.search(message) for pattern in INTENT_DATA_QUERY_PATTERNS):
        return "data_query"
    if any(pattern.search(message) for pattern in INTENT_ANALYSIS_PATTERNS):
        return "data_analysis"
    return _classify_intent_llm(message)


def _classify_intent_llm(message: str) -> str:
    payload = chat_json(
        [
            {
                "role": "system",
                "content": (
                    "Classify the user message for an internal HR assistant. "
                    "Return JSON only: {\"intent\": \"data_query\"|\"data_analysis\"|\"app_support\"|\"refuse\"}. "
                    "Use app_support for in-product how-to questions, data_query for factual employee/company data questions, "
                    "data_analysis for requests to analyze trends or dashboards, and refuse for unsafe or unrelated requests."
                ),
            },
            {"role": "user", "content": message},
        ],
        temperature=0.0,
    )
    intent = str(payload.get("intent") or "refuse")
    if intent not in {"data_query", "data_analysis", "app_support", "refuse"}:
        return "refuse"
    return intent


def select_catalog(message: str) -> dict[str, Any]:
    for pattern, catalog_id in CATALOG_RULES:
        if pattern.search(message):
            params = _rule_based_params(catalog_id, message)
            if _needs_llm_param_extraction(message, catalog_id=catalog_id, params=params):
                heuristic_params = _heuristic_catalog_params(catalog_id, message)
                if heuristic_params:
                    merged_params = dict(params)
                    merged_params.update(heuristic_params)
                    if not _needs_llm_param_extraction(message, catalog_id=catalog_id, params=merged_params):
                        return {"catalog_id": catalog_id, "params": merged_params}
                break
            return {"catalog_id": catalog_id, "params": params}

    payload = chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You choose a single catalog entry for an internal HR assistant. "
                    "Return JSON only with keys catalog_id and params. "
                    "Use only the provided catalog ids and param names. "
                    "Never include SQL, explanations, markdown, or extra keys."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "catalog": catalog_prompt_entries(),
                    }
                ),
            },
        ],
        temperature=0.0,
    )
    return {
        "catalog_id": payload.get("catalog_id"),
        "params": payload.get("params") or {},
    }


def _rule_based_params(catalog_id: str, message: str) -> dict[str, Any]:
    lowered = message.lower()
    params: dict[str, Any] = {}

    if "annual" in lowered:
        params["leave_type"] = "annual"
    elif "sick" in lowered:
        params["leave_type"] = "sick"
    elif "unpaid" in lowered:
        params["leave_type"] = "unpaid"

    if "approved" in lowered:
        params["status"] = "approved"
    elif "pending" in lowered:
        params["status"] = "pending"
    elif "rejected" in lowered:
        params["status"] = "rejected"
    elif "inactive" in lowered:
        params["status"] = "inactive"
    elif "on leave" in lowered:
        params["status"] = "on_leave"
    elif re.search(r"\bleft\b", lowered):
        params["status"] = "left"
    elif re.search(r"\bactive\b", lowered):
        params["status"] = "active"

    employee_id_match = re.search(r"\bemployee(?:\s+id)?\s+#?(\d+)\b", message, re.IGNORECASE)
    if employee_id_match:
        params["employee_id"] = int(employee_id_match.group(1))

    for pattern, key in (
        (re.compile(r"next (\d+) days?", re.IGNORECASE), "days"),
        (re.compile(r"last (\d+) days?", re.IGNORECASE), "days"),
        (re.compile(r"next (\d+) months?", re.IGNORECASE), "months"),
        (re.compile(r"last (\d+) months?", re.IGNORECASE), "months"),
    ):
        match = pattern.search(message)
        if match:
            params[key] = int(match.group(1))

    if catalog_id == "TEAM_ON_LEAVE_PERIOD" and "days" in params:
        params["days_ahead"] = params.pop("days")
    if catalog_id == "EMP_LEAVE_HISTORY":
        params.setdefault("limit", 5)
    if catalog_id == "VISIBLE_EMPLOYEE_DIRECTORY":
        params.setdefault("limit", 10)
    return params


def _needs_llm_param_extraction(message: str, *, catalog_id: str, params: dict[str, Any]) -> bool:
    if catalog_id not in EMPLOYEE_TARGETED_CATALOGS:
        return False
    if "employee_id" in params or "employee_name" in params:
        return False
    lowered = message.lower()
    if re.search(r"\b(my|me|mine)\b", lowered):
        return False
    return True


def _heuristic_catalog_params(catalog_id: str, message: str) -> dict[str, Any]:
    if catalog_id not in EMPLOYEE_TARGETED_CATALOGS:
        return {}

    patterns = (
        re.compile(r"\bdoes\s+(?P<target>.+?)\s+have\b", re.IGNORECASE),
        re.compile(r"\bfor\s+(?P<target>.+?)\s*$", re.IGNORECASE),
        re.compile(r"\b(?:who is|employee details for|employee info for)\s+(?P<target>.+?)\s*$", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(message)
        if not match:
            continue
        parsed = _parse_employee_target(match.group("target"))
        if parsed:
            return parsed
    return {}


def _parse_employee_target(target: str) -> dict[str, Any]:
    cleaned = " ".join(target.split()).strip(" ?,.")
    if not cleaned:
        return {}

    params: dict[str, Any] = {}

    grade_match = re.search(r"\b(G\d+)\b", cleaned, re.IGNORECASE)
    if grade_match:
        params["grade"] = grade_match.group(1).upper()
        cleaned = re.sub(r"\bG\d+\b", "", cleaned, flags=re.IGNORECASE).strip(" ,")

    department_match = re.search(r"\b(?:in|from)\s+([A-Za-z][A-Za-z ]+)$", cleaned)
    if department_match:
        params["department"] = " ".join(department_match.group(1).split())
        cleaned = cleaned[: department_match.start()].strip(" ,")

    cleaned = re.sub(r"\b(still|currently|now|today)\b$", "", cleaned, flags=re.IGNORECASE).strip(" ,")
    cleaned = re.sub(r"^\bemployee\b\s*", "", cleaned, flags=re.IGNORECASE).strip(" ,")
    if cleaned:
        params["employee_name"] = cleaned
    return params
