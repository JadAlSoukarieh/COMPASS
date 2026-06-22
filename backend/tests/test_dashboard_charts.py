"""Dashboard chart metadata + expanded dashboard set."""

from __future__ import annotations

from backend.app.routers.dashboards import DASHBOARDS, DASHBOARDS_BY_ID
from backend.app.catalog.registry import CATALOG_BY_ID

VALID_CHART_TYPES = {"bar", "pie", "line", "grouped-bar"}


def test_expanded_dashboard_set() -> None:
    # We surfaced more of the catalog as dashboards (was 7).
    assert len(DASHBOARDS) >= 12
    charted = [d for d in DASHBOARDS if d.chart_type]
    assert len(charted) >= 8


def test_new_dashboards_present() -> None:
    for did in (
        "company-avg-tenure",
        "company-leave-utilization",
        "company-new-hires",
        "company-approval-bottleneck",
    ):
        assert did in DASHBOARDS_BY_ID


def test_chart_metadata_is_consistent() -> None:
    for d in DASHBOARDS:
        if not d.chart_type:
            continue
        assert d.chart_type in VALID_CHART_TYPES, (d.id, d.chart_type)
        assert d.chart_x, f"{d.id} has chart_type but no chart_x"
        assert d.chart_y, f"{d.id} has chart_type but no chart_y series"


def test_every_dashboard_maps_to_a_real_catalog_entry() -> None:
    for d in DASHBOARDS:
        assert d.catalog_id in CATALOG_BY_ID, (d.id, d.catalog_id)


def test_grouped_bar_has_multiple_series() -> None:
    util = DASHBOARDS_BY_ID["company-leave-utilization"]
    assert util.chart_type == "grouped-bar"
    assert len(util.chart_y) >= 2  # days_total vs days_used
