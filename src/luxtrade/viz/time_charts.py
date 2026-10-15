"""Time-series plugins: ranked snapshots with playback and stacked area trends."""

from html import escape
from typing import Literal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pydantic import Field

from luxtrade.config import DASHBOARD_MAX_ANIMATION_PERIODS
from luxtrade.viz.charts import NEUTRAL, SERIES
from luxtrade.viz.registry import ChartOptions, ChartPlugin, ChartSpec, MappingRole, mapped_columns


class RankingOptions(ChartOptions):
    """Number of ranked categories and playback speed."""

    top_n: int = Field(default=10, ge=1, le=30)
    frame_duration: int = Field(default=700, ge=100, le=3000, title="Playback step (ms)")
    fixed_scale: bool = True
    sort_order: Literal["descending", "ascending"] = "descending"
    category_width: int = Field(default=180, ge=80, le=400, title="Category label width (pixels)")


def _time_label(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.isoformat()
    return str(value)


def _value_range(values: pd.Series) -> list[float]:
    low, high = min(0.0, float(values.min())), max(0.0, float(values.max()))
    padding = (high - low or 1) * 0.12
    return [low - padding if low < 0 else 0, high + padding]


class RankingBarChart(ChartPlugin):
    """Horizontal top-N bars re-ranked at every time-slider position."""

    type, label = "bar_race", "Animated ranking bars"
    roles = (
        MappingRole(name="time", label="Time / slider", required=True),
        MappingRole(name="category", label="Categories", required=True),
        MappingRole(name="value", label="Ranking value", required=True, numeric=True),
        MappingRole(name="hover", label="Hover details", multiple=True),
    )
    options_model = RankingOptions

    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: RankingOptions) -> go.Figure:
        """Use independently sorted frames, stable category colors and a shared value scale."""
        time, category, value = (
            mapped_columns(spec, role)[0] for role in ("time", "category", "value")
        )
        if frame[[time, category, value]].isna().any().any():
            raise ValueError("Ranking time, category and value columns must not contain nulls.")
        frame = frame.copy()
        frame[category] = frame[category].astype(str)
        if frame.duplicated([time, category]).any():
            raise ValueError("Aggregate SQL to one row per time and category for ranking bars.")
        try:
            periods = frame[time].drop_duplicates().sort_values().tolist()
        except TypeError as exc:
            raise ValueError(
                "Time values must have a consistent type; set a column type override."
            ) from exc
        if len(periods) > DASHBOARD_MAX_ANIMATION_PERIODS:
            raise ValueError(
                f"Ranking bars support up to {DASHBOARD_MAX_ANIMATION_PERIODS} periods. "
                "Filter the query or aggregate to quarters or years."
            )
        categories = (
            frame.groupby(category)[value]
            .max()
            .sort_values(ascending=False, kind="stable")
            .index.tolist()
        )
        colors = {
            name: SERIES[i] if i < len(SERIES) else NEUTRAL for i, name in enumerate(categories)
        }
        hover = mapped_columns(spec, "hover")
        hover_template = (
            "%{y}<br>"
            + escape(spec.labels.get(value, value))
            + ": %{x:,.2f}<br>"
            + escape(spec.labels.get(time, time))
            + ": %{customdata[0]}"
            + "".join(
                f"<br>{escape(spec.labels.get(column, column))}: %{{customdata[{i + 1}]}}"
                for i, column in enumerate(hover)
            )
            + "<extra></extra>"
        )
        frames = []
        for i, period in enumerate(periods):
            part = (
                frame[frame[time] == period]
                .sort_values([value, category], ascending=[False, True], kind="stable")
                .head(options.top_n)
            )
            if options.sort_order == "ascending":
                part = part.sort_values([value, category], ascending=[True, True], kind="stable")
            names = part[category].tolist()
            customdata = [
                [_time_label(period), *row]
                for row in part[hover].itertuples(index=False, name=None)
            ]
            if not hover:
                customdata = [[_time_label(period)] for _ in names]
            trace = go.Bar(
                x=part[value].tolist(),
                y=names,
                ids=names,
                orientation="h",
                marker={"color": [colors[name] for name in names], "cornerradius": 5},
                texttemplate="%{x:,.3s}",
                textposition="auto",
                cliponaxis=False,
                customdata=customdata,
                hovertemplate=hover_template,
            )
            frames.append(
                go.Frame(
                    name=f"period-{i}",
                    data=[trace],
                    traces=[0],
                    layout=go.Layout(
                        yaxis={
                            "categoryorder": "array",
                            "categoryarray": names,
                            "tickmode": "array",
                            "tickvals": names,
                            "ticktext": [escape(name) for name in names],
                            "automargin": False,
                            "range": [len(names) - 0.5, -0.5],
                            "autorange": False,
                        },
                        xaxis={
                            "range": _value_range(
                                frame[value] if options.fixed_scale else part[value]
                            ),
                            "autorange": False,
                        },
                    ),
                )
            )
        fig = go.Figure(data=frames[0].data, frames=frames, layout=frames[0].layout)
        fig.update_layout(
            showlegend=False,
            bargap=0.24,
            margin={"l": options.category_width + 20, "r": 16, "b": 120, "autoexpand": False},
            meta={
                "category_labels": {
                    "width": options.category_width,
                    "names": sorted({name for snapshot in frames for name in snapshot.data[0].y}),
                }
            },
            xaxis_title=spec.labels.get(value, value),
            yaxis_title=None,
            yaxis_type="category",
            yaxis_automargin=False,
            yaxis_tickfont_size=12,
            xaxis_automargin=False,
            sliders=[
                {
                    "active": 0,
                    "x": 0,
                    "len": 1,
                    "y": -0.08,
                    "currentvalue": {
                        "prefix": spec.labels.get(time, time) + ": ",
                        "font": {"size": 15},
                    },
                    "pad": {"t": 26},
                    "steps": [
                        {
                            "label": _time_label(period),
                            "method": "animate",
                            "args": [
                                [f"period-{i}"],
                                {
                                    "mode": "immediate",
                                    "frame": {"duration": 0, "redraw": True},
                                    "transition": {"duration": 0},
                                },
                            ],
                        }
                        for i, period in enumerate(periods)
                    ],
                }
            ],
            updatemenus=[
                {
                    "type": "buttons",
                    "direction": "left",
                    "showactive": False,
                    "x": 1,
                    "xanchor": "right",
                    "y": 1.16,
                    "buttons": [
                        {
                            "label": "▶ Play",
                            "method": "animate",
                            "args": [
                                None,
                                {
                                    "fromcurrent": True,
                                    "mode": "immediate",
                                    "frame": {"duration": options.frame_duration, "redraw": True},
                                    "transition": {"duration": 0},
                                },
                            ],
                        },
                        {
                            "label": "❚❚ Pause",
                            "method": "animate",
                            "args": [
                                [None],
                                {
                                    "mode": "immediate",
                                    "frame": {"duration": 0, "redraw": True},
                                    "transition": {"duration": 0},
                                },
                            ],
                        },
                    ],
                }
            ],
        )
        return fig


