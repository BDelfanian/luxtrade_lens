"""Shared dashboard service for Streamlit and HTTP: guarded SQL to mapped figures."""

import json
import logging
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from pydantic import BaseModel, ConfigDict, Field

from luxtrade.agents.sql_guard import check_sql
from luxtrade.config import ATTRIBUTION, SQL_ROW_LIMIT
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.viz.mapped_charts import CHARTS
from luxtrade.viz.registry import ChartRegistry, ChartSpec

logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    """One SQL query against the public semantic views."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=50_000)


class ChartRequest(QueryRequest):
    """Query plus a chart definition, usable as an API request or dashboard panel."""

    chart: ChartSpec


class DashboardSpec(BaseModel):
    """Versioned, exportable dashboard layout and its ordered chart requests."""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    title: str = "My dashboard"
    description: str = ""
    columns: int = Field(default=2, ge=1, le=3)
    charts: list[ChartRequest] = Field(default_factory=list, max_length=24)


def describe_columns(frame: pd.DataFrame) -> list[dict]:
    """Describe query output for mapping controls without inferring dates from names."""
    columns = []
    for name in frame.columns:
        dtype = frame[name].dtype
        kind = "categorical"
        if pd.api.types.is_datetime64_any_dtype(dtype):
            kind = "temporal"
        elif pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
            kind = "numeric"
        columns.append({"name": name, "dtype": str(dtype), "type": kind})
    return columns


@dataclass
class QueryResult:
    """Checked SQL and its bounded output, retained for evidence and preview."""

    sql: str
    frame: pd.DataFrame

    def payload(self) -> dict:
        """Return JSON-safe rows (including dates and nulls) plus column metadata."""
        return {
            "sql": self.sql,
            "columns": describe_columns(self.frame),
            "rows": json.loads(self.frame.to_json(orient="records", date_format="iso")),
            "row_count": len(self.frame),
            "row_limit": SQL_ROW_LIMIT,
            "at_row_limit": len(self.frame) >= SQL_ROW_LIMIT,
        }


class DashboardService:
    """Keep query execution and chart validation identical across both front ends."""

    def __init__(self, sem: SemanticLayer, registry: ChartRegistry = CHARTS) -> None:
        self.sem = sem
        self.registry = registry

    @property
    def source(self) -> str:
        """Attribution for every rendered chart."""
        return ATTRIBUTION.format(date=self.sem.coverage.extraction_date)

    def preview(self, request: QueryRequest) -> QueryResult:
        """Run guarded, row-limited SQL with the semantic layer's read-only timeout."""
        sql = check_sql(request.query)
        frame = self.sem.query(sql)
        logger.info("dashboard query | rows=%s | sql=%s", len(frame), sql)
        return QueryResult(sql=sql, frame=frame)

    def render(self, request: ChartRequest) -> tuple[QueryResult, go.Figure]:
        """Execute a query and render the mapped output."""
        self.registry.get(request.chart.type)
        result = self.preview(request)
        return result, self.registry.render(result.frame, request.chart)

    def render_dashboard(self, dashboard: DashboardSpec) -> dict:
        """Render all panels, isolating individual panel errors and reusing identical queries."""
        results: dict[str, QueryResult] = {}
        panels = []
        for request in dashboard.charts:
            try:
                sql = check_sql(request.query)
                if sql not in results:
                    results[sql] = self.preview(request)
                result = results[sql]
                figure = self.registry.render(result.frame, request.chart)
                panels.append(
                    {"chart": request.chart.model_dump(), **self.chart_payload(result, figure)}
                )
            except (ValueError, RuntimeError) as exc:
                panels.append({"chart": request.chart.model_dump(), "error": str(exc)})
        return {"dashboard": dashboard.model_dump(), "panels": panels, "source": self.source}

    def chart_payload(self, result: QueryResult, figure: go.Figure) -> dict:
        """Return a Plotly JSON figure alongside its query, data and provenance."""
        return {
            **result.payload(),
            "figure": json.loads(figure.to_json()),
            "source": self.source,
            "is_placeholder": self.sem.coverage.is_placeholder,
        }
