"""Analysis step: SQL result → standard display frames per intent, using tested analytics tools.

Frame shapes (``Analysis.main``) are the contract for charts, facts and stored run records:
- ranking/composition/drilldown: key, label, flow, value, share, rank, kind[, iso3]
  (measure "change": also base, change, change_pct; value is the last year, base the first)
- time_series: period, [key, label,] flow, value
- pivot: key, label, period, flow, value
- single_value: period, flow, value
- seasonality: period, flow, observed, trend, seasonal_factor, adjusted  (+ extra "profile")
- forecast: period, flow, value, kind, lo80, hi80, lo95, hi95
- benchmark: reporter, label, period, value, index, intra_share
"""

from dataclasses import dataclass, field

import pandas as pd

from luxtrade.agents.guard import make
from luxtrade.agents.spec import (
    MAX_SERIES,
    RANKED_INTENTS,
    SPLIT_BREAKDOWNS,
    Limitation,
    QuerySpec,
)
from luxtrade.analytics import benchmark, forecast, rankings, seasonality, timeseries
from luxtrade.semantic.layer import SemanticLayer

# The part a split question is about comes first (rank 1), whatever its size
SPLIT_SUBJECT = {
    "partner_group": ["EU27", "NON_EU27"],
    "confidentiality": ["CONFIDENTIAL", "DISCLOSED"],
}


@dataclass
class Analysis:
    """Display-ready frames plus what the trace and the guard need to know."""

    main: pd.DataFrame
    extra: dict[str, pd.DataFrame] = field(default_factory=dict)
    methods: list[str] = field(default_factory=list)
    flags: list[Limitation] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    intent_used: str = ""


def _measure(df: pd.DataFrame, spec: QuerySpec) -> pd.Series:
    if spec.measure == "qty_kg":
        return df["qty_kg"].fillna(0.0)
    if spec.measure == "unit_value":
        return df["value_eur_with_qty"] / df["qty_kg"].where(df["qty_kg"] > 0)
    return df["value_eur"]


def _key_kind(spec: QuerySpec) -> str:
    if spec.breakdown == "partner":
        return "partner"
    return "section" if spec.product_level == "SECTION" else "product"


def _label(df: pd.DataFrame, spec: QuerySpec, sem: SemanticLayer) -> pd.DataFrame:
    kind = _key_kind(spec)
    df["label"] = [sem.label(str(k), kind, spec.language) for k in df["key"]]
    if spec.breakdown == "partner":
        df["iso3"] = df["key"].map(lambda k: sem.partners["iso3"].get(k))
    elif spec.breakdown == "product":
        parents = []
        parent_labels = []
        for k in df["key"]:
            code = str(k)
            parent = ""
            if (
                code in sem.products.index
                and sem.products.loc[code, "parent"]
                and sem.products.loc[code, "parent"] != "TOTAL"
            ):
                parent = str(sem.products.loc[code, "parent"])
            elif len(code) > 2 and code[:2] in sem.products.index:
                parent = code[:2]
            parents.append(parent)
            parent_labels.append(sem.label(parent, "product", spec.language) if parent else "")
        df["parent"] = parents
        df["parent_label"] = parent_labels
    return df


def _fold_series(df: pd.DataFrame, max_series: int) -> pd.DataFrame:
    """Keep the largest ``max_series - 1`` keys (by total), pool the rest into OTHER."""
    totals = df.groupby("key")["value"].sum().abs().sort_values(ascending=False)
    if len(totals) <= max_series:
        return df
    keep = set(totals.index[: max_series - 1])
    df = df.assign(key=df["key"].where(df["key"].isin(keep), rankings.OTHER))
    group = [c for c in ("period", "key", "flow") if c in df.columns]
    return df.groupby(group, as_index=False)["value"].sum()


