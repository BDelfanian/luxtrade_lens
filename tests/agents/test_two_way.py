"""Two-way trade (Grubel-Lloyd) as an assistant measure, its facts, checks and evidence."""

from types import SimpleNamespace

import pandas as pd
import pytest

from luxtrade.agents.analyse import short_label
from luxtrade.agents.compile_sql import compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.evidence import compose
from luxtrade.agents.facts import two_way_reading
from luxtrade.agents.scenario import describe, two_way_cause, two_way_misread
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql
from luxtrade.runs.store import RunRecord
from luxtrade.viz.charts import build_figures, evidence_bars


def ranking(**changes: object) -> QuerySpec:
    values = {
        "intent": "ranking",
        "measure": "two_way",
        "period_start": "2024",
        "period_end": "2024",
    } | changes
    return QuerySpec(**values)


YEARLY = QuerySpec(
    intent="time_series",
    measure="two_way",
    breakdown="product",
    product_level="CN8",
    period_start="2018",
    period_end="2024",
    year_step=2,
)


def test_two_way_compares_both_flows_by_product(semantic):
    spec = apply_defaults(ranking(flow="export", breakdown="partner"), semantic.coverage)
    assert (spec.flow, spec.breakdown, spec.intent, spec.product_level) == (
        "both",
        "product",
        "ranking",
        "HS2",
    )
    assert apply_defaults(YEARLY, semantic.coverage).freq == "A"
    assert "two-way trade index" in describe(spec.model_dump(mode="json"))


def test_the_index_matches_its_definition(semantic):
    spec = apply_defaults(ranking(), semantic.coverage)
    df = semantic.query(check_sql(compile_spec(spec).sql))
    by_key = semantic.query(
        "SELECT hs2 AS key, sum(value_eur) FILTER (WHERE flow = 'export') AS x, "
        "sum(value_eur) FILTER (WHERE flow = 'import') AS m FROM v_lu_trade "
        "WHERE year = 2024 AND hs2 NOT LIKE '%X%' GROUP BY hs2"
    ).fillna(0)
    x, m = by_key["x"], by_key["m"]
    matched = 100 * (x + m - (x - m).abs()).sum() / (x + m).sum()
    assert df["gl_all"].iloc[0] == pytest.approx(matched)
    row = df.iloc[0]
    assert row["gl"] == pytest.approx(
        100 * (1 - abs(row["export"] - row["import"]) / (row["export"] + row["import"]))
    )
    assert df["n"].iloc[0] == len(by_key)


@pytest.mark.parametrize(
    ("gl", "exported", "reading"),
    [
        (88, True, "traded both ways in similar amounts"),
        (48, False, "traded both ways, mostly imported"),
        (7, True, "almost only exported (one-way)"),
    ],
)
def test_the_index_in_words(gl, exported, reading):
    assert two_way_reading(gl, exported, "en") == reading


def test_short_labels_keep_the_first_clause():
    long = (
        "Ferrous waste and scrap; remelting scrap ingots of iron or steel (excl. slag, scale "
        "and other waste)"
    )
    assert short_label(long) == "Ferrous waste and scrap"
    assert short_label("Computers") == "Computers"


def test_facts_figure_and_charts(make_assistant, semantic):
    assistant = make_assistant()
    specs = [ranking(), YEARLY, ranking(products=["84"])]
    records = {
        n: assistant.run_spec(s, question=f"q{n}", origin="preset")
        for n, s in enumerate(specs, start=1)
    }
    assert all(r.status == "answered" and r.view_kind == "two_way" for r in records.values())
    facts = {f["key"]: f["text"] for f in records[1].facts}
    assert facts["two_way.all"].startswith("Two-way trade 2024, all ")
    item = next(t for k, t in facts.items() if k.count(".") == 1 and k[-2:].isdigit())
    assert "two-way index" in item and "% of exports" in item
    yearly = {f["key"]: f["text"] for f in records[2].facts}
    assert {"two_way.2018", "two_way.2020", "two_way.2022", "two_way.2024", "two_way.change"} <= (
        set(yearly)
    )
    assert "at CN8 product level" in yearly["two_way.2024"]
    scoped = {f["key"]: f["text"] for f in records[3].facts}
    assert any("of these exports" in t for t in scoped.values())  # shares of the chapter

    chain = [SimpleNamespace(n=n) for n in records]
    [fig] = compose(chain, records, "", "", semantic)
    assert fig.kind == "two_way" and fig.steps == [1, 2, 3]
    assert {r["panel"] for r in fig.rows} == {"items", "share"}
    labels = [t["label"] for t in fig.tiles]
    assert labels[0] == "of trade two-way at CN8 product level, 2024"
    assert any(label.startswith("Machinery") for label in labels)  # the chapter drilled into
    assert len(evidence_bars(pd.DataFrame(fig.rows), fig.kind, "en", fig.panels).data) > 2
    for n in (1, 2):
        rec = records[n]
        figs = build_figures(rec.view_kind, rec.frame("main"), "t", lang="en")
        assert figs and all(len(f.data) for f in figs)


def _ranked(facts: list[dict]) -> RunRecord:
    frame = [{"period": 2025, "gl_all": 39.1, "key": "85171300"}]
    return RunRecord.model_construct(
        spec={"measure": "two_way", "intent": "ranking", "product_level": "CN8"},
        facts=facts,
        frames={"main": frame},
        status="answered",
    )


ROBOTS = {
    "key": "two_way.84287000",
    "text": "Industrial robots (84287000): exports 233.8 M€ (1.4 % of exports), imports 747.2 M€ "
    "(3.0 % of imports); two-way index 48: traded both ways, mostly imported",
}
PHONES = {
    "key": "two_way.85171300",
    "text": "Smartphones for wireless networks (85171300): exports 898.3 M€ (5.5 % of exports), "
    "imports 701.3 M€ (2.8 % of imports); two-way index 88: traded both ways in similar amounts",
}


def test_a_product_is_held_to_its_own_reading():
    records = {6: _ranked([ROBOTS, PHONES])}
    bad = "Smartphones and Industrial robots are traded both ways in similar amounts."
    (problem,) = two_way_misread(bad, {6}, records)
    assert "Industrial robots" in problem and "index is 48" in problem
    for fine in (
        "Smartphones are traded in similar amounts, while Industrial robots are mostly imported.",
        "Most chapters are balanced, except Industrial robots, which are mostly imported.",
    ):
        assert two_way_misread(fine, {6}, records) == []


def test_mostly_the_same_goods_needs_the_finest_level_above_half():
    records = {6: _ranked([PHONES])}
    (problem,) = two_way_misread("Luxembourg mostly trades similar goods both ways.", {6}, records)
    assert "only 39.1 %" in problem
    assert two_way_misread("Chapters overlap; 39.1 % is the same goods.", {6}, records) == []


def test_two_way_trade_is_not_explained_by_causes_the_data_lack():
    records = {6: _ranked([PHONES])}
    assert two_way_cause("Phones are re-exported through Luxembourg.", {6}, records)
    assert two_way_cause("Phones are both exported and imported.", {6}, records) == []
    other = {1: RunRecord.model_construct(spec={"measure": "value_eur"})}
    assert two_way_cause("Fuel transit grew.", {1}, other) == []  # not a two-way step
