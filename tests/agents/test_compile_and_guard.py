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


def test_growth_ranking_becomes_a_change_against_the_previous_year(semantic):
    from luxtrade.agents.analyse import analyse

    spec = QuerySpec(intent="ranking", breakdown="product", flow="export", measure="growth_yoy")
    resolved = apply_defaults(spec, semantic.coverage)
    assert resolved.measure == "change"
    assert (resolved.period_start, resolved.period_end) == ("2024", "2025")
    main = analyse(resolved, semantic.query(compile_spec(resolved).sql), semantic).main
    assert 0 < len(main) <= 10 and main["change"].is_monotonic_decreasing
    since = apply_defaults(spec.model_copy(update={"period_start": "2019"}), semantic.coverage)
    assert (since.period_start, since.period_end) == ("2019", "2025")
    top = main.iloc[0]
    ref = semantic.query(
        "SELECT year, sum(value_eur) AS v FROM v_lu_trade WHERE flow = 'export' "
        f"AND hs2 = '{top['key']}' AND year IN (2024, 2025) GROUP BY year ORDER BY year"
    )["v"]
    assert top["change"] == pytest.approx(ref.iloc[1] - ref.iloc[0])


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


def _coverage_until(semantic, latest_complete):
    from dataclasses import replace

    return replace(semantic.coverage, latest_complete_period=latest_complete)


def test_annual_series_never_end_in_an_incomplete_year(semantic):
    from datetime import date

    cov = _coverage_until(semantic, date(2026, 6, 1))  # Jan–Jun 2026 published
    spec = QuerySpec(
        intent="time_series", partners=["CN"], period_start="2015", period_end="2026-06"
    )
    resolved = apply_defaults(spec, cov)
    assert resolved.freq == "A" and resolved.period_end == "2025"
    assert any("2026 is incomplete" in a for a in resolved.assumptions)


def test_incomplete_year_is_kept_when_asked_alone_or_monthly(semantic):
    from datetime import date

    cov = _coverage_until(semantic, date(2026, 6, 1))
    alone = apply_defaults(QuerySpec(intent="single_value", period_start="2026"), cov)
    monthly = apply_defaults(
        QuerySpec(intent="time_series", freq="M", period_start="2025-01", period_end="2026-06"),
        cov,
    )
    assert alone.period_end == "2026" and monthly.period_end == "2026-06"


def test_eu_split_shares_add_up_and_match_reference_sql(semantic):
    spec = apply_defaults(
        QuerySpec(intent="composition", breakdown="partner_group", flow="import"),
        semantic.coverage,
    )
    df = semantic.query(check_sql(compile_spec(spec).sql))
    assert set(df["key"]) == {"EU27", "NON_EU27"}
    year = int(spec.period_start)
    ref = semantic.query(
        "SELECT sum(value_eur) FILTER (WHERE partner_is_eu27_2020 OR (partner_is_special "
        "AND trade_type = 'intra')) AS eu FROM v_lu_trade "
        f"WHERE flow = 'import' AND year = {year}"
    )
    eu = df.set_index("key").at["EU27", "value_eur"]
    assert eu == pytest.approx(ref["eu"].iloc[0])


def test_confidential_split_uses_the_cn8_detail(semantic):
    spec = apply_defaults(
        QuerySpec(
            intent="composition", breakdown="confidentiality", products=["27"], flow="import"
        ),
        semantic.coverage,
    )
    compiled = compile_spec(spec)
    assert compiled.view == "v_lu_trade"
    df = semantic.query(check_sql(compiled.sql)).set_index("key")
    ref = semantic.query(
        "SELECT sum(value_eur) AS v FROM v_lu_trade WHERE is_confidential AND hs2 = '27' "
        f"AND flow = 'import' AND year = {int(spec.period_start)}"
    )
    assert df.at["CONFIDENTIAL", "value_eur"] == pytest.approx(ref["v"].iloc[0])


def test_benchmark_countries_named_as_partners_become_reporters(semantic):
    spec = QuerySpec(
        intent="benchmark", partners=["BE", "NL"], compare_reporters=["BE"], flow="export"
    )
    resolved = apply_defaults(spec, semantic.coverage)
    assert resolved.partners == [] and resolved.compare_reporters == ["BE", "NL"]
    assert not guard.is_blocked(guard.check_spec(resolved, semantic.coverage))


def test_pivot_over_a_few_named_partners_becomes_a_time_series(semantic):
    spec = QuerySpec(intent="pivot", breakdown="partner", partners=["DE", "FR"], flow="export")
    assert apply_defaults(spec, semantic.coverage).intent == "time_series"
    table = spec.model_copy(update={"view": "table"})
    assert apply_defaults(table, semantic.coverage).intent == "pivot"  # asked for a table
