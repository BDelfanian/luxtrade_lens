"""Plotly builders for each data product (SOLUTION_DESIGN §5.6), pure: frames in, figures out.

Colour rules (dataviz reference palette): categorical slots in fixed order, never cycled;
"Other"/"Confidential" in neutral gray; sequential blue for maps and heatmaps; one y-axis.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from luxtrade.analytics.rankings import CONFIDENTIAL, OTHER, UNDISCLOSED
from luxtrade.viz.format import (
    flow_label,
    fmt_eur,
    fmt_measure,
    fmt_number,
    fmt_pct,
    fmt_period,
    month_name,
)

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#a3a29c"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FLOW_COLOR = {"export": SERIES[0], "import": SERIES[1], "total": SERIES[2], "balance": SERIES[2]}
TEXT, TEXT_2, GRID = "#0b0b0b", "#52514e", "#e8e7e3"
POOLED = {OTHER, CONFIDENTIAL, UNDISCLOSED}
_MEUR = {"en": "M€", "fr": "M€", "de": "Mio. €"}


def _layout(fig: go.Figure, title: str, y_title: str = "", height: int = 420) -> go.Figure:
    legend_items = sum(
        1 for d in fig.data if getattr(d, "showlegend", False) is not False and d.name
    )
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 16, "color": TEXT}},
        font={"color": TEXT_2, "size": 12},
        height=height,
        margin={"l": 8, "r": 8, "t": 56 if legend_items <= 4 else 96, "b": 8},
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
    if measure == "index":
        return values, "index", "index"
    if measure == "hhi":
        return values, "HHI", "HHI"
    return values / 1e6, "M€", "M€"


def _hover(values: pd.Series, measure: str, lang: str) -> list[str]:
    if measure in ("growth_yoy", "share"):
        return [fmt_pct(v, lang) if pd.notna(v) else "–" for v in values]
    if measure in ("value_eur",):
        return [fmt_eur(v, lang) if pd.notna(v) else "–" for v in values]
    if measure == "hhi":
        return [f"HHI {fmt_number(v, 0, lang)}" if pd.notna(v) else "–" for v in values]
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
    balance = flow == "balance"  # deficits and surpluses: diverging colours around zero
    if balance:
        limit = float(part["value"].abs().max() / 1e6) if not part.empty else 1.0
        scale = {
            "colorscale": [[0, SERIES[7]], [0.5, "#f7f6f2"], [1, SERIES[0]]],
            "zmid": 0,
            "zmin": -limit,
            "zmax": limit,
        }
    else:
        scale = {"colorscale": [[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)]}
    fig = go.Figure(
        go.Choropleth(
            locations=part["iso3"],
            z=part["value"] / 1e6,
            text=part["label"],
            customdata=[
                fmt_eur(v, lang) if balance else f"{fmt_eur(v, lang)} · {fmt_pct(s, lang)}"
                for v, s in zip(part["value"], part["share"], strict=True)
            ],
            **scale,
            marker_line_color="white",
            marker_line_width=0.5,
            colorbar={"title": _MEUR.get(lang, "M€"), "thickness": 10},
            hovertemplate="%{text}<br>%{customdata}<extra></extra>",
        )
    )
    # zoom to the mapped partners; light land around them for context
    fig.update_geos(
        fitbounds="locations",
        showframe=False,
        showcoastlines=False,
        showland=True,
        landcolor="#f1f0ec",
        showcountries=True,
        countrycolor="white",
        projection_type="natural earth",
        bgcolor="rgba(0,0,0,0)",
    )
    return _layout(fig, title, height=440)


def treemap(main: pd.DataFrame, title: str, lang: str) -> list[go.Figure]:
    """One treemap per flow; Other and Confidential slices in gray."""
    figs = []
    colors = _colors(list(dict.fromkeys(main.sort_values("value", ascending=False)["key"])))
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
                mode="lines+markers" if measure == "hhi" else "lines",
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
    if measure == "hhi":
        _hhi_levels(fig, lang)
        fig.update_yaxes(rangemode="tozero")
        fig.update_xaxes(tickmode="array", tickvals=sorted(main["period"].unique()))
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


def _short(label: str, size: int = 40) -> str:
    return label if len(label) <= size else label[: size - 1].rstrip() + "…"


def with_events(fig: go.Figure, events: pd.DataFrame) -> go.Figure:
    """Dotted reference lines for well-known shocks: reading aids, not data."""
    for i, row in enumerate(events.itertuples()):
        fig.add_vline(x=row.year, line={"color": NEUTRAL, "width": 1, "dash": "dot"})
        fig.add_annotation(
            x=row.year,
            y=1 - 0.07 * (i % 2),
            yref="paper",
            yanchor="top",
            xanchor="left",
            xshift=3,
            text=row.label,
            showarrow=False,
            font={"size": 11, "color": TEXT_2},
        )
    return fig


def change_bar(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """Diverging bars of a change in value: rises in blue, falls in red, zero as the midpoint."""
    part = main.sort_values("change", ascending=False)
    fig = go.Figure(
        go.Bar(
            x=part["change"] / 1e6,
            y=[_short(lab) for lab in part["label"]],
            orientation="h",
            marker={
                "color": [SERIES[0] if v >= 0 else SERIES[7] for v in part["change"]],
                "cornerradius": 4,
            },
            customdata=[
                [lab, ("+" if v >= 0 else "") + fmt_eur(v, lang)]
                for lab, v in zip(part["label"], part["change"], strict=True)
            ],
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
        )
    )
    fig = _layout(fig, title, height=max(300, 34 * len(part) + 90))
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(
        title=_MEUR.get(lang, "M€"),
        showgrid=True,
        gridcolor=GRID,
        zeroline=True,
        zerolinecolor=TEXT_2,
        zerolinewidth=1,
    )
    return fig


def _flows(main: pd.DataFrame) -> list[str]:
    present = set(main["flow"])
    return [f for f in ("export", "import", "total", "balance") if f in present] or sorted(present)


def stacked_bars(main: pd.DataFrame, title: str, lang: str, measure: str = "share") -> go.Figure:
    """One stacked horizontal bar per period, a colour per key; exports and imports side by side."""
    flows = _flows(main)
    periods = sorted(main["period"].unique())
    ticks = [fmt_period(p, lang) for p in periods]
    ranked = list(dict.fromkeys(main.sort_values("value", ascending=False)["key"]))
    keys = [k for k in ranked if k not in POOLED] + [k for k in ranked if k in POOLED]
    colors = _colors(keys)
    names = dict(zip(main["key"], main.get("label", main["key"]), strict=False))
    fig = make_subplots(
        rows=1,
        cols=len(flows),
        shared_yaxes=True,
        horizontal_spacing=0.06,
        subplot_titles=[flow_label(f, lang) for f in flows] if len(flows) > 1 else None,
    )
    in_legend: set[str] = set()
    for col, flow in enumerate(flows, start=1):
        part = main[main["flow"] == flow]
        for k in keys:
            seg = part[part["key"] == k].groupby("period")["value"].sum().reindex(periods)
            if seg.isna().all():
                continue
            x, unit, _ = _y(seg, measure)
            name = _short(str(names.get(k, k)), 44)
            fig.add_bar(
                x=x,
                y=ticks,
                orientation="h",
                name=name,
                legendgroup=k,
                showlegend=k not in in_legend,
                marker={"color": colors[k], "line": {"color": "white", "width": 1}},
                customdata=_hover(seg, measure, lang),
                hovertemplate="%{y} · %{customdata}<extra>" + name + "</extra>",
                row=1,
                col=col,
            )
            in_legend.add(k)
    fig.update_layout(barmode="stack", bargap=0.3)
    fig = _layout(fig, title, height=max(320, 34 * len(periods) + 150))
    fig.update_layout(legend={"y": -0.08, "yanchor": "top"}, margin={"t": 72})
    fig.update_xaxes(title=_y(main["value"], measure)[1], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(
        categoryorder="array", categoryarray=ticks, autorange="reversed", gridcolor="rgba(0,0,0,0)"
    )
    return fig


def heatmap(
    main: pd.DataFrame, title: str, lang: str, measure: str = "value_eur"
) -> list[go.Figure]:
    """Rows × periods per flow: item × period with keys, otherwise year × month."""
    figs = []
    for flow in _flows(main):
        part = main[main["flow"] == flow]
        if "key" in part.columns:
            rows = part["label"] if "label" in part.columns else part["key"]
            grid = part.assign(row=rows).pivot_table(
                index="row", columns="period", values="value", aggfunc="sum"
            )
            grid = grid.loc[grid.abs().sum(axis=1).sort_values(ascending=False).index]
            x = [fmt_period(p, lang) for p in grid.columns]
            y = [_short(str(r)) for r in grid.index]
        else:
            when = pd.DatetimeIndex(part["period"])
            grid = part.assign(year=when.year, month=when.month).pivot_table(
                index="year", columns="month", values="value", aggfunc="sum"
            )
            x, y = [month_name(m, lang) for m in grid.columns], list(grid.index)
        z, unit, _ = _y(grid, measure)
        if (grid < 0).any().any():  # balances and growth rates: diverging around zero
            scale = {"colorscale": [[0, SERIES[7]], [0.5, "#f7f6f2"], [1, SERIES[0]]], "zmid": 0}
        else:
            scale = {
                "colorscale": [[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)]
            }
        fig = go.Figure(
            go.Heatmap(
                z=z.to_numpy(),
                x=x,
                y=y,
                xgap=2,
                ygap=2,
                colorbar={"title": unit, "thickness": 10},
                hovertemplate="%{y} · %{x}: %{z:,.1f} " + unit + "<extra></extra>",
                **scale,
            )
        )
        fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
        name = f"{title} — {flow_label(flow, lang)}" if len(_flows(main)) > 1 else title
        figs.append(_layout(fig, name, height=max(320, 26 * len(y) + 130)))
    return figs


def change_bars(main: pd.DataFrame, title: str, lang: str) -> list[go.Figure]:
    """Diverging change bars, one chart per flow."""
    flows = _flows(main)
    return [
        change_bar(
            main[main["flow"] == f],
            f"{title} — {flow_label(f, lang)}" if len(flows) > 1 else title,
            lang,
        )
        for f in flows
    ]


def overview_figures(
    key: str, frames: dict[str, pd.DataFrame], titles: list[str], lang: str = "en"
) -> list[go.Figure]:
    """Figures for one overview panel (agents/overview.py), first figure = the main one."""
    main = frames["main"]
    if main.empty:
        return []
    if key == "trend":
        return [with_events(lines(main, titles[0], lang), frames["events"])]
    if key == "partners":
        # bars: exports and imports side by side, ordered by total trade
        return [choropleth(main, titles[0], lang), bar(main, titles[1], lang)]
    if key == "products":
        figs = treemap(main, titles[0], lang)
        change = frames.get("change")
        if change is not None and not change.empty:
            figs.append(change_bar(change, titles[1], lang))
        return figs
    if key == "season":
        return season(main, titles[0], lang)
    if key == "peers":
        return bench(main, titles[0], lang)
    return []


HHI_LEVELS = {  # US Merger Guidelines (2023), as on the Overview card
    1_000: {"en": "moderately concentrated", "fr": "concentration modérée", "de": "mäßig"},
    1_800: {"en": "highly concentrated", "fr": "forte concentration", "de": "hoch"},
}


def _hhi_levels(fig: go.Figure, lang: str) -> None:
    """Dashed reference lines where concentration becomes moderate and high."""
    for level, names in HHI_LEVELS.items():
        fig.add_hline(y=level, line={"color": NEUTRAL, "width": 1, "dash": "dash"})
        fig.add_annotation(
            x=0,
            xref="paper",
            y=level,
            yanchor="bottom",
            xanchor="left",
            text=f"{names.get(lang, names['en'])} (> {fmt_number(level, 0, lang)})",
            showarrow=False,
            font={"size": 11, "color": TEXT_2},
        )


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
    if kind == "change":
        return change_bars(main, title, lang)
    if kind == "stacked":
        return [stacked_bars(main, title, lang, measure)]
    if kind == "heatmap":
        return heatmap(main, title, lang, measure)
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


# --- key findings (agents/findings.py) --------------------------------------------------------


def hhi_lines(main: pd.DataFrame, refs: pd.DataFrame, title: str) -> go.Figure:
    """Concentration over time: colour = product or partner, dash = flow, reference levels."""
    color = {"product": SERIES[0], "partner": SERIES[1]}
    fig = go.Figure()
    for (dim, flow), part in main.groupby(["dim", "flow"], sort=True):
        part = part.sort_values("year")
        fig.add_scatter(
            x=part["year"],
            y=part["hhi"],
            name=part["label"].iloc[0],
            mode="lines+markers",
            line={
                "width": 2.5,
                "color": color[dim],
                "dash": "solid" if flow == "export" else "dot",
            },
            hovertemplate="%{x}: HHI %{y:,.0f}<extra>" + part["label"].iloc[0] + "</extra>",
        )
    for row in refs.itertuples():
        fig.add_hline(y=row.level, line={"color": NEUTRAL, "width": 1, "dash": "dash"})
        fig.add_annotation(
            x=1,
            xref="paper",
            y=row.level,
            yanchor="bottom",
            xanchor="right",
            text=f"{row.label} ({row.level:,})",
            showarrow=False,
            font={"size": 11, "color": TEXT_2},
        )
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(tickmode="array", tickvals=sorted(main["year"].unique()))
    return _layout(fig, title, y_title="HHI")


def then_now_bars(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """Share of each chapter in two years, side by side: light = then, dark = now."""
    years = sorted(main["year"].unique())
    order = main[main["year"] == years[-1]].sort_values("share", ascending=False)["hs2"].tolist()
    order += [c for c in main["hs2"].unique() if c not in order]
    labels = dict(zip(main["hs2"], main["label"], strict=False))
    fig = go.Figure()
    for y, shade in zip(years, (SEQUENTIAL[2], SEQUENTIAL[5]), strict=False):
        part = main[main["year"] == y].set_index("hs2").reindex(order)
        fig.add_bar(
            x=part["share"],
            y=[_short(labels.get(c, c)) for c in order],
            name=str(y),
            orientation="h",
            marker={"color": shade, "cornerradius": 4},
            customdata=[fmt_pct(v, lang) if pd.notna(v) else "–" for v in part["share"]],
            hovertemplate="%{y}<br>%{customdata}<extra>" + str(y) + "</extra>",
        )
    fig = _layout(fig, title, height=max(320, 30 * len(order) + 120))
    fig.update_layout(barmode="group")
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(title="%", showgrid=True, gridcolor=GRID)
    return fig


def change_heatmap(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """Chapters × crises: change in exports, red for falls, blue for rises, value in each cell."""
    grid = main.pivot_table(index="label", columns="episode", values="change", sort=False)
    grid = grid.loc[grid.mean(axis=1).sort_values().index]
    episodes = list(dict.fromkeys(main["episode"]))
    grid = grid[episodes]
    text = [
        [fmt_pct(v, lang, decimals=0, signed=True) if pd.notna(v) else "" for v in row]
        for row in grid.to_numpy()
    ]
    limit = max(10.0, float(grid.abs().max().max()))
    fig = go.Figure(
        go.Heatmap(
            z=grid.to_numpy(),
            x=episodes,
            y=[_short(lab) for lab in grid.index],
            text=text,
            texttemplate="%{text}",
            zmin=-limit,
            zmax=limit,
            colorscale=[[0, SERIES[7]], [0.5, "#f7f6f2"], [1, SERIES[0]]],
            showscale=False,
            hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
            xgap=2,
            ygap=2,
        )
    )
    fig = _layout(fig, title, height=max(320, 32 * len(grid) + 130))
    fig.update_layout(margin={"t": 96})  # room for the crisis names between title and grid
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(side="top")
    return fig


def share_bars(main: pd.DataFrame, title: str, lang: str) -> go.Figure:
    """Shares of a whole as horizontal bars; pooled rows (other, undisclosed) in gray."""
    fig = go.Figure(
        go.Bar(
            x=main["share"],
            y=main["label"],
            orientation="h",
            marker={
                "color": [NEUTRAL if k in POOLED else SERIES[0] for k in main["key"]],
                "cornerradius": 4,
            },
            text=[fmt_pct(v, lang) for v in main["share"]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>",
        )
    )
    fig = _layout(fig, title, height=max(280, 34 * len(main) + 100))
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(title="%", showgrid=False, showticklabels=False)
    return fig


def finding_figures(
    key: str, frames: dict[str, pd.DataFrame], titles: list[str], lang: str = "en"
) -> list[go.Figure]:
    """Figures for one key finding (agents/findings.py), in the order of its chart titles."""
    main = frames["main"]
    if main.empty or not titles:
        return []
    if key == "diversification":
        return [
            hhi_lines(main, frames["refs"], titles[0]),
            then_now_bars(frames["chapters"], titles[1], lang),
        ]
    if key == "shocks":
        figs = [with_events(lines(main, titles[0], lang), frames["events"])]
        if not frames["heat"].empty:
            figs.append(change_heatmap(frames["heat"], titles[1], lang))
        if not frames["fuel"].empty:
            figs.append(share_bars(frames["fuel"], titles[2], lang))
        return figs
    if key == "europe":
        figs = [lines(main, titles[0], lang, measure="share")]
        if not frames["watch"].empty:
            figs.append(lines(frames["watch"], titles[1], lang, measure="share"))
        return figs
    if key == "prices":
        uv = lines(main, titles[0], lang, measure="unit_value")
        uv.update_yaxes(type="log")
        figs = [uv]
        if not frames["fuel_index"].empty:
            idx = lines(frames["fuel_index"], titles[1], lang, measure="index")
            idx.add_hline(y=100, line={"color": NEUTRAL, "width": 1, "dash": "dash"})
            figs.append(idx)
        return figs
    if key == "composition":
        return [composition_bars(main, lang, titles[0], height=520)]
    return []


# --- key findings: one compact chart per card (the headline made visible) ----------------------

_EU_LABEL = {"en": "EU27 countries", "fr": "Pays de l'UE27", "de": "EU27-Länder"}
HERO_HEIGHT = 360  # every card chart is the same height, so the cards line up


def _hero_layout(fig: go.Figure, height: int = HERO_HEIGHT, right: int = 8) -> go.Figure:
    """Compact, title-less layout for a card: the card's headline is the title."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": right, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": TEXT_2, "size": 13},
        hoverlabel={"bgcolor": "white", "font": {"color": TEXT}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0, "title": None},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="", fixedrange=True)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, fixedrange=True)
    return fig


