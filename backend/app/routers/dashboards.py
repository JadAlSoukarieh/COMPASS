from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.cache import CacheClient, get_cache
from backend.app.catalog import execute_catalog_plan, validate_catalog_selection
from backend.app.config import RuntimeSettings, get_settings
from backend.app.db import get_app_session
from backend.app.llm.analyze import analyze_dashboard_rows
from backend.app.models import UserRole
from backend.app.schemas.dashboards import DashboardAnalyzeResponse, DashboardDataResponse, DashboardSummary
from backend.app.security.auth import AuthenticatedUser, get_current_user
from backend.app.security.guards import GuardrailViolation

router = APIRouter(tags=["dashboards"])
templates = Jinja2Templates(directory="frontend/templates")


@dataclass(frozen=True, slots=True)
class DashboardDefinition:
    id: str
    title: str
    description: str
    catalog_id: str
    required_roles: tuple[str, ...]
    scope: str
    default_params: dict[str, Any] = field(default_factory=dict)
    # Chart hints for the frontend (Chart.js). chart_type one of: bar, pie, line, grouped-bar.
    # chart_x = category/label field; chart_y = numeric series field(s) to plot.
    chart_type: str | None = None
    chart_x: str | None = None
    chart_y: tuple[str, ...] = ()


CURRENT_YEAR = date.today().year

DASHBOARDS: tuple[DashboardDefinition, ...] = (
    DashboardDefinition(
        id="emp-leave-summary",
        title="My leave summary",
        description="Leave balances for the signed-in employee.",
        catalog_id="EMP_LEAVE_BALANCE",
        required_roles=("emp", "mgr", "hr", "superuser"),
        scope="self",
        chart_type="bar",
        chart_x="leave_type",
        chart_y=("days_remaining",),
    ),
    DashboardDefinition(
        id="team-headcount",
        title="Team headcount by grade",
        description="Direct-report headcount grouped by grade.",
        catalog_id="TEAM_HEADCOUNT_BY_GRADE",
        required_roles=("mgr", "hr", "superuser"),
        scope="team",
        chart_type="bar",
        chart_x="grade",
        chart_y=("headcount",),
    ),
    DashboardDefinition(
        id="team-salary-summary",
        title="Team salary summary",
        description="Visible team salary summary by department and grade.",
        catalog_id="TEAM_SALARY_SUMMARY",
        required_roles=("mgr", "hr", "superuser"),
        scope="team",
        chart_type="bar",
        chart_x="grade",
        chart_y=("avg_salary",),
    ),
    DashboardDefinition(
        id="team-leave-risk",
        title="Team leave carryover risk",
        description="Visible employees with high unused annual leave.",
        catalog_id="TEAM_CARRYOVER_RISK",
        required_roles=("mgr", "hr", "superuser"),
        scope="team",
        chart_type="bar",
        chart_x="full_name",
        chart_y=("days_remaining",),
    ),
    DashboardDefinition(
        id="company-headcount",
        title="Company headcount by department",
        description="Company-wide headcount grouped by department.",
        catalog_id="CO_HEADCOUNT_BY_DEPT",
        required_roles=("hr", "superuser"),
        scope="company",
        chart_type="pie",
        chart_x="department",
        chart_y=("headcount",),
    ),
    DashboardDefinition(
        id="company-salary-distribution",
        title="Company salary distribution",
        description="Company-wide average salary by department and grade.",
        catalog_id="CO_SALARY_DISTRIBUTION",
        required_roles=("hr", "superuser"),
        scope="company",
        chart_type="bar",
        chart_x="grade",
        chart_y=("avg_salary",),
    ),
    DashboardDefinition(
        id="company-contracts-expiring",
        title="Contracts expiring (90 days)",
        description="Company contracts expiring in the next 90 days.",
        catalog_id="CO_CONTRACTS_EXPIRING",
        required_roles=("hr", "superuser"),
        scope="company",
        default_params={"days": 90},
    ),
    # ---- New chart-first dashboards from previously-unused catalog queries ----
    DashboardDefinition(
        id="company-avg-tenure",
        title="Average tenure by department",
        description="Mean tenure (days) per department — retention signal.",
        catalog_id="CO_AVG_TENURE_BY_DEPT",
        required_roles=("hr", "superuser"),
        scope="company",
        chart_type="bar",
        chart_x="department",
        chart_y=("avg_tenure_days",),
    ),
    DashboardDefinition(
        id="company-leave-utilization",
        title="Leave utilization by department",
        description="Annual leave days allotted vs. used per department.",
        catalog_id="CO_LEAVE_UTILIZATION_BY_DEPT",
        required_roles=("hr", "superuser"),
        scope="company",
        default_params={"year": CURRENT_YEAR},
        chart_type="grouped-bar",
        chart_x="department",
        chart_y=("days_total", "days_used"),
    ),
    DashboardDefinition(
        id="company-new-hires",
        title="New hires (last 180 days)",
        description="Recent hires across the company.",
        catalog_id="CO_NEW_HIRES",
        required_roles=("hr", "superuser"),
        scope="company",
        default_params={"days": 180},
        chart_type="bar",
        chart_x="hire_date",
        chart_y=("employee_id",),
    ),
    DashboardDefinition(
        id="company-approval-bottleneck",
        title="Approval bottlenecks",
        description="Approvers with the largest pending-approval workload.",
        catalog_id="SIG_APPROVAL_BOTTLENECK",
        required_roles=("hr", "superuser"),
        scope="company",
        chart_type="bar",
        chart_x="approver_name",
        chart_y=("pending_count",),
    ),
    DashboardDefinition(
        id="company-overdue-approvals",
        title="Overdue approvals (>7 days)",
        description="Pending leave approvals older than 7 days.",
        catalog_id="SIG_OVERDUE_APPROVALS",
        required_roles=("hr", "superuser"),
        scope="company",
        default_params={"days": 7},
    ),
    DashboardDefinition(
        id="team-on-leave",
        title="Team on leave (next 30 days)",
        description="Direct reports on leave in the coming month.",
        catalog_id="TEAM_ON_LEAVE_PERIOD",
        required_roles=("mgr", "hr", "superuser"),
        scope="team",
        default_params={"days_ahead": 30},
    ),
)
DASHBOARDS_BY_ID = {dashboard.id: dashboard for dashboard in DASHBOARDS}


