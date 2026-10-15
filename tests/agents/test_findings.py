"""Key findings (Overview story tab): deterministic, evidence-backed and explorable."""

import pytest

from luxtrade.agents.findings import build_findings, snapshot_years
from luxtrade.agents.sql_guard import check_sql
from luxtrade.viz.charts import finding_figures

KEYS = ["diversification", "shocks", "europe", "prices", "conclusion"]


@pytest.fixture(scope="module")
def findings_en(semantic):
    return build_findings(semantic, "en")[2]


def test_four_findings_and_a_conclusion(findings_en):
    assert [f.key for f in findings_en] == KEYS
    for f in findings_en:
        assert f.name and f.title and f.summary and f.facts
        assert not f.frames["main"].empty
    # the four findings carry a headline figure; the conclusion carries the options table
    assert all(f.metric_value for f in findings_en[:4])
    assert list(findings_en[-1].frames["main"].columns) == [
        "Finding",
        "Option",
        "Monitor in LuxTrade Lens with",
    ]


def test_every_finding_shows_guarded_sql(findings_en):
    for f in findings_en[:4]:
        assert f.sql
        for sql in f.sql:
            assert check_sql(sql) == sql  # already normalised by the guard


def test_findings_are_deterministic(semantic, findings_en):
    again = build_findings(semantic, "en")[2]
    assert [f.facts for f in again] == [f.facts for f in findings_en]


@pytest.mark.parametrize("lang", ["fr", "de"])
def test_findings_follow_the_language(semantic, findings_en, lang):
    hero, intro, local = build_findings(semantic, lang)
    en_hero, en_intro, _ = build_findings(semantic, "en")
    assert hero != en_hero and intro != en_intro
    for loc, en in zip(local, findings_en, strict=True):
        assert loc.title != en.title and loc.headline != en.headline
        if loc.explore_spec is not None:
            assert loc.explore_spec.language == lang


def test_hhi_matches_an_independent_computation(semantic, findings_en):
    """Export concentration by HS2 chapter, recomputed in pandas from the raw view."""
    cov = semantic.coverage
    year = cov.latest_complete_year
    rows = semantic.query(
        f"SELECT hs2, sum(value_eur) AS v FROM v_lu_trade_hs2 "
        f"WHERE flow = 'export' AND year = {year} GROUP BY hs2"
    )
    shares = rows["v"] / rows["v"].sum()
    expected = 10_000 * (shares**2).sum()
    hhi = findings_en[0].frames["main"]
    got = hhi[(hhi["dim"] == "product") & (hhi["flow"] == "export") & (hhi["year"] == year)]
    assert got["hhi"].iloc[0] == pytest.approx(expected)


def test_snapshot_years_step_back_from_the_latest_year():
    assert snapshot_years(2002, 2025) == [2005, 2010, 2015, 2020, 2025]
    assert snapshot_years(2018, 2025) == [2020, 2025]
    assert snapshot_years(2024, 2025) == [2024, 2025]


def test_finding_figures_render(findings_en):
    for f in findings_en[:4]:
        figs = finding_figures(f.key, f.frames, f.chart_titles, "en")
        assert figs, f.key


@pytest.mark.parametrize("key", KEYS[:4])
def test_explore_answers_in_the_assistant(make_assistant, findings_en, key):
    f = next(x for x in findings_en if x.key == key)
    rec = make_assistant().run_spec(f.explore_spec, question=f.explore_question, origin="overview")
    assert rec.status == "answered", rec.status