def _end_label(fig: go.Figure, x: object, y: float, name: str, value: str, color: str) -> None:
    """Direct label at the end of a line: the series name, then its last value."""
    fig.add_annotation(
        x=x,
        y=y,
        xanchor="left",
        xshift=10,
        text=f"<b>{value}</b><br>{name}",
        showarrow=False,
        align="left",
        font={"size": 12, "color": TEXT},
        bordercolor=color,
        borderwidth=0,
    )


def hero_hhi(main: pd.DataFrame, refs: pd.DataFrame, lang: str) -> go.Figure:
    """Two lines that part ways: export concentration by product vs imports by partner."""
    fig = go.Figure()
    high = refs.loc[refs["level"].idxmax()] if not refs.empty else None
    if high is not None:  # the line that counts as highly concentrated
        fig.add_hline(y=high["level"], line={"color": NEUTRAL, "width": 1, "dash": "dash"})
        fig.add_annotation(
            x=0,
            xref="paper",
            y=high["level"],
            yanchor="bottom",
            xanchor="left",
            text=f"{high['label']} (> {fmt_number(high['level'], 0, lang)})",
            showarrow=False,
            font={"size": 11, "color": TEXT_2},
        )
    for dim, flow, color in (("product", "export", SERIES[0]), ("partner", "import", SERIES[1])):
        part = main[(main["dim"] == dim) & (main["flow"] == flow)].sort_values("year")
        if part.empty:
            continue
        name = part["label"].iloc[0]
        fig.add_scatter(
            x=part["year"],
            y=part["hhi"],
            name=name,
            mode="lines+markers",
            line={"width": 3, "color": color},
            marker={"size": 8, "color": color},
            hovertemplate="%{x}: HHI %{y:,.0f}<extra>" + name + "</extra>",
        )
        first, last = part.iloc[0], part.iloc[-1]
        fig.add_annotation(
            x=first["year"],
            y=first["hhi"],
            yshift=14 if flow == "import" else -14,
            text=fmt_number(first["hhi"], 0, lang),
            showarrow=False,
            font={"size": 12, "color": TEXT_2},
        )
        _end_label(fig, last["year"], last["hhi"], name, fmt_number(last["hhi"], 0, lang), color)
    fig.update_layout(showlegend=False, hovermode="x unified")
    years = sorted(main["year"].unique())
    fig.update_xaxes(tickmode="array", tickvals=years, range=[years[0] - 1, years[-1] + 1])
    fig.update_yaxes(title="HHI", rangemode="tozero")
    return _hero_layout(fig, right=190)


