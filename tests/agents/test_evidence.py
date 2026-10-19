"""Evidence figures: comparable steps become one chart and key figures, computed by code."""

from types import SimpleNamespace

from luxtrade.agents.evidence import compose
from luxtrade.agents.spec import QuerySpec


def change(y0: str, y1: str) -> QuerySpec:
    return QuerySpec(
        intent="ranking",
        breakdown="product",
        flow="export",
        measure="change",
        period_start=y0,
        period_end=y1,
    )


def share(year: str) -> QuerySpec:
    return QuerySpec(
        intent="composition",
        breakdown="product",
        flow="export",
        measure="share",
        period_start=year,
        period_end=year,
    )


def runs(assistant, specs):
    records = {
        n: assistant.run_spec(s, question=f"q{n}", origin="preset")
        for n, s in enumerate(specs, start=1)
    }
    return [SimpleNamespace(n=n) for n in records], records


def test_change_steps_compare_the_named_item_with_the_whole_flow(make_assistant, semantic):
    assistant = make_assistant()
    chain, records = runs(assistant, [change("2019", "2020"), change("2023", "2024")])
    label = next(r["label"] for r in records[1].frames["main"] if r["kind"] == "item")
    [fig] = compose(chain, records, f"{label} fell most.", "", semantic)
    assert fig.kind == "change" and fig.steps == [1, 2]
    assert {r["series"] for r in fig.rows} == {label, "All exports"}
    assert [r["group"] for r in fig.rows if r["series"] == label] == ["2019 → 2020", "2023 → 2024"]
    # the whole flow is the step's own SQL summed: the total change of all exports
    df = semantic.query(records[1].sql)
    by_year = df.groupby("year")["value_eur"].sum()
    whole = next(r["value"] for r in fig.rows if r["series"] == "All exports" and r["step"] == 1)
    assert abs(whole - 100 * (by_year[2020] / by_year[2019] - 1)) < 1e-9
    assert fig.tiles[0]["label"].startswith(label)


def test_share_steps_compare_two_years_and_unrelated_steps_make_no_chart(make_assistant, semantic):
    assistant = make_assistant()
    chain, records = runs(assistant, [share("2019"), share("2024"), change("2023", "2024")])
    figs = compose(chain, records, "Exports spread out.", "", semantic)
    assert [f.kind for f in figs] == ["share"]  # one change step alone is not a comparison
    assert {r["series"] for r in figs[0].rows} == {"2019", "2024"}
    assert len({r["group"] for r in figs[0].rows}) == 3  # the three largest items of 2024
    assert compose(chain[2:], records, "", "", semantic) == []


def test_a_projection_is_one_figure_with_its_range_season_and_method(make_assistant, semantic):
    import pandas as pd

    from luxtrade.viz.charts import evidence_bars

    assistant = make_assistant()
    ahead = QuerySpec(intent="forecast", flow="both", period_end="2028-12")
    season = QuerySpec(intent="seasonality", flow="both")
    chain, records = runs(assistant, [ahead, season])
    [fig] = compose(chain, records, "", "", semantic)
    assert fig.kind == "projection" and fig.steps == [1] and fig.flow == "both"
    projected = [r for r in fig.rows if r["kind"] == "projection"]
    assert projected and all(r["lo80"] <= r["value"] <= r["hi80"] for r in projected)
    assert max(r["group"] for r in projected) > 2028.9  # to December 2028
    labels = [t["label"] for t in fig.tiles]
    assert labels[:2] == ["Exports, projected total 2028", "Imports, projected total 2028"]
    assert labels[2:] == [f"{f} in March, vs a typical month" for f in ("Exports", "Imports")]
    # the method and each flow's fitted parameters, read from the steps' own method notes
    assert "500 simulated paths" in fig.note and "fitted on Jan 2018 to" in fig.note
    assert "Exports" in fig.caption and "Imports" in fig.caption
    chart = evidence_bars(pd.DataFrame(fig.rows), fig.kind, "en")
    assert len(chart.data) == 8  # per flow: the band's two edges, observed and projected


def test_the_fitted_parameters_or_the_fallback_are_said():
    from luxtrade.agents.evidence import _fitted
    from luxtrade.runs.store import RunRecord

    methods = [
        "export: ETS (additive damped trend + monthly seasonality, log values); smoothing α "
        "(level) 0.50, β (trend) 0.00, γ (season) 0.00, damping φ 0.98; fitted on 294 months "
        "(Jan 2002 to Jun 2026); back-test on the last 12 months: MAPE 8.9 % (seasonal-naive "
        "11.9 %); 80 and 95 % intervals from 500 simulated paths",
        "import: Seasonal-naive (same month last year), because ETS did not beat it; σ of the "
        "yearly log change 0.134; fitted on 294 months (Jan 2002 to Jun 2026); back-test on the "
        "last 12 months: MAPE 8.0 % (seasonal-naive 7.3 %); 80 and 95 % intervals from 500 "
        "simulated paths",
    ]
    rec = RunRecord.model_construct(methods=methods)
    ets, naive = _fitted([1], {1: rec}, "en")
    assert ets["short"] == "Exports α 0.50, φ 0.98"
    assert "β (trend) 0.00" in ets["long"] and "8.9 % (same month last year: 11.9 %)" in ets["long"]
    assert naive["short"].startswith("Imports: same month last year")
    assert "(8.0 % vs 7.3 %)" in naive["long"]
    assert "σ of the yearly log change 0.134" in naive["long"]