def _entities(main: pd.DataFrame, spec: QuerySpec) -> dict[str, list[str]]:
    if "key" not in main.columns or spec.breakdown in SPLIT_BREAKDOWNS:
        return {}
    items = main[~main["key"].isin([rankings.OTHER, rankings.UNDISCLOSED, rankings.CONFIDENTIAL])]
    if "rank" in items.columns:
        items = items.sort_values("rank")
    codes = list(dict.fromkeys(items["key"].astype(str)))[:10]
    return {"partners" if spec.breakdown == "partner" else "products": codes}


_SHARE_OF = {"partner": "all partners", "product": "all products"}


def _share_of_totals(
    main: pd.DataFrame, totals: pd.DataFrame, on: list[str], share_of: str
) -> tuple[pd.Series, str]:
    """Shares in % of the whole from the total query (``compile_sql.share_base``).

    ``on`` joins a result row to its total: the flow, plus the period for series (both queries
    bucket periods the same way). The "total" flow of a two-flow ranking is both flows together.
    """
    whole = totals.rename(columns={"value_eur": "whole"})[[*on, "whole"]]
    if "period" not in on:
        both = whole.loc[whole["flow"].isin(["export", "import"]), "whole"].sum()
        whole = pd.concat([whole, pd.DataFrame({"flow": ["total"], "whole": [both]})])
    merged = main[on].merge(whole, on=on, how="left")
    share = 100 * main["value"].to_numpy() / merged["whole"].to_numpy()
    method = f"share of the whole flow ({_SHARE_OF.get(share_of, share_of)}), from a total query"
    return pd.Series(share, index=main.index), method


def _split(df: pd.DataFrame, spec: QuerySpec, sem: SemanticLayer) -> Analysis:
    """Two-way split of each flow's total (EU27 vs non-EU27, confidential vs published)."""
    df = df.assign(value=_measure(df, spec)).groupby(["flow", "key"], as_index=False)["value"].sum()
    order = {k: i for i, k in enumerate(SPLIT_SUBJECT[spec.breakdown])}
    df["share"] = 100 * df["value"] / df.groupby("flow")["value"].transform("sum")
    df = df.sort_values(["flow", "key"], key=lambda c: c.map(order) if c.name == "key" else c)
    df["rank"] = df.groupby("flow").cumcount() + 1
    main = _label(df.assign(kind="item").reset_index(drop=True), spec, sem)
    return Analysis(main=main, methods=["share of each flow's total in %"])


def _ranking(
    df: pd.DataFrame,
    spec: QuerySpec,
    sem: SemanticLayer,
    totals: pd.DataFrame | None = None,
    share_of: str = "",
) -> Analysis:
    if spec.breakdown in SPLIT_BREAKDOWNS:
        return _split(df, spec, sem)
    df = df.assign(value=_measure(df, spec))[["key", "flow", "value"]]
    n = spec.top_n or 10
    if spec.flow == "balance":
        bal = timeseries.to_balance(df, ["key"])
        main = bal.reindex(bal["value"].abs().sort_values(ascending=False).index).head(n)
        main = main.assign(share=None, rank=range(1, len(main) + 1), kind="item")
        method = "trade balance = exports − imports per item, top by absolute size"
    else:
        main = rankings.rank_by_flow(df, n)
        method = f"Top-{n} per flow; the rest pooled as 'Other', masked/undisclosed kept separately"
    main = _label(main.reset_index(drop=True), spec, sem)
    a = Analysis(main=main, methods=[method])
    if totals is not None and spec.flow != "balance":
        main["share"], note = _share_of_totals(main, totals, ["flow"], share_of)
        a.methods.append(note)
        a.extra["totals"] = totals.rename(columns={"value_eur": "value"})
    return a


