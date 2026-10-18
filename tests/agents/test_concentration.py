"""The concentration index (HHI) as an assistant measure, "every n years", and its evidence."""

import pandas as pd
import pytest

from luxtrade.agents.compile_sql import compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.evidence import compose
from luxtrade.agents.scenario import describe
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql
from luxtrade.runs.scenarios import ScenarioStep
from luxtrade.viz.charts import build_figures, evidence_bars


def hhi_spec(**changes: object) -> QuerySpec:
    values = {
        "intent": "time_series",
        "breakdown": "partner",
        "flow": "import",
        "measure": "hhi",
        "period_start": "2018",
        "period_end": "2024",
    } | changes
    return QuerySpec(**values)


def test_an_hhi_question_becomes_a_yearly_series_across_every_item(semantic):
    spec = apply_defaults(hhi_spec(intent="ranking", breakdown="none"), semantic.coverage)
    assert (spec.intent, spec.breakdown, spec.freq, spec.top_n) == (
        "time_series",
        "partner",
        "A",
        None,
    )
    assert "concentration computed for each year" in spec.assumptions
    both = apply_defaults(hhi_spec(flow="balance"), semantic.coverage)
    assert both.flow == "both"  # a balance has no shares


def test_every_n_years_keeps_a_yearly_series(semantic):
    short = apply_defaults(
        QuerySpec(
            intent="time_series", flow="export", period_start="2022", period_end="2024", year_step=2
        ),
        semantic.coverage,
    )
    assert (short.freq, short.year_step) == ("A", 2)  # three years would default to months
    growth = apply_defaults(
        QuerySpec(intent="time_series", flow="export", measure="growth_yoy", year_step=5),
        semantic.coverage,
    )
    assert growth.year_step is None  # year-on-year growth needs consecutive years
    snapshot = apply_defaults(QuerySpec(intent="ranking", year_step=5), semantic.coverage)
    assert snapshot.year_step is None


@pytest.mark.parametrize("breakdown", ["partner", "product"])
def test_the_index_is_the_sum_of_squared_shares(semantic, breakdown):
    spec = apply_defaults(hhi_spec(breakdown=breakdown, year_step=2), semantic.coverage)
    got = semantic.query(check_sql(compile_spec(spec).sql))
    assert sorted(got["period"]) == [2018, 2020, 2022, 2024]

    key = "partner" if breakdown == "partner" else "hs2"
    special = "AND NOT partner_is_special" if breakdown == "partner" else ""
    raw = semantic.query(
        f"SELECT year, {key} AS key, sum(value_eur) AS v FROM v_lu_trade_hs2 "
        f"WHERE flow = 'import' AND year IN (2018, 2020, 2022, 2024) {special} "
        "GROUP BY year, key"
    )
    raw = raw[raw["v"] > 0]
    raw["s"] = raw["v"] / raw.groupby("year")["v"].transform("sum")
    expected = (10_000 * (raw["s"] ** 2)).groupby(raw["year"]).sum()
    for row in got.itertuples():
        assert row.hhi == pytest.approx(expected[row.period])
        assert row.n == int((raw["year"] == row.period).sum())
    if breakdown == "partner":
        assert not set(got["top_key"]) & {"QY", "QV"}  # undisclosed partners left out


def test_an_hhi_run_reads_the_index_for_the_answer(make_assistant):
    rec = make_assistant(None).run_spec(hhi_spec(year_step=2), question="HHI", origin="preset")
    assert (rec.status, rec.view_kind) == ("answered", "line")
    texts = [f["text"] for f in rec.facts]
    assert any(
        t.startswith("Concentration (HHI) of imports across partners, 2018: ") for t in texts
    )
    assert any("concentrated" in t for t in texts)  # each year's reading
    (change,) = [t for t in texts if "change 2018–2024" in t]  # the direction, in words
    assert change.endswith(
        ("(more diversified)", "(less diversified)", "about as concentrated as before")
    )
    assert any("the same as" in t and "equally sized partners" in t for t in texts)
    assert any(t.startswith("Largest of the") for t in texts)
    assert "Herfindahl-Hirschman" in " ".join(rec.methods)
    assert {lim["id"] for lim in rec.limitations} >= {"L06"}


def test_concentration_steps_make_one_figure_with_a_panel_each(make_assistant, semantic):
    assistant = make_assistant(None)
    specs = {
        1: hhi_spec(breakdown="product", flow="export", year_step=3),
        2: hhi_spec(breakdown="partner", flow="import", year_step=3),
    }
    records = {
        n: assistant.run_spec(s, question=f"q{n}", origin="preset") for n, s in specs.items()
    }
    chain = [ScenarioStep(n=n, kind="plan", question=f"q{n}") for n in specs]
    (fig,) = compose(chain, records, "headline", "text", semantic)
    assert fig.kind == "concentration" and fig.steps == [1, 2]
    assert list(dict.fromkeys(r["series"] for r in fig.rows)) == [
        "Exports by product",
        "Imports by partner",
    ]
    assert sorted({r["group"] for r in fig.rows}) == [2018, 2021, 2024]
    assert [t["label"] for t in fig.tiles] == [
        "Exports by product, 2024",
        "Imports by partner, 2024",
    ]
    for tile in fig.tiles:  # red when concentration rose, green when it fell
        mine = [r["value"] for r in fig.rows if tile["label"].startswith(r["series"])]
        assert tile["tone"] == ("down" if mine[-1] > mine[0] else "up")
    chart = evidence_bars(pd.DataFrame(fig.rows), fig.kind, "en")
    assert len(chart.data) == 2 and chart.layout.annotations[0].text == "Exports by product"


def test_the_run_chart_marks_the_concentration_levels(make_assistant):
    rec = make_assistant(None).run_spec(hhi_spec(), question="HHI", origin="preset")
    (fig,) = build_figures("line", pd.DataFrame(rec.frames["main"]), "t", measure="hhi")
    assert {s.y0 for s in fig.layout.shapes} == {1_000, 1_800}
    assert fig.layout.yaxis.title.text == "HHI"


def test_the_step_says_what_it_queried():
    spec = hhi_spec(period_start="2005", period_end="2025", year_step=5, freq="A")
    assert describe(spec.model_dump()) == (
        "imports · across all partners · 2005–2025, yearly, every 5 years · "
        "concentration index (HHI)"
    )
