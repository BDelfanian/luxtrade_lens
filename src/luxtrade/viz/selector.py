"""Visualisation selector: result shape and intent pick the data product (SOLUTION_DESIGN §5.6)."""

import pandas as pd

from luxtrade.agents.spec import SPLIT_BREAKDOWNS, QuerySpec

KINDS = (
    "kpi",
    "bar",
    "map",
    "treemap",
    "line",
    "area",
    "pivot",
    "season",
    "forecast",
    "bench",
    "table",
)
MAP_MIN_COUNTRIES = 5
MAP_MAX_UNDISCLOSED_PCT = 50.0


def _compatible(view: str, spec: QuerySpec, main: pd.DataFrame) -> bool:
    has_key = "key" in main.columns
    has_time = "period" in main.columns
    return {
        "table": True,
        "kpi": spec.intent == "single_value",
        "bar": has_key,
        "treemap": has_key and spec.breakdown == "product",
        "map": has_key and spec.breakdown == "partner",
        "line": has_time,
        "area": has_time,
        "pivot": has_key and has_time,
    }.get(view, False)


def choose_view(
    spec: QuerySpec, main: pd.DataFrame, iso3_count: int = 0, undisclosed_pct: float = 0.0
) -> str:
    """Return the chart kind for this answer; a compatible user-requested view always wins."""
    if spec.view != "auto" and _compatible(spec.view, spec, main):
        return spec.view
    if spec.intent == "single_value":
        return "kpi"
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
        return "area" if spec.measure == "share" else "line"
    return {
        "pivot": "pivot",
        "seasonality": "season",
        "forecast": "forecast",
        "benchmark": "bench",
    }.get(spec.intent, "table")
