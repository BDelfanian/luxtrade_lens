from unittest.mock import patch

import pytest

from luxtrade.agents.dashboard import ChartRequest, DashboardService, DashboardSpec, QueryRequest
from luxtrade.agents.sql_guard import SQLRejectedError
from luxtrade.config import SQL_ROW_LIMIT
from luxtrade.viz.registry import ChartSpec

QUERY = (
    "SELECT period, flow, SUM(value_eur) AS amount FROM v_lu_trade_hs2 "
    "GROUP BY period, flow ORDER BY period"
)


def test_preview_is_guarded_and_describes_temporal_numeric_columns(semantic):
    service = DashboardService(semantic)
    result = service.preview(QueryRequest(query=QUERY))
    payload = result.payload()
    assert f"LIMIT {SQL_ROW_LIMIT}" in result.sql
    assert {c["name"]: c["type"] for c in payload["columns"]} == {
        "period": "temporal",
        "flow": "categorical",
        "amount": "numeric",
    }
    assert isinstance(payload["rows"][0]["period"], str)
    assert payload["row_count"] > 0


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE v_lu_trade",
        "SELECT * FROM read_csv('file.csv')",
        "SELECT * FROM secrets",
        "SELECT 1; SELECT 2",
    ],
)
def test_unsafe_dashboard_sql_never_reaches_database(semantic, query):
    service = DashboardService(semantic)
    with patch.object(semantic, "query") as execute:
        with pytest.raises(SQLRejectedError):
            service.preview(QueryRequest(query=query))
        execute.assert_not_called()


def test_dashboard_reuses_queries_and_isolates_errors(semantic):
    service = DashboardService(semantic)
    chart = ChartRequest(
        query=QUERY,
        chart=ChartSpec(type="line", mapping={"x": "period", "y": "amount", "color": "flow"}),
    )
    bad = ChartRequest(
        query=QUERY, chart=ChartSpec(type="bar", mapping={"x": "missing", "y": "amount"})
    )
    assert service.source  # Load coverage before counting data queries.
    with patch.object(semantic, "query", wraps=semantic.query) as execute:
        rendered = service.render_dashboard(DashboardSpec(charts=[chart, bad, chart]))
        assert execute.call_count == 1
    assert "figure" in rendered["panels"][0]
    assert "error" in rendered["panels"][1]
    assert "figure" in rendered["panels"][2]
    assert "Eurostat" in rendered["source"]


def test_dashboard_definition_round_trips():
    dashboard = DashboardSpec(
        title="Trade",
        columns=3,
        charts=[
            ChartRequest(
                query=QUERY,
                chart=ChartSpec(
                    type="line",
                    mapping={"x": "period", "y": ["amount"]},
                    column_types={"period": "temporal"},
                ),
            )
        ],
    )
    assert DashboardSpec.model_validate_json(dashboard.model_dump_json()) == dashboard
