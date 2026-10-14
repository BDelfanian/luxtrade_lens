"""Plotly builders for each data product (SOLUTION_DESIGN §5.6), pure: frames in, figures out.

Colour rules (dataviz reference palette): categorical slots in fixed order, never cycled;
"Other"/"Confidential" in neutral gray; sequential blue for maps and heatmaps; one y-axis.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from luxtrade.analytics.rankings import CONFIDENTIAL, OTHER, UNDISCLOSED
from luxtrade.viz.format import flow_label, fmt_eur, fmt_pct, month_name

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#a3a29c"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FLOW_COLOR = {"export": SERIES[0], "import": SERIES[1], "total": SERIES[2], "balance": SERIES[2]}
TEXT, TEXT_2, GRID = "#0b0b0b", "#52514e", "#e8e7e3"
POOLED = {OTHER, CONFIDENTIAL, UNDISCLOSED}
_MEUR = {"en": "M€", "fr": "M€", "de": "Mio. €"}


def _layout(fig: go.Figure, title: str, y_title: str = "", height: int = 420) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 16, "color": TEXT}},
        font={"color": TEXT_2, "size": 12},
        height=height,
        margin={"l": 8, "r": 8, "t": 56, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0, "title": None},
        hoverlabel={"bgcolor": "white", "font": {"color": TEXT}},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=y_title or None)
    return fig


def _colors(keys: list[str]) -> dict[str, str]:
    slots = iter(SERIES)
    return {k: (NEUTRAL if k in POOLED else next(slots, NEUTRAL)) for k in keys}


def _y(values: pd.Series, measure: str) -> tuple[pd.Series, str, str]:
    """Scale values for the axis: euros → M€, percentages unchanged."""
    if measure in ("growth_yoy", "share"):
        return values, "%", "%"
    if measure == "qty_kg":
        return values / 1e6, "kt", "kt"
    if measure == "unit_value":
        return values, "€/kg", "€/kg"
    return values / 1e6, "M€", "M€"


def _hover(values: pd.Series, measure: str, lang: str) -> list[str]:
    if measure in ("growth_yoy", "share"):
        return [fmt_pct(v, lang) if pd.notna(v) else "–" for v in values]
    if measure in ("value_eur",):
        return [fmt_eur(v, lang) if pd.notna(v) else "–" for v in values]
    return [f"{v:,.1f}" if pd.notna(v) else "–" for v in values]


def bar(main: pd.DataFrame, title: str, lang: str, measure: str = "value_eur") -> go.Figure:
    """Horizontal ranked bars; grouped by flow when both flows are present."""
    flows = [f for f in ("export", "import") if f in set(main["flow"])] or list(
        main["flow"].unique()
    )
    order_flow = "total" if "total" in set(main["flow"]) else flows[0]
    order = main[main["flow"] == order_flow]
    order = pd.concat(
        [
            order[order["kind"] == "item"].sort_values("value", ascending=False),
            order[order["kind"] != "item"],
        ]
    )
    labels = list(order["label"])
    fig = go.Figure()
    for flow in flows:
        part = main[main["flow"] == flow].set_index("label").reindex(labels)
        y, unit, _ = _y(part["value"], measure)
        hover = _hover(part["value"], measure, lang)
        share = [
            fmt_pct(s, lang) if pd.notna(s) else "" for s in part.get("share", [None] * len(part))
        ]
        colors = [NEUTRAL if k in POOLED else FLOW_COLOR.get(flow, SERIES[0]) for k in part["key"]]
        fig.add_bar(
            y=labels,
            x=y,
            orientation="h",
            name=flow_label(flow, lang),
            marker={"color": colors, "cornerradius": 4},
            customdata=list(zip(hover, share, strict=True)),
            hovertemplate="%{y}<br>%{customdata[0]} · %{customdata[1]}<extra>"
            + flow_label(flow, lang)
            + "</extra>",
        )
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08, showlegend=len(flows) > 1)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(
        title=_MEUR.get(lang, "M€") if measure == "value_eur" else None, gridcolor=GRID
    )
    return _layout(fig, title, height=max(320, 28 * len(labels) * max(1, len(flows)) + 90))


def choropleth(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """World map of partner values (sequential blue); undisclosed partners are never mapped."""
    flow = "total" if "total" in set(main["flow"]) else main["flow"].iloc[0]
    part = main[(main["flow"] == flow) & main["iso3"].notna() & (main["kind"] == "item")]
    fig = go.Figure(
        go.Choropleth(
            locations=part["iso3"],
            z=part["value"] / 1e6,
            text=part["label"],
            customdata=[
                f"{fmt_eur(v, lang)} · {fmt_pct(s, lang)}"
                for v, s in zip(part["value"], part["share"], strict=True)
            ],
            colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
            marker_line_color="white",
            marker_line_width=0.5,
            colorbar={"title": _MEUR.get(lang, "M€"), "thickness": 10},
            hovertemplate="%{text}<br>%{customdata}<extra></extra>",
        )
    )
    fig.update_geos(
        showframe=False,
        showcoastlines=False,
        projection_type="natural earth",
        lataxis_range=[-50, 75],
        bgcolor="rgba(0,0,0,0)",
    )
    return _layout(fig, title, height=440)


def treemap(main: pd.DataFrame, title: str, lang: str) -> list[go.Figure]:
    """One treemap per flow; Other and Confidential slices in gray."""
    figs = []
    has_parent = (
        "parent_label" in main.columns
        and main["parent_label"].dropna().astype(str).str.strip().ne("").any()
    )
    for flow in [f for f in ("export", "import", "balance") if f in set(main["flow"])]:
        part = main[main["flow"] == flow]
        if has_parent:
            part = part.copy()
            part["parent_label"] = part["parent_label"].fillna("").astype(str).str.strip()
            part["parent_label"] = part["parent_label"].replace({"": "All Products"})
            fig = px.treemap(
                part,
                path=["parent_label", "label"],
                values=part["value"].clip(lower=0),
            )
            fig.update_traces(
                texttemplate="%{label}<br>%{percentParent:.1%}",
                hovertemplate="%{label}<br>%{value:.1f} M€<extra></extra>",
                textfont={"color": "white"},
            )
        else:
            colors = _colors(list(part["key"]))
            fig = go.Figure(
                go.Treemap(
                    labels=[f"{lab}" for lab in part["label"]],
                    parents=[""] * len(part),
                    values=part["value"].clip(lower=0),
                    marker={"colors": [colors[k] for k in part["key"]]},
                    customdata=[
                        f"{fmt_eur(v, lang)} · {fmt_pct(s, lang)}"
                        for v, s in zip(part["value"], part["share"], strict=True)
                    ],
                    hovertemplate="%{label}<br>%{customdata}<extra></extra>",
                    texttemplate="%{label}<br>%{percentRoot:.1%}",
                    textfont={"color": "white"},
                )
            )
        figs.append(_layout(fig, f"{title} — {flow_label(flow, lang)}", height=420))
    return figs


def lines(
    main: pd.DataFrame,
    title: str,
    lang: str,
    measure: str = "value_eur",
    stacked: bool = False,
    monthly: bool = False,
) -> go.Figure:
    """Lines (or stacked areas) over time; one series per key, or per flow without keys."""
    by = "key" if "key" in main.columns else "flow"
    keys = list(dict.fromkeys(main.sort_values("value", ascending=False)[by]))
    colors = FLOW_COLOR if by == "flow" else _colors(keys)
    names = (
        dict(zip(main["key"], main["label"], strict=False))
        if by == "key"
        else {k: flow_label(k, lang) for k in keys}
    )
    flows = sorted(main["flow"].unique())
    fig = go.Figure()
    for k in keys:
        for flow in flows if by == "key" else [k]:
            part = main[(main[by] == k) & (main["flow"] == flow)].sort_values("period")
            if part.empty:
                continue
            y, unit, _ = _y(part["value"], measure)
            name = names.get(k, k) + (
                f" · {flow_label(flow, lang)}" if by == "key" and len(flows) > 1 else ""
            )
            fig.add_scatter(
                x=part["period"],
                y=y,
                name=name,
                mode="lines",
                line={
                    "width": 2,
                    "color": colors.get(k, NEUTRAL),
                    "dash": "dot"
                    if (by == "key" and flow == "import" and len(flows) > 1)
                    else "solid",
                },
                stackgroup="one" if stacked else None,
                customdata=_hover(part["value"], measure, lang),
                hovertemplate="%{x}<br>%{customdata}<extra>" + name + "</extra>",
            )
    fig.update_layout(hovermode="x unified", showlegend=len(fig.data) > 1)
    if monthly:
        fig.update_xaxes(rangeslider={"visible": True, "thickness": 0.06})
    return _layout(fig, title, y_title=_y(main["value"], measure)[1])


def season(main: pd.DataFrame, title: str, lang: str) -> list[go.Figure]:
    """Raw vs seasonally adjusted lines, plus a month × year heatmap, per flow."""
    figs = []
    for flow in sorted(main["flow"].unique()):
        part = main[main["flow"] == flow].sort_values("period")
        fig = go.Figure()
        fig.add_scatter(
            x=part["period"],
            y=part["observed"] / 1e6,
            name="raw",
            mode="lines",
            line={"width": 1.5, "color": NEUTRAL},
            customdata=_hover(part["observed"], "value_eur", lang),
            hovertemplate="%{x}<br>%{customdata}<extra>raw</extra>",
        )
        fig.add_scatter(
            x=part["period"],
            y=part["adjusted"] / 1e6,
            name="seasonally adjusted",
            mode="lines",
            line={"width": 2, "color": FLOW_COLOR.get(flow, SERIES[0])},
            customdata=_hover(part["adjusted"], "value_eur", lang),
            hovertemplate="%{x}<br>%{customdata}<extra>adjusted</extra>",
        )
        fig.update_layout(hovermode="x unified")
        fig.update_xaxes(rangeslider={"visible": True, "thickness": 0.06})
        figs.append(
            _layout(fig, f"{title} — {flow_label(flow, lang)}", y_title=_MEUR.get(lang, "M€"))
        )

        heat = part.assign(
            year=pd.DatetimeIndex(part["period"]).year, month=pd.DatetimeIndex(part["period"]).month
        )
        grid = heat.pivot_table(index="year", columns="month", values="observed", aggfunc="sum")
        hm = go.Figure(
            go.Heatmap(
                z=grid.to_numpy() / 1e6,
                x=[month_name(m, lang) for m in grid.columns],
                y=grid.index,
                colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
                xgap=2,
                ygap=2,
                colorbar={"title": _MEUR.get(lang, "M€"), "thickness": 10},
                hovertemplate="%{x} %{y}: %{z:,.0f} M€<extra></extra>",
            )
        )
        hm.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
        figs.append(_layout(hm, f"Month × year — {flow_label(flow, lang)}", height=480))
    return figs


def projection(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """History solid, projection dashed, 80 % and 95 % bands."""
    fig = go.Figure()
    for flow in sorted(main["flow"].unique()):
        part = main[main["flow"] == flow].sort_values("period")
        color = FLOW_COLOR.get(flow, SERIES[0])
        hist = part[part["kind"] == "actual"].iloc[-72:]
        proj = part[part["kind"] == "projection"]
        name = flow_label(flow, lang)
        fig.add_scatter(
            x=hist["period"],
            y=hist["value"] / 1e6,
            name=name,
            mode="lines",
            line={"width": 2, "color": color},
            customdata=_hover(hist["value"], "value_eur", lang),
            hovertemplate="%{x}<br>%{customdata}<extra>" + name + "</extra>",
        )
        if proj.empty:
            continue
        for lo, hi, opacity in (("lo95", "hi95", 0.12), ("lo80", "hi80", 0.22)):
            fig.add_scatter(
                x=list(proj["period"]) + list(proj["period"][::-1]),
                y=list(proj[hi] / 1e6) + list(proj[lo][::-1] / 1e6),
                fill="toself",
                fillcolor=color,
                opacity=opacity,
                line={"width": 0},
                hoverinfo="skip",
                showlegend=False,
            )
        fig.add_scatter(
            x=proj["period"],
            y=proj["value"] / 1e6,
            name=f"{name} (projection)",
            mode="lines",
            line={"width": 2, "color": color, "dash": "dash"},
            customdata=[
                f"{fmt_eur(v, lang)} (80 %: {fmt_eur(a, lang)}–{fmt_eur(b, lang)})"
                for v, a, b in zip(proj["value"], proj["lo80"], proj["hi80"], strict=True)
            ],
            hovertemplate="%{x}<br>%{customdata}<extra>projection</extra>",
        )
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, y_title=_MEUR.get(lang, "M€"))


def bench(main: pd.DataFrame, title: str, lang: str) -> list[go.Figure]:
    """Indexed growth lines per reporter (LU first slot) and intra-EU share bars, latest year."""
    reporters = ["LU"] + sorted(r for r in main["reporter"].unique() if r != "LU")
    colors = dict(zip(reporters, SERIES, strict=False))
    fig = go.Figure()
    for r in reporters:
        part = main[main["reporter"] == r].sort_values("period")
        label = part["label"].iloc[0] if len(part) else r
        fig.add_scatter(
            x=part["period"],
            y=part["index"],
            name=label,
            mode="lines+markers",
            line={"width": 3 if r == "LU" else 2, "color": colors[r]},
            marker={"size": 8},
            hovertemplate="%{x}: %{y:.0f}<extra>" + label + "</extra>",
        )
    fig.update_layout(hovermode="x unified")
    figs = [_layout(fig, title, y_title="index")]
    latest = main[main["period"] == main["period"].max()].sort_values(
        "intra_share", ascending=False
    )
    share = go.Figure(
        go.Bar(
            x=latest["intra_share"],
            y=latest["label"],
            orientation="h",
            marker={
                "color": [colors.get(r, NEUTRAL) for r in latest["reporter"]],
                "cornerradius": 4,
            },
            hovertemplate="%{y}: %{x:.1f} %<extra></extra>",
        )
    )
    share.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    figs.append(_layout(share, f"Intra-EU share of trade, {int(main['period'].max())}", height=320))
    return figs


def build_figures(
    kind: str,
    main: pd.DataFrame,
    title: str,
    lang: str = "en",
    measure: str = "value_eur",
    monthly: bool = False,
) -> list[go.Figure]:
    """Dispatch to the builder for ``kind``; table, pivot and KPI are rendered by the app."""
    if main.empty or kind in ("table", "pivot", "kpi"):
        return []
    if kind == "bar":
        return [bar(main, title, lang, measure)]
    if kind == "map":
        return [choropleth(main, title, lang), bar(main, title, lang, measure)]
    if kind == "treemap":
        return treemap(main, title, lang)
    if kind in ("line", "area"):
        return [lines(main, title, lang, measure, stacked=kind == "area", monthly=monthly)]
    if kind == "season":
        return season(main, title, lang)
    if kind == "forecast":
        return [projection(main, title, lang)]
    if kind == "bench":
        return bench(main, title, lang)
    return []
