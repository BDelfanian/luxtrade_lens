import pandas as pd
import pytest

from luxtrade.agents.analyse import analyse
from luxtrade.agents.compile_sql import compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.spec import QuerySpec
from luxtrade.viz.charts import build_figures
from luxtrade.viz.format import fmt_eur, fmt_pct
from luxtrade.viz.selector import choose_view


@pytest.mark.parametrize(
    ("value", "lang", "expected"),
    [
        (16_253_900_000, "en", "16.25 bn €"),
        (16_253_900_000, "fr", "16,25 Md €"),
        (16_253_900_000, "de", "16,25 Mrd. €"),
        (967_000_000, "en", "967.0 M€"),
    ],
)
def test_euro_formatting(value, lang, expected):
    assert fmt_eur(value, lang) == expected


def test_signed_percent():
    assert (
        fmt_pct(-5.25, "de", signed=True) == "−5,2 %"
        or fmt_pct(-5.25, "de", signed=True) == "−5,3 %"
    )


def _spec(**kw):
    return QuerySpec(**kw)


@pytest.mark.parametrize(
    ("spec", "kind"),
    [
        (_spec(intent="single_value"), "kpi"),
        (_spec(intent="ranking", breakdown="product"), "bar"),
        (_spec(intent="composition", breakdown="product"), "treemap"),
        (_spec(intent="drilldown"), "treemap"),
        (_spec(intent="time_series"), "line"),
        (_spec(intent="time_series", measure="share"), "area"),
        (_spec(intent="time_series", measure="share", freq="A"), "stacked"),
        (_spec(intent="pivot"), "pivot"),
        (_spec(intent="seasonality"), "season"),
        (_spec(intent="forecast"), "forecast"),
        (_spec(intent="benchmark"), "bench"),
    ],
)
def test_selector_rules(spec, kind):
    assert choose_view(spec, pd.DataFrame({"key": [], "period": []})) == kind


def test_map_needs_enough_countries_and_few_undisclosed():
    spec = _spec(intent="ranking", breakdown="partner")
    frame = pd.DataFrame({"key": []})
    assert choose_view(spec, frame, iso3_count=8, undisclosed_pct=2.0) == "map"
    assert choose_view(spec, frame, iso3_count=3) == "bar"
    assert choose_view(spec, frame, iso3_count=8, undisclosed_pct=60.0) == "bar"


def test_change_ranking_uses_diverging_bars_only():
    spec = _spec(intent="ranking", breakdown="product", measure="change")
    frame = pd.DataFrame({"key": [], "change": []})
    assert choose_view(spec, frame) == "change"
    assert choose_view(spec.model_copy(update={"view": "treemap"}), frame) == "change"


def test_long_share_series_stay_stacked_areas():
    spec = _spec(intent="time_series", measure="share", freq="A")
    frame = pd.DataFrame({"key": ["01"] * 20, "period": range(2005, 2025)})
    assert choose_view(spec, frame) == "area"


def test_requested_view_wins_only_if_compatible():
    spec = _spec(intent="ranking", breakdown="product", view="map")
    assert choose_view(spec, pd.DataFrame({"key": []})) == "bar"
    assert (
        choose_view(spec.model_copy(update={"view": "table"}), pd.DataFrame({"key": []})) == "table"
    )


@pytest.mark.parametrize(
    "spec",
    [
        _spec(intent="ranking", breakdown="partner"),
        _spec(intent="drilldown", partners=["DE"]),
        _spec(intent="time_series", breakdown="partner", flow="export"),
        _spec(intent="seasonality", flow="export"),
        _spec(intent="forecast", flow="export"),
        _spec(intent="benchmark", flow="export"),
        _spec(intent="ranking", breakdown="product", measure="growth_yoy", period_start="2019"),
        _spec(intent="ranking", breakdown="partner", measure="change", flow="balance"),
        _spec(
            intent="time_series",
            breakdown="product",
            measure="share",
            freq="A",
            period_start="2018",
            period_end="2025",
        ),
        _spec(intent="time_series", breakdown="partner", flow="export", view="heatmap"),
        _spec(intent="time_series", flow="import", freq="M", view="heatmap"),
    ],
    ids=lambda s: f"{s.intent}-{s.measure}-{s.view}",
)
def test_figures_build_for_real_answers(semantic, spec):
    resolved = apply_defaults(spec, semantic.coverage)
    a = analyse(resolved, semantic.query(compile_spec(resolved).sql), semantic)
    kind = choose_view(resolved, a.main, iso3_count=8)
    figs = build_figures(kind, a.main, "title", "fr", monthly=resolved.freq == "M")
    assert figs and all(len(f.data) > 0 for f in figs)
    assert len(set(a.main.get("key", pd.Series(dtype=str)))) <= 30


def test_render_hierarchical_treemap_with_parent_labels():
    from luxtrade.viz.charts import treemap

    df = pd.DataFrame(
        {
            "flow": ["export", "export"],
            "parent_label": ["Machinery", "Machinery"],
            "label": ["Turbines", "Boilers"],
            "key": ["8406", "8402"],
            "value": [100.0, 200.0],
            "share": [0.33, 0.67],
            "kind": ["item", "item"],
        }
    )
    figs = treemap(df, "Hierarchical Test", "en")
    assert len(figs) == 1
    fig = figs[0]
    assert fig.data[0].type == "treemap"
    labels = list(fig.data[0].labels)
    assert "Machinery" in labels or any("Machinery" in str(x) for x in fig.data[0].ids)


def test_missing_values_format_as_a_dash():
    from luxtrade.viz.format import fmt_eur, fmt_number, fmt_pct

    assert fmt_pct(None) == fmt_eur(None) == fmt_number(float("nan"), 1, "en") == "–"
    assert fmt_pct(12.345, "fr") == "12,3 %"


def test_month_names_short_and_full():
    from luxtrade.viz.format import month_name

    assert month_name(3, "en") == "Mar" and month_name(3, "en", full=True) == "March"
    assert month_name(8, "fr", full=True) == "août" and month_name(3, "de", full=True) == "März"


def test_a_trade_balance_ranking_draws_in_every_view():
    """Balance rows have no share (a share of a balance means nothing): no view may crash."""
    from luxtrade.viz.charts import build_figures

    main = pd.DataFrame(
        {
            "key": ["BE", "DE", "US"],
            "value": [-19.0e9, -7.1e9, 1.2e9],
            "flow": "balance",
            "share": [None, None, None],
            "rank": [1, 2, 3],
            "kind": "item",
            "label": ["Belgium", "Germany", "United States"],
            "iso3": ["BEL", "DEU", "USA"],
        }
    )
    for kind in ("map", "bar", "treemap"):
        assert build_figures(kind, main, "Trade balance by partner", "en"), kind
    choropleth = build_figures("map", main, "Trade balance by partner", "en")[0]
    assert choropleth.data[0].zmid == 0  # deficits and surpluses on either side of zero


def test_a_refined_question_describes_the_new_request():
    from luxtrade.agents.spec import QuerySpec
    from luxtrade.app.components import refined_question

    spec = QuerySpec(
        intent="ranking",
        breakdown="partner",
        flow="balance",
        period_start="2014",
        period_end="2018",
        top_n=5,
    )
    assert refined_question(spec) == "Refined: trade balance by partner, 2014–2018, top 5"
