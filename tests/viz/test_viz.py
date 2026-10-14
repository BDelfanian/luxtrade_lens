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
    ],
    ids=lambda s: s.intent,
)
def test_figures_build_for_real_answers(semantic, spec):
    resolved = apply_defaults(spec, semantic.coverage)
    a = analyse(resolved, semantic.query(compile_spec(resolved).sql), semantic)
    kind = choose_view(resolved, a.main, iso3_count=8)
    figs = build_figures(kind, a.main, "title", "fr", monthly=resolved.freq == "M")
    assert figs and all(len(f.data) > 0 for f in figs)
    assert len(set(a.main.get("key", pd.Series(dtype=str)))) <= 30
