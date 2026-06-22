from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    id: str
    title: str
    description: str
    catalog_id: str
    scope: Literal["self", "team", "company"]
    default_params: dict[str, Any]
    chart_type: str | None = None
    chart_x: str | None = None
    chart_y: list[str] = []


class DashboardDataResponse(BaseModel):
    dashboard_id: str
    rows: list[dict[str, Any]]
    scope: Literal["self", "team", "company"]
    cached: bool


class DashboardAnalyzeResponse(BaseModel):
    dashboard_id: str
    analysis_markdown: str
    scope: Literal["self", "team", "company"]
