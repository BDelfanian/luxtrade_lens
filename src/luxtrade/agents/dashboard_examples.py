"""Ready-to-run dashboard definitions using the latest complete years of trade data."""

from luxtrade.agents.dashboard import ChartRequest
from luxtrade.viz.registry import ChartSpec


def time_series_examples(latest_year: int) -> dict[str, ChartRequest]:
    """Return bounded examples with explicit chart roles and sensible display defaults."""
    first_year = latest_year - 5
    return {
        "Partner rankings over time": ChartRequest(
            query=f"""SELECT t.year, p.label_en AS partner, SUM(t.value_eur) AS amount
FROM v_lu_trade_hs2 AS t
JOIN dim_partner AS p ON t.partner = p.partner
WHERE t.flow = 'export' AND NOT t.partner_is_special
  AND t.year BETWEEN {first_year} AND {latest_year}
GROUP BY t.year, p.label_en
ORDER BY t.year, p.label_en""",
            chart=ChartSpec(
                type="bar_race",
                title="Leading export partners over time",
                description="Move the year slider or press Play to re-rank export partners.",
                mapping={"time": "year", "category": "partner", "value": "amount"},
                labels={"year": "Year", "amount": "Exports (EUR)"},
                options={"top_n": 10, "frame_duration": 900, "fixed_scale": True},
                height=560,
            ),
        ),
        "Monthly trade composition": ChartRequest(
            query=f"""SELECT period, flow, SUM(value_eur) AS amount
FROM v_lu_trade_hs2
WHERE year BETWEEN {first_year} AND {latest_year}
GROUP BY period, flow
ORDER BY period, flow""",
            chart=ChartSpec(
                type="area",
                title="Monthly trade over time",
                description="Use the range slider to zoom; enable Normalize to compare shares.",
                mapping={"x": "period", "y": "amount", "color": "flow"},
                column_types={"period": "temporal"},
                labels={"period": "Month", "amount": "Trade value (EUR)"},
                options={"range_slider": True, "normalize": False},
                height=500,
            ),
        ),
    }