def hero_crisis(episodes: pd.DataFrame, lang: str) -> go.Figure:
    """The weak spot against all exports in each crisis: red bars fall further than gray ones."""
    order = list(dict.fromkeys(episodes["episode"]))
    series = list(dict.fromkeys(episodes["series"]))
    fig = go.Figure()
    for name, color in zip(series, (SERIES[7], NEUTRAL), strict=False):
        part = episodes[episodes["series"] == name].set_index("episode").reindex(order)
        fig.add_bar(
            x=order,
            y=part["change"],
            name=name,
            marker={"color": color, "cornerradius": 4},
            text=[fmt_pct(v, lang, decimals=0, signed=True) for v in part["change"]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>%{text}<extra>" + name + "</extra>",
        )
    low = float(episodes["change"].min())
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(
        ticksuffix=" %", range=[min(low * 1.25, -10), 8], zeroline=True, zerolinecolor=TEXT_2
    )
    return _hero_layout(fig)


def hero_europe(main: pd.DataFrame, watch: pd.DataFrame, lang: str) -> go.Figure:
    """The EU share of imports climbs while China's falls, on one percentage axis."""
    fig = go.Figure()
    eu = main[main["flow"] == "import"].sort_values("period")
    china = watch[watch["key"] == "CN-import"].sort_values("period")
    for part, name, color in (
        (eu, _EU_LABEL.get(lang, _EU_LABEL["en"]), SERIES[0]),
        (china, china["label"].iloc[0] if not china.empty else "", SERIES[1]),
    ):
        if part.empty:
            continue
        fig.add_scatter(
            x=part["period"],
            y=part["value"],
            name=name,
            mode="lines",
            line={"width": 3, "color": color},
            hovertemplate="%{x}: %{y:.1f} %<extra>" + name + "</extra>",
        )
        last = part.iloc[-1]
        _end_label(fig, last["period"], last["value"], name, fmt_pct(last["value"], lang), color)
    fig.update_layout(showlegend=False, hovermode="x unified")
    fig.update_xaxes(range=[eu["period"].min() - 0.5, eu["period"].max() + 0.5])
    fig.update_yaxes(range=[0, 100], ticksuffix=" %")
    return _hero_layout(fig, right=170)


def hero_kilo(main: pd.DataFrame, lang: str) -> go.Figure:
    """Value of a kilo imported from outside vs inside the EU, latest year."""
    year = main["period"].max()
    part = main[(main["period"] == year) & main["key"].isin(["extra-import", "intra-import"])]
    part = part.sort_values("value")
    fig = go.Figure(
        go.Bar(
            x=part["value"],
            y=[f"{lab}  " for lab in part["label"]],
            orientation="h",
            marker={
                "color": [SERIES[0] if k == "extra-import" else NEUTRAL for k in part["key"]],
                "cornerradius": 4,
            },
            text=[f"{fmt_number(v, 2, lang)} €/kg" for v in part["value"]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra>" + str(year) + "</extra>",
        )
    )
    fig.update_layout(showlegend=False, bargap=0.45)
    fig.update_xaxes(showticklabels=False, range=[0, float(part["value"].max()) * 1.3])
    fig.update_yaxes(showgrid=False)
    return _hero_layout(fig)


# Shades of one chapter's hue: its 1st, 2nd and 3rd heading, then the rest of the chapter
_SHADES = {1: 1.0, 2: 0.7, 3: 0.45, 0: 0.18}
_FLOW_TITLE = {
    "export": {"en": "Exports", "fr": "Exportations", "de": "Exporte"},
    "import": {"en": "Imports", "fr": "Importations", "de": "Importe"},
}
_OF_FLOW = {"en": "% of {flow}", "fr": "% des {flow}", "de": "% der {flow}"}


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def composition_bars(
    main: pd.DataFrame, lang: str = "en", title: str = "", height: int = HERO_HEIGHT
) -> go.Figure:
    """Exports and imports side by side: one stacked bar per year, coloured by chapter.

    A hue per chapter (the same in both panels) and a shade per heading: darkest = the largest
    heading in the latest year, then the next two, palest = the rest of the chapter.
    """
    years = sorted(main["year"].unique())
    flows = [f for f in ("export", "import") if f in set(main["flow"])]
    chapters = list(dict.fromkeys(main["hs2"]))  # same chapter, same colour in both panels
    hue = {c: SERIES[i % len(SERIES)] for i, c in enumerate(chapters)}
    fig = make_subplots(
        rows=1,
        cols=len(flows),
        shared_yaxes=True,
        horizontal_spacing=0.06,
        subplot_titles=[_FLOW_TITLE[f].get(lang, _FLOW_TITLE[f]["en"]) for f in flows],
    )
    in_legend = set()
    for col, flow in enumerate(flows, start=1):
        part = main[main["flow"] == flow]
        for hs2 in dict.fromkeys(part["hs2"]):
            chapter = part[part["hs2"] == hs2]
            for slot in (1, 2, 3, 0):
                seg = chapter[chapter["slot"] == slot].set_index("year").reindex(years)
                if seg["share"].isna().all():
                    continue
                name = _short(chapter["chapter"].iloc[0], 44)
                fig.add_bar(
                    x=seg["share"],
                    y=[str(y) for y in years],
                    orientation="h",
                    name=name,
                    legendgroup=hs2,
                    showlegend=slot == 1 and hs2 not in in_legend,
                    marker={
                        "color": _rgba(hue[hs2], _SHADES[slot]),
                        "line": {"color": "white", "width": 1},
                    },
                    text=[
                        (seg["hs4"].iloc[0] if slot else "") if v >= 2.0 else ""
                        for v in seg["share"].fillna(0)
                    ],
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont={"color": "white" if slot in (1, 2) else TEXT, "size": 11},
                    customdata=[
                        [_short(lab, 60), fmt_pct(v, lang)]
                        for lab, v in zip(
                            seg["label"].fillna(""), seg["share"].fillna(0), strict=True
                        )
                    ],
                    hovertemplate="%{y} · %{customdata[0]}<br>%{customdata[1]}<extra>"
                    + name
                    + "</extra>",
                    row=1,
                    col=col,
                )
                if slot == 1:
                    in_legend.add(hs2)
        fig.update_xaxes(
            ticksuffix=" %",
            title=_OF_FLOW.get(lang, _OF_FLOW["en"]).format(flow=flow_label(flow, lang)),
            showgrid=True,
            gridcolor=GRID,
            row=1,
            col=col,
        )
    fig.update_layout(barmode="stack", bargap=0.3)
    fig.update_yaxes(
        categoryorder="array", categoryarray=[str(y) for y in years], autorange="reversed"
    )
    fig.update_annotations(font={"size": 14, "color": TEXT})
    if title:
        fig = _layout(fig, title, height=height)
        fig.update_layout(legend={"y": -0.18, "yanchor": "top"}, margin={"b": 70})
        return fig
    fig = _hero_layout(fig, height=height)
    fig.update_layout(legend={"orientation": "h", "y": -0.16, "yanchor": "top", "x": 0})
    fig.update_layout(margin={"t": 30, "b": 60})
    return fig


def hero_figure(key: str, frames: dict[str, pd.DataFrame], lang: str = "en") -> go.Figure | None:
    """The compact chart on a key finding's card (None for the conclusion)."""
    main = frames["main"]
    if key == "diversification" and not main.empty:
        return hero_hhi(main, frames["refs"], lang)
    if key == "shocks" and not frames.get("episodes", pd.DataFrame()).empty:
        return hero_crisis(frames["episodes"], lang)
    if key == "europe" and not main.empty:
        return hero_europe(main, frames["watch"], lang)
    if key == "prices" and not main.empty:
        return hero_kilo(main, lang)
    if key == "composition" and not main.empty:
        return composition_bars(main, lang, height=430)
    return None


def evidence_bars(
    rows: pd.DataFrame, kind: str, lang: str, titles: list[str] | None = None
) -> go.Figure:
    """A scenario's evidence chart (agents/evidence.py), in the style of the Overview cards.

    ``change``: one group of bars per period, the items the answer is about in colour and the
    whole flow in gray (like the crisis card). ``share``: one group per item, a bar per year.
    ``titles``: the figure's panel titles, where it has panels.
    """
    if kind in ("concentration", "series"):
        return evidence_panels(rows, kind, lang)
    if kind == "projection":
        return evidence_projection(rows, lang)
    if kind == "benchmark":
        return evidence_benchmark(rows, lang, titles)
    groups = list(dict.fromkeys(rows["group"]))
    series = list(dict.fromkeys(rows["series"]))
    fig = go.Figure()
    if kind == "change":
        colors = [SERIES[7], SERIES[0], SERIES[6]][: len(series) - 1] + [NEUTRAL]
    else:  # older years lighter, the latest year darkest
        colors = [SEQUENTIAL[min(2 + 3 * i, 6)] for i in range(len(series))]
    for name, color in zip(series, colors, strict=False):
        part = rows[rows["series"] == name].set_index("group").reindex(groups)
        labels = [
            fmt_pct(v, lang, decimals=0 if kind == "change" else 1, signed=kind == "change")
            if pd.notna(v)
            else ""
            for v in part["value"]
        ]
        fig.add_bar(
            x=[_short(g, 28) for g in groups],
            y=part["value"],
            name=name,
            marker={"color": color, "cornerradius": 4},
            text=labels,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>%{text}<extra>" + name + "</extra>",
        )
    low, high = float(rows["value"].min()), float(rows["value"].max())
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    if kind == "change":
        fig.update_yaxes(
            ticksuffix=" %",
            range=[min(low * 1.3, -10), max(high * 1.3, 8)],
            zeroline=True,
            zerolinecolor=TEXT_2,
        )
    else:
        fig.update_yaxes(ticksuffix=" %", range=[0, high * 1.25])
    return _hero_layout(fig, height=380)


def evidence_hhi(rows: pd.DataFrame, lang: str) -> go.Figure:
    """Concentration over time as small multiples, on one shared scale.

    Exports and imports in rows, by product and by partner in columns (blue and orange, as on
    the Overview card), with the levels where concentration becomes moderate and high.
    """
    return evidence_panels(rows, "concentration", lang)


def evidence_panels(rows: pd.DataFrame, kind: str, lang: str) -> go.Figure:
    """Small multiples of yearly lines: a panel per series, first and last values labelled.

    ``concentration``: HHI on one shared scale with the 1,000 and 1,800 levels, coloured by
    dimension. ``series``: shares or values, each panel on its own scale (a 4 % share next to
    an 87 % one would be flat on a shared one).
    """
    hhi = kind == "concentration"
    panels = list(dict.fromkeys(rows["series"]))
    cols = 2 if len(panels) > 1 else 1
    n_rows = (len(panels) + cols - 1) // cols
    fig = make_subplots(
        rows=n_rows,
        cols=cols,
        subplot_titles=panels,
        shared_yaxes=hhi,
        shared_xaxes=hhi,  # yearly series each span their own years
        vertical_spacing=0.16,
        horizontal_spacing=0.06 if hhi else 0.1,
    )
    for i, panel in enumerate(panels):
        part = rows[rows["series"] == panel].sort_values("group")
        if hhi:
            color = SERIES[1] if part["dim"].iloc[0] == "partner" else SERIES[0]
        else:
            color = SERIES[i % len(SERIES)]
        unit = "hhi" if hhi else str(part["unit"].iloc[0])

        def show(v: float, unit: str = unit) -> str:
            return fmt_number(v, 0, lang) if unit == "hhi" else fmt_measure(v, unit, lang)

        r, c = i // cols + 1, i % cols + 1
        fig.add_scatter(
            x=part["group"],
            y=part["value"],
            mode="lines+markers+text" if len(part) <= 8 else "lines+text",
            line={"width": 3, "color": color},
            marker={"size": 7, "color": color},
            text=[show(v) if j in (0, len(part) - 1) else "" for j, v in enumerate(part["value"])],
            # the first label to the right of its point, the last to the left: inside the panel
            textposition=[
                "top right" if j == 0 else "top left" if j == len(part) - 1 else "top center"
                for j in range(len(part))
            ],
            textfont={"size": 12, "color": TEXT},
            customdata=[show(v) for v in part["value"]],
            hovertemplate="%{x}: %{customdata}<extra>" + panel + "</extra>",
            showlegend=False,
            row=r,
            col=c,
        )
        if hhi:
            for level in HHI_LEVELS:
                fig.add_hline(
                    y=level,
                    line={"color": NEUTRAL, "width": 1, "dash": "dash" if level > 1_000 else "dot"},
                    row=r,
                    col=c,
                )
        else:
            fig.update_yaxes(
                range=[0, float(part["value"].max()) * 1.25],
                ticksuffix=" %" if unit == "share" else "",
                row=r,
                col=c,
            )
    fig.update_annotations(font={"size": 13, "color": TEXT})  # the panel titles
    for i, panel in enumerate(panels):
        years = sorted(rows.loc[rows["series"] == panel, "group"].unique())
        if hhi:
            years = sorted(rows["group"].unique())
        pad = 1.5 if len(years) <= 8 else 0.8
        ticks = years if len(years) <= 8 else [y for y in years if y % 5 == 0]
        fig.update_xaxes(
            tickmode="array",
            tickvals=ticks,
            range=[years[0] - pad, years[-1] + pad],
            row=i // cols + 1,
            col=i % cols + 1,
        )
    if hhi:
        fig.update_yaxes(range=[0, max(float(rows["value"].max()) * 1.18, 2_100)])
        high = HHI_LEVELS[1_800]
        fig.add_annotation(
            x=0,
            xref="paper",
            y=0,
            yref="paper",
            yanchor="top",
            yshift=-30,  # below the year labels, whatever the height
            showarrow=False,
            xanchor="left",
            text=f"- - {high.get(lang, high['en'])} (> {fmt_number(1_800, 0, lang)})   "
            f"····· {HHI_LEVELS[1_000].get(lang, 'moderately concentrated')} "
            f"(> {fmt_number(1_000, 0, lang)})",
            font={"size": 11, "color": TEXT_2},
        )
    fig = _hero_layout(fig, height=300 * n_rows + 80)
    fig.update_layout(margin={"l": 8, "r": 8, "t": 30, "b": 52 if hhi else 16})
    return fig


def evidence_projection(rows: pd.DataFrame, lang: str) -> go.Figure:
    """Observed months, then the projection (dashed) in its 80 % band, a panel per flow (M€)."""
    panels = list(dict.fromkeys(rows["series"]))
    fig = make_subplots(rows=1, cols=len(panels), subplot_titles=panels, horizontal_spacing=0.08)
    for i, panel in enumerate(panels, start=1):
        part = rows[rows["series"] == panel].sort_values("group")
        seen, ahead = part[part["kind"] == "actual"], part[part["kind"] == "projection"]
        color = SERIES[i - 1]
        joined = pd.concat([seen.tail(1), ahead])  # the dashed line starts at the last month seen
        fig.add_scatter(
            x=ahead["group"],
            y=ahead["hi80"] / 1e6,
            mode="lines",
            line={"width": 0},
            hoverinfo="skip",
            showlegend=False,
            row=1,
            col=i,
        )
        fig.add_scatter(
            x=ahead["group"],
            y=ahead["lo80"] / 1e6,
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor=_rgba(color, 0.18),
            hoverinfo="skip",
            showlegend=False,
            row=1,
            col=i,
        )
        for frame, dash, name in ((seen, "solid", "observed"), (joined, "dash", "projected")):
            fig.add_scatter(
                x=frame["group"],
                y=frame["value"] / 1e6,
                mode="lines",
                line={"width": 2.2, "color": color, "dash": dash},
                customdata=[fmt_eur(v, lang) for v in frame["value"]],
                hovertemplate="%{customdata}<extra>" + f"{panel}, {name}" + "</extra>",
                showlegend=False,
                row=1,
                col=i,
            )
        if not seen.empty:
            fig.add_vline(
                x=float(seen["group"].max()),
                line={"color": NEUTRAL, "width": 1, "dash": "dot"},
                row=1,
                col=i,
            )
        years = sorted({int(g) for g in part["group"]})
        fig.update_xaxes(tickmode="array", tickvals=[y for y in years if y % 2 == 0], row=1, col=i)
        fig.update_yaxes(title="M€" if i == 1 else None, row=1, col=i)  # spans the data
    fig.update_annotations(font={"size": 13, "color": TEXT})
    fig = _hero_layout(fig, height=380)
    fig.update_layout(margin={"l": 8, "r": 8, "t": 30, "b": 16})
    return fig


_PEERS = [*SERIES[1:7], NEUTRAL]  # no red: in the share panel red means "fell"


def evidence_benchmark(rows: pd.DataFrame, lang: str, titles: list[str] | None = None) -> go.Figure:
    """Each country's index (Luxembourg in bold) and its intra-EU share at both ends."""
    index, intra = rows[rows["panel"] == "index"], rows[rows["panel"] == "intra"]
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=titles or ["", ""],
        column_widths=[0.56, 0.44],
        horizontal_spacing=0.14,
    )
    countries = list(dict.fromkeys(index.sort_values("reporter")["series"]))
    lu = next(iter(index.loc[index["reporter"] == "LU", "series"]), None)
    for k, name in enumerate([c for c in countries if c != lu] + ([lu] if lu else [])):
        part = index[index["series"] == name].sort_values("group")
        own = name == lu
        fig.add_scatter(
            x=part["group"],
            y=part["value"],
            mode="lines+markers" if own else "lines",
            name=name,
            line={"width": 3.2 if own else 1.6, "color": SERIES[0] if own else _PEERS[k % 7]},
            marker={"size": 6},
            hovertemplate="%{y:.0f}<extra>" + name + "</extra>",
            row=1,
            col=1,
        )
    fig.add_hline(y=100, line={"color": NEUTRAL, "width": 1, "dash": "dot"}, row=1, col=1)
    years = sorted(intra["series"].unique())
    order = list(dict.fromkeys(intra["group"]))[::-1]  # the highest share on top
    for name in order:
        pair = intra[intra["group"] == name].set_index("series")["value"]
        a, b = float(pair.get(years[0])), float(pair.get(years[-1]))
        own = intra.loc[intra["group"] == name, "reporter"].iloc[0] == "LU"
        color = SERIES[0] if own else ("#1baf7a" if b > a else "#e34948")
        fig.add_scatter(
            x=[a, b],
            y=[name, name],
            mode="lines+markers",
            line={"color": color, "width": 3 if own else 2},
            marker={
                "size": [8, 11],
                "color": ["white", color],
                "line": {"color": color, "width": 2},
            },
            customdata=[fmt_pct(a, lang), fmt_pct(b, lang)],
            hovertemplate="%{customdata}<extra>" + name + "</extra>",
            showlegend=False,
            row=1,
            col=2,
        )
    fig.update_yaxes(title="index", row=1, col=1)
    fig.update_xaxes(ticksuffix=" %", row=1, col=2)
    fig.update_annotations(font={"size": 13, "color": TEXT})
    fig = _hero_layout(fig, height=460)
    fig.update_layout(  # the legend under the panels, clear of their titles
        margin={"l": 8, "r": 8, "t": 30, "b": 70},
        legend={"orientation": "h", "x": 0, "y": -0.12, "yanchor": "top"},
    )
    return fig
