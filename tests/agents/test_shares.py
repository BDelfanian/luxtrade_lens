"""Shares of the whole flow: a filter on the shared dimension never shrinks the denominator."""

import pytest

from luxtrade.agents.compile_sql import compile_spec, share_base
from luxtrade.agents.spec import QuerySpec

RANKING = dict(intent="ranking", flow="import", measure="share", period_start="2024")


@pytest.mark.parametrize(
    ("fields", "dropped"),
    [
        (dict(breakdown="partner", partners=["BE", "DE"]), "partner"),
        (dict(breakdown="product", products=["84", "85"]), "product"),
        (dict(breakdown="none", partners=["CN"], products=["27"]), "partner"),
        (dict(breakdown="none", products=["8471"]), "product"),
        (dict(breakdown="partner", partner_group="EXTRA_EU27_2020"), "partner"),
    ],
)
def test_the_total_drops_only_the_shared_filter(fields, dropped):
    spec = QuerySpec(**{**RANKING, **fields})
    base, share_of = share_base(spec)
    assert share_of == dropped
    if dropped == "partner":
        assert base.partners == [] and base.partner_group == "WORLD"
        assert base.products == spec.products  # "shares of fuel imports" stay within fuel
    else:
        assert base.products == [] and base.partners == spec.partners


@pytest.mark.parametrize(
    "fields",
    [
        dict(breakdown="partner"),  # no filter: the result's own total is the whole
        dict(breakdown="partner", products=["27"]),  # partners of fuel: shares within fuel
        dict(breakdown="partner", partners=["BE"], measure="value_eur"),
        dict(breakdown="partner", partners=["BE"], flow="balance"),
    ],
)
def test_no_total_query_when_the_selection_is_the_whole(fields):
    spec = QuerySpec(**{**RANKING, **fields})
    assert share_base(spec) is None and compile_spec(spec).total_sql is None


def test_ranking_shares_are_of_all_partners(make_assistant, semantic):
    spec = QuerySpec(**RANKING, breakdown="partner", partners=["BE", "DE"], period_end="2024")
    rec = make_assistant().run_spec(spec, question="BE and DE share", origin="preset")
    assert rec.status == "answered" and len(rec.support_sql) == 1
    whole = semantic.query(rec.support_sql[0])["value_eur"].sum()
    for row in (r for r in rec.frames["main"] if r["kind"] == "item"):
        assert row["share"] == pytest.approx(100 * row["value"] / whole)
    assert any("selection" in f["text"] for f in rec.facts)


def test_series_share_of_one_product_is_a_percentage(make_assistant):
    spec = QuerySpec(
        intent="time_series",
        products=["27"],
        flow="import",
        measure="share",
        period_start="2023",
        period_end="2024",
        freq="A",
    )
    rec = make_assistant().run_spec(spec, question="fuel share", origin="preset")
    values = [r["value"] for r in rec.frames["main"]]
    assert values and all(0 < v < 100 for v in values)


def test_eu_split_never_filters_on_one_group(make_assistant):
    spec = QuerySpec(
        intent="composition",
        breakdown="partner_group",
        partner_group="EU27_2020",
        flow="import",
        measure="share",
        period_start="2024",
    )
    rec = make_assistant().run_spec(spec, question="EU share", origin="preset")
    assert rec.spec["partner_group"] == "WORLD"
    assert {r["key"] for r in rec.frames["main"]} == {"EU27", "NON_EU27"}