class AreaOptions(ChartOptions):
    """Time-range navigation and optional percentage shares."""

    range_slider: bool = True
    normalize: bool = False


class AreaChart(ChartPlugin):
    """Stacked area trends showing absolute values or percentage composition."""

    type, label = "area", "Stacked area over time"
    options_model = AreaOptions
    roles = (
        MappingRole(name="x", label="Time axis", required=True),
        MappingRole(name="y", label="Values (Y axis)", required=True, multiple=True, numeric=True),
        MappingRole(name="color", label="Series / color"),
        MappingRole(name="hover", label="Hover details", multiple=True),
    )

    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: AreaOptions) -> go.Figure:
        """Sort time, validate stacking inputs, and preserve query values in hover data."""
        time = mapped_columns(spec, "x")[0]
        values, color = mapped_columns(spec, "y"), mapped_columns(spec, "color")
        if len(values) > 1 and color:
            raise ValueError(
                "Use one Y column with a series column, or multiple Y columns without it."
            )
        if frame[[time, *color, *values]].isna().any().any():
            raise ValueError("Area time, series and value columns must not contain nulls.")
        if (frame[values] < 0).any().any():
            raise ValueError(
                "Stacked areas require nonnegative values; use a line chart for balances."
            )
        if frame.duplicated([time, *color]).any():
            raise ValueError(
                "Area charts need one row per time and series; map a series or aggregate SQL."
            )
        ordered = frame.sort_values(time, kind="stable")
        fig = px.area(
            ordered,
            x=time,
            y=values if len(values) > 1 else values[0],
            color=color[0] if color else None,
            hover_data=mapped_columns(spec, "hover"),
            labels=spec.labels,
            color_discrete_sequence=SERIES,
            groupnorm="percent" if options.normalize else None,
        )
        fig.update_xaxes(rangeslider_visible=options.range_slider)
        fig.update_layout(hovermode="x unified")
        if options.normalize:
            _retain_area_values(fig, ordered, values, color)
            fig.update_yaxes(title="Share (%)", range=[0, 100])
        return fig


def _retain_area_values(
    figure: go.Figure, frame: pd.DataFrame, values: list[str], color: list[str]
) -> None:
    # Plotly normalizes its calculated Y values. Retain the query value explicitly
    # so a tooltip labelled in euros never displays a percentage as a euro amount.
    parts = (
        [part for _, part in frame.groupby(color[0], sort=False, observed=True)]
        if color
        else [frame] * len(values)
    )
    for i, (trace, part) in enumerate(zip(figure.data, parts, strict=True)):
        raw = part[values[0] if color else values[i]].tolist()
        existing = trace.customdata
        width = len(existing[0]) if existing is not None and len(existing) else 0
        trace.customdata = [
            [*(existing[j] if existing is not None else []), value] for j, value in enumerate(raw)
        ]
        trace.hovertemplate = trace.hovertemplate.replace("%{y}", f"%{{customdata[{width}]}}")
        trace.hovertemplate = trace.hovertemplate.replace("<extra>", "<br>Share: %{y:.1f}%<extra>")
