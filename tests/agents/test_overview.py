"""Overview (landing page): deterministic, evidence-backed and consistent with the assistant."""

import pandas as pd
import pytest

from luxtrade.agents.overview import build_overview
from luxtrade.agents.sql_guard import check_sql
from luxtrade.viz.charts import overview_figures
from luxtrade.viz.format import fmt_eur, fmt_pct


@pytest.fixture(scope="module")
def overview_en(semantic):
    return build_overview(semantic, "en")


def test_overview_has_five_questions_and_four_headline_figures(overview_en):
    assert [p.key for p in overview_en.panels] == [
        "trend",
        "partners",
        "products",
        "season",
        "peers",
    ]
    assert len(overview_en.kpis) == 4
    for panel in overview_en.panels:
        assert panel.question.endswith("?")
        assert panel.takeaway
        assert panel.facts
        assert not panel.frames["main"].empty


def test_every_panel_shows_guarded_sql(overview_en):
    for panel in overview_en.panels:
        assert panel.sql
        for sql in panel.sql:
            assert check_sql(sql) == sql  # already normalised by the guard


def test_overview_is_deterministic(semantic, overview_en):
    again = build_overview(semantic, "en")
    assert [p.facts for p in again.panels] == [p.facts for p in overview_en.panels]
    assert [k.value for k in again.kpis] == [k.value for k in overview_en.kpis]


@pytest.mark.parametrize("lang", ["fr", "de"])
def test_overview_follows_the_language(semantic, overview_en, lang):
    ov = build_overview(semantic, lang)
    for local, en in zip(ov.panels, overview_en.panels, strict=True):
        assert local.question != en.question
        assert local.explore_spec.language == lang


def test_headline_figures_match_the_trend_panel(overview_en):
    trend = overview_en.panels[0].frames["main"]
    latest = trend[trend["period"] == overview_en.year]
    exports = latest.loc[latest["flow"] == "export", "value"].iloc[0]
    assert overview_en.kpis[0].label == f"Exports {overview_en.year}"
    assert overview_en.kpis[0].spark  # sparkline over the whole series
    assert overview_en.kpis[0].value == fmt_eur(exports, "en")


def test_explore_reproduces_the_panel_numbers(make_assistant, overview_en):
    """'Explore' runs the panel's spec in the assistant: same rows, same values."""
    assistant = make_assistant()
    panel = next(p for p in overview_en.panels if p.key == "partners")
    rec = assistant.run_spec(panel.explore_spec, question=panel.explore_question, origin="overview")
    assert rec.status == "answered"
    assert rec.sql == panel.sql[0]
    ours = panel.frames["main"].sort_values(["flow", "key"]).reset_index(drop=True)
    theirs = rec.frame("main").sort_values(["flow", "key"]).reset_index(drop=True)
    pd.testing.assert_series_equal(ours["value"], theirs["value"], check_dtype=False)


def test_overview_figures_render_for_every_panel(overview_en):
    for panel in overview_en.panels:
        figs = overview_figures(panel.key, panel.frames, panel.chart_titles, "en")
        assert figs, panel.key


def test_trend_marks_reference_events_inside_the_series(overview_en):
    trend = overview_en.panels[0]
    years = set(trend.frames["main"]["period"])
    assert set(trend.frames["events"]["year"]) <= set(range(min(years), max(years) + 1))
    assert any("not part of the data" in m for m in trend.methods)


def test_dependence_sparkline_ends_at_the_headline_share(overview_en):
    partners = next(p for p in overview_en.panels if p.key == "partners")
    conc = partners.frames["concentration"]
    assert int(conc["year"].iloc[-1]) == overview_en.year
    tile = overview_en.kpis[3]
    assert tile.spark[-1] == pytest.approx(round(conc["top_share"].iloc[-1], 2))
    assert tile.value == fmt_pct(conc["top_share"].iloc[-1], "en")
