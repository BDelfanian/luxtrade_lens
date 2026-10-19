"""Visualisation selector: result shape and intent pick the data product (SOLUTION_DESIGN §5.6)."""

import pandas as pd

from luxtrade.agents.spec import SPLIT_BREAKDOWNS, QuerySpec

KINDS = (
    "kpi",
    "bar",
    "change",
    "map",
    "treemap",
    "line",
    "area",
    "stacked",
    "heatmap",
    "pivot",
    "season",
    "forecast",
    "bench",
    "table",
)
MAP_MIN_COUNTRIES = 5
MAP_MAX_UNDISCLOSED_PCT = 50.0
STACKED_MAX_YEARS = 15  # one bar per year; longer share series read better as stacked areas


def _compatible(view: str, spec: QuerySpec, main: pd.DataFrame) -> bool:
    has_time = "period" in main.columns
    is_change = "change" in main.columns  # rises and falls: only diverging bars read right
    has_key = "key" in main.columns and not is_change
    # lines and heatmaps draw one series per key, or per flow: a benchmark frame has neither
    has_series = "key" in main.columns or "flow" in main.columns
    return {
        "table": True,
        "kpi": spec.intent == "single_value",
        "bar": has_key,
        "change": is_change,
        "treemap": has_key and spec.breakdown == "product",
        "map": has_key and spec.breakdown == "partner",
        "line": has_time and has_series,
        "area": has_time and has_series,
        "stacked": has_key and has_time,
        "heatmap": has_time and has_series and (has_key or spec.freq == "M"),
        "pivot": has_key and has_time,
    }.get(view, False)


def choose_view(
    spec: QuerySpec, main: pd.DataFrame, iso3_count: int = 0, undisclosed_pct: float = 0.0
) -> str:
    """Return the chart kind for this answer; a compatible user-requested view always wins."""
    if spec.intent == "benchmark" and spec.view in ("line", "area"):
        # seen on real data: "index 2015 = 100" read as a line chart; the benchmark chart is one
        return "bench"
    if spec.view != "auto" and _compatible(spec.view, spec, main):
        return spec.view
    if spec.intent == "single_value":
        return "kpi"
    if "change" in main.columns:
        return "change"
    if spec.intent in ("ranking", "composition"):
        if spec.breakdown in SPLIT_BREAKDOWNS:
            return "bar"
        if spec.breakdown == "partner":
            if iso3_count >= MAP_MIN_COUNTRIES and undisclosed_pct < MAP_MAX_UNDISCLOSED_PCT:
                return "map"
            return "bar"
        return "treemap" if spec.intent == "composition" else "bar"
    if spec.intent == "drilldown":
        return "treemap"
    if spec.intent == "time_series":
        if spec.measure != "share":
            return "line"
        years = main["period"].nunique() if "period" in main.columns else 0
        annual = spec.freq == "A" and "key" in main.columns and years <= STACKED_MAX_YEARS
        return "stacked" if annual else "area"
    return {
        "pivot": "pivot",
        "seasonality": "season",
        "forecast": "forecast",
        "benchmark": "bench",
    }.get(spec.intent, "table")
