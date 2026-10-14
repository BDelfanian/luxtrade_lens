import pytest

from luxtrade.agents import guard
from luxtrade.agents.compile_sql import SpecError, compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql

INTENT_SPECS = [
    QuerySpec(intent="ranking"),
    QuerySpec(intent="ranking", breakdown="product"),
    QuerySpec(intent="composition", breakdown="product", flow="import"),
    QuerySpec(intent="drilldown", partners=["DE"], products=["84"]),
    QuerySpec(intent="time_series", breakdown="partner", partners=["DE", "FR"], flow="export"),
    QuerySpec(intent="seasonality", flow="export"),
    QuerySpec(intent="forecast", flow="import"),
    QuerySpec(intent="single_value", flow="export"),
    QuerySpec(intent="pivot", breakdown="partner"),
    QuerySpec(intent="benchmark", flow="export"),
]


@pytest.mark.parametrize("spec", INTENT_SPECS, ids=lambda s: s.intent)
def test_every_intent_compiles_guards_and_runs(semantic, spec):
    resolved = apply_defaults(spec, semantic.coverage)
    df = semantic.query(check_sql(compile_spec(resolved).sql))
    assert not df.empty


def test_defaults_are_stated_like_the_golden_set(semantic):
    resolved = apply_defaults(QuerySpec(intent="ranking", breakdown="product"), semantic.coverage)
    assert resolved.period_start == resolved.period_end == "2025"
    assert resolved.flow == "both" and resolved.product_level == "HS2"
    assert "exports and imports (no flow given)" in resolved.assumptions
    assert "latest complete year 2025 (no period given)" in resolved.assumptions
    assert "HS2 chapters (no level given)" in resolved.assumptions


def test_ranking_matches_reference_sql(semantic):
    resolved = apply_defaults(
        QuerySpec(intent="ranking", breakdown="partner", flow="export"), semantic.coverage
    )
    df = semantic.query(compile_spec(resolved).sql)
    ref = semantic.query(
        "SELECT sum(value_eur) AS v FROM v_lu_trade WHERE year = 2025 AND flow = 'export'"
    )["v"].iloc[0]
    assert df["value_eur"].sum() == pytest.approx(ref)


def test_invalid_codes_never_reach_sql():
    with pytest.raises(SpecError):
        compile_spec(
            QuerySpec(
                intent="ranking",
                partners=["DE'; DROP"],
                period_start="2025",
                period_end="2025",
                flow="export",
                product_level="TOTAL",
            )
        )


def test_pre_2002_is_blocked(semantic):
    spec = apply_defaults(QuerySpec(intent="time_series", period_start="1995"), semantic.coverage)
    assert guard.is_blocked(guard.check_spec(spec, semantic.coverage))


def test_recent_months_block_totals_but_warn_for_extra_eu(semantic):
    cov = semantic.coverage
    total = apply_defaults(QuerySpec(intent="single_value", period_start="2026-03"), cov)
    extra = total.model_copy(update={"partner_group": "EXTRA_EU27_2020"})
    assert {(lim.id, lim.severity) for lim in guard.check_spec(total, cov)} >= {("L04", "block")}
    assert {(lim.id, lim.severity) for lim in guard.check_spec(extra, cov)} >= {("L04", "warn")}


def test_long_cn8_series_warns_about_code_changes(semantic):
    spec = apply_defaults(
        QuerySpec(intent="time_series", products=["84711000"], period_start="2010"),
        semantic.coverage,
    )
    assert "L05" in {lim.id for lim in guard.check_spec(spec, semantic.coverage)}


@pytest.mark.parametrize(
    "question",
    [
        "What share of GDP are exports?",
        "Part des exportations dans le PIB ?",
        "Exporte im Verhältnis zum BIP",
        "trade in services with France",
    ],
)
def test_out_of_scope_topics_are_blocked(question):
    assert guard.is_blocked(guard.check_question(question))


def test_why_questions_only_warn():
    lims = guard.check_question("Why did exports drop in 2020?")
    assert [lim.id for lim in lims] == ["S04"] and not guard.is_blocked(lims)


def test_post_rules_fire_on_shares():
    spec = QuerySpec(intent="ranking", breakdown="partner")
    lims = guard.check_result(spec, guard.ScopeStats(total=100.0, confidential=5.0, special=2.0))
    assert [lim.id for lim in lims] == ["L03"]
    assert "2.0 %" in lims[0].message
    product = spec.model_copy(update={"breakdown": "product"})
    assert [lim.id for lim in guard.check_result(product, guard.ScopeStats(100.0, 5.0, 2.0))] == [
        "L02"
    ]


def test_registry_ids_match_the_data_card():
    assert set(guard.registry()) == {f"L{i:02d}" for i in range(1, 12)} | {
        f"S0{i}" for i in range(1, 6)
    }