def _change(df: pd.DataFrame, spec: QuerySpec, sem: SemanticLayer) -> Analysis:
    """Largest rises and falls per flow between the first and the last year of the period."""
    y0, y1 = int(spec.period_start[:4]), int(spec.period_end[:4])
    df = df.assign(value=df["value_eur"])[["year", "key", "flow", "value"]]
    if spec.flow == "balance":
        df = timeseries.to_balance(df, ["year", "key"])
    df = df[~df["key"].astype(str).map(rankings.is_hidden_key).astype(bool)]
    wide = df.pivot_table(
        index=["flow", "key"], columns="year", values="value", aggfunc="sum", fill_value=0.0
    )
    both = pd.DataFrame(index=wide.index)
    both["base"], both["value"] = wide.get(y0, 0.0), wide.get(y1, 0.0)
    both = both.reset_index()
    both["change"] = both["value"] - both["base"]
    both["change_pct"] = [
        timeseries.change_pct(b, v) for b, v in zip(both["base"], both["value"], strict=True)
    ]
    n = spec.top_n or 10
    rises, falls = (n + 1) // 2, n // 2
    parts = []
    for _, g in both.groupby("flow"):
        part = pd.concat(
            [
                g[g["change"] > 0].nlargest(rises, "change"),
                g[g["change"] < 0].nsmallest(falls, "change"),
            ]
        ).sort_values("change", ascending=False)
        parts.append(part.assign(rank=range(1, len(part) + 1)))
    main = pd.concat(parts, ignore_index=True) if parts else both.assign(rank=None)
    main = _label(main.assign(kind="item", share=None), spec, sem)
    method = (
        f"change = value {y1} − value {y0} per item; the {rises} largest rises and {falls} "
        "largest falls per flow; masked and undisclosed codes are not ranked"
    )
    return Analysis(main=main, methods=[method])


def _time_series(
    df: pd.DataFrame, spec: QuerySpec, totals: pd.DataFrame | None = None, share_of: str = ""
) -> Analysis:
    df = df.assign(value=_measure(df, spec))
    cols = ["period"] + (["key"] if "key" in df.columns else []) + ["flow", "value"]
    df = df[cols]
    methods = []
    if spec.flow == "balance":
        df = timeseries.to_balance(df, [c for c in cols if c not in ("flow", "value")])
    if "key" in df.columns:
        df = _fold_series(df, MAX_SERIES)
        methods.append(f"at most {MAX_SERIES} series; smaller ones pooled as 'Other'")
    group = [c for c in ("key", "flow") if c in df.columns]
    df = df.sort_values(["period", *group])
    if spec.measure == "growth_yoy":
        lag = 1 if spec.freq == "A" else 12
        df["value"] = df.groupby(group)["value"].transform(lambda s: timeseries.yoy_pct(s, lag))
        methods.append(f"year-on-year change in % (lag {lag})")
    elif spec.measure == "share" and totals is not None:
        df = df.reset_index(drop=True)
        df["value"], note = _share_of_totals(df, totals, ["period", "flow"], share_of)
        methods.append(note)
        return Analysis(
            main=df,
            methods=methods,
            extra={"totals": totals.rename(columns={"value_eur": "value"})},
        )
    elif spec.measure == "share" and "key" in df.columns:
        df["value"] = 100 * df["value"] / df.groupby(["period", "flow"])["value"].transform("sum")
        methods.append("share of the period total in %")
    return Analysis(main=df.reset_index(drop=True), methods=methods)


def _series(df: pd.DataFrame, flow: str) -> pd.Series:
    part = df[df["flow"] == flow]
    return pd.Series(part["value_eur"].to_numpy(), index=pd.DatetimeIndex(part["period"]))


def _seasonality(df: pd.DataFrame, spec: QuerySpec) -> Analysis:
    frames, profiles = [], []
    for flow in sorted(df["flow"].unique()):
        dec = seasonality.stl_decompose(_series(df, flow))
        frames.append(dec.reset_index(names="period").assign(flow=flow))
        profiles.append(seasonality.seasonal_profile(dec).assign(flow=flow))
    return Analysis(
        main=pd.concat(frames, ignore_index=True),
        extra={"profile": pd.concat(profiles, ignore_index=True)},
        methods=[seasonality.method_note()],
    )