def _cache_from_request(request: Request) -> CacheClient:
    return getattr(request.app.state, "cache", None) or get_cache()


def _settings_from_request(request: Request) -> RuntimeSettings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _visible_dashboards(current_user: AuthenticatedUser) -> list[DashboardDefinition]:
    role = current_user.role.value
    dashboards = [dashboard for dashboard in DASHBOARDS if role in dashboard.required_roles]
    if current_user.role == UserRole.EMP:
        return [dashboard for dashboard in dashboards if dashboard.scope == "self"]
    if current_user.role == UserRole.MGR:
        return [dashboard for dashboard in dashboards if dashboard.scope == "team"]
    return [dashboard for dashboard in dashboards if dashboard.scope == "company"]


def _get_visible_dashboard(dashboard_id: str, current_user: AuthenticatedUser) -> DashboardDefinition:
    dashboard = DASHBOARDS_BY_ID.get(dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found.")
    if dashboard not in _visible_dashboards(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dashboard not permitted.")
    return dashboard


def _cache_scope_key(current_user: AuthenticatedUser, scope: str) -> str:
    if scope == "self":
        return f"self:{current_user.employee_id or current_user.user_id}"
    if scope == "team":
        return f"team:{current_user.employee_id or current_user.user_id}"
    return "company"


def _summary(dashboard: DashboardDefinition) -> DashboardSummary:
    return DashboardSummary(
        id=dashboard.id,
        title=dashboard.title,
        description=dashboard.description,
        catalog_id=dashboard.catalog_id,
        scope=dashboard.scope,  # type: ignore[arg-type]
        default_params=dashboard.default_params,
        chart_type=dashboard.chart_type,
        chart_x=dashboard.chart_x,
        chart_y=list(dashboard.chart_y),
    )


def _dashboard_rows(
    *,
    request: Request,
    dashboard: DashboardDefinition,
    current_user: AuthenticatedUser,
    session: Session,
) -> tuple[list[dict[str, Any]], str, bool]:
    plan = validate_catalog_selection(
        dashboard.catalog_id,
        dashboard.default_params,
        current_user=current_user,
        session=session,
    )
    response_scope = plan.scope_context.scope
    cache_scope = _cache_scope_key(current_user, response_scope)
    cache = _cache_from_request(request)
    cache_key = cache.build_dashboard_key(plan.entry.id, cache_scope, plan.params)

    cached_payload = cache.get_json(cache_key)
    if isinstance(cached_payload, list):
        return [dict(row) for row in cached_payload], response_scope, True

    rows = execute_catalog_plan(plan, session=session, current_user=current_user)
    settings = _settings_from_request(request)
    cache.set_json(cache_key, rows, settings.cache_ttl_dash_seconds)
    return rows, response_scope, False


@router.get("/dashboards-page", response_class=HTMLResponse, include_in_schema=False)
def dashboards_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboards.html",
        context={"page_title": "Dashboards · Compass"},
    )


@router.get("/dashboards", response_model=list[DashboardSummary], status_code=status.HTTP_200_OK)
def list_dashboards(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[DashboardSummary]:
    return [_summary(dashboard) for dashboard in _visible_dashboards(current_user)]


@router.get("/dashboards/{dashboard_id}/data", response_model=DashboardDataResponse, status_code=status.HTTP_200_OK)
def dashboard_data(
    dashboard_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> DashboardDataResponse:
    dashboard = _get_visible_dashboard(dashboard_id, current_user)
    rows, scope, cached = _dashboard_rows(
        request=request,
        dashboard=dashboard,
        current_user=current_user,
        session=session,
    )
    return DashboardDataResponse(
        dashboard_id=dashboard.id,
        rows=rows,
        scope=scope,  # type: ignore[arg-type]
        cached=cached,
    )


@router.post(
    "/dashboards/{dashboard_id}/analyze",
    response_model=DashboardAnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
def dashboard_analyze(
    dashboard_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> DashboardAnalyzeResponse:
    started_at = perf_counter()
    dashboard = _get_visible_dashboard(dashboard_id, current_user)
    rows, scope, cached = _dashboard_rows(
        request=request,
        dashboard=dashboard,
        current_user=current_user,
        session=session,
    )
    try:
        analysis = analyze_dashboard_rows(
            dashboard_id=dashboard.id,
            title=dashboard.title,
            scope=scope,
            rows=rows,
        )
    except GuardrailViolation as exc:
        write_audit(
            action_type="guardrail_block",
            role=current_user.role.value,
            result_status="blocked",
            user_id=current_user.user_id,
            session=session,
            detail={
                "dashboard_id": dashboard.id,
                "reason": exc.reason,
                "stage": exc.stage,
            },
        )
        session.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc

    write_audit(
        action_type="data_analysis",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "dashboard_id": dashboard.id,
            "catalog_id": dashboard.catalog_id,
            "scope": scope,
            "row_count": len(rows),
            "cached": cached,
            "latency_ms": int((perf_counter() - started_at) * 1000),
        },
    )
    return DashboardAnalyzeResponse(
        dashboard_id=dashboard.id,
        analysis_markdown=analysis,
        scope=scope,  # type: ignore[arg-type]
    )
