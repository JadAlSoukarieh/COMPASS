from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.search import SourceItem


class WidgetContext(BaseModel):
    page: str | None = None
    dashboard_id: str | None = None


class WidgetMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    context: WidgetContext = Field(default_factory=WidgetContext)


class WidgetMessageResponse(BaseModel):
    intent: Literal["data_query", "data_analysis", "app_support", "refuse"]
    answer_markdown: str
    catalog_id: str | None = None
    used_params: dict[str, Any] = Field(default_factory=dict)
    scope_decision: Literal["allowed", "scoped", "refused"]
    sources: list[SourceItem] = Field(default_factory=list)
    refused: bool