def _forecast(df: pd.DataFrame, spec: QuerySpec) -> Analysis:
    frames, methods, flags = [], [], []
    for flow in sorted(df["flow"].unique()):
        y = _series(df, flow)
        reason = forecast.eligibility(y)
        if reason:
            flags.append(
                make("S05", "warn").model_copy(
                    update={"message": f"No projection for {flow}: {reason}."}
                )
            )
            frames.append(
                pd.DataFrame(
                    {"period": y.index, "value": y.to_numpy(), "kind": "actual", "flow": flow}
                )
            )
            continue
        res = forecast.project(y, spec.forecast_horizon or 12)
        frames.append(res.frame.assign(flow=flow))
        methods.append(f"{flow}: {res.method_note()}")
    return Analysis(main=pd.concat(frames, ignore_index=True), methods=methods, flags=flags)


def _benchmark(df: pd.DataFrame, spec: QuerySpec, sem: SemanticLayer) -> Analysis:
    totals = df.groupby(["reporter", "period"], as_index=False)["value_eur"].sum()
    base = int(spec.period_start[:4]) if spec.period_start else int(totals["period"].min())
    totals = totals.rename(columns={"value_eur": "value"})
    totals["index"] = benchmark.index_to_base(totals, base)
    shares = benchmark.intra_share(df)
    main = totals.merge(shares, on=["reporter", "period"], how="left")
    main["label"] = [sem.label(r, "reporter", spec.language) for r in main["reporter"]]
    return Analysis(
        main=main, methods=[f"index {base} = 100 per reporter; intra-EU share = intra / total"]
    )


def analyse(
    spec: QuerySpec,
    df: pd.DataFrame,
    sem: SemanticLayer,
    totals: pd.DataFrame | None = None,
    share_of: str = "",
) -> Analysis:
    """Turn the SQL result into display frames for the spec's intent.

    ``totals`` (from the total query of ``compile_sql.share_base``) makes shares relative to the
    whole flow rather than to the filtered selection; ``share_of`` names the filter left out.
    """
    if spec.intent in RANKED_INTENTS and spec.measure == "change":
        result = _change(df, spec, sem)
    elif spec.intent in RANKED_INTENTS:
        result = _ranking(df, spec, sem, totals, share_of)
    elif spec.intent == "time_series":
        result = _time_series(df, spec, totals, share_of)
        if "key" in result.main.columns:
            result.main = _label(result.main, spec, sem)
    elif spec.intent == "pivot":
        result = _time_series(df, spec, totals, share_of)
        result.main = _label(result.main, spec, sem)
    elif spec.intent == "single_value":
        main = df.assign(value=_measure(df, spec)).rename(columns={"year": "period"})
        result = Analysis(main=main[["period", "flow", "value"]])
    elif spec.intent == "seasonality":
        result = _seasonality(df, spec)
    elif spec.intent == "forecast":
        result = _forecast(df, spec)
    elif spec.intent == "benchmark":
        result = _benchmark(df, spec, sem)
    else:
        raise ValueError(f"unsupported intent {spec.intent}")

    if spec.intent in ("time_series", "seasonality", "forecast") and spec.freq == "M":
        value_col = "observed" if spec.intent == "seasonality" else "value"
        for flow, g in result.main.groupby("flow"):
            if "key" in g.columns:
                continue
            series = g.set_index("period")[value_col].astype(float)
            spikes = timeseries.robust_spikes(series)
            if spikes.any():
                month = pd.Timestamp(spikes[spikes].index[0])
                result.flags.append(make("L11", "warn", value_label=f"{month:%b %Y}, {flow}"))
                break
    result.entities = _entities(result.main, spec)
    result.intent_used = spec.intent
    return result
