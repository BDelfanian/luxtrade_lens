"""Built-in dashboard charts. Add plugins here without changing API routes or UI controls."""

from typing import Literal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pydantic import Field

from luxtrade.viz.charts import SERIES
from luxtrade.viz.registry import (
    ChartOptions,
    ChartPlugin,
    ChartRegistry,
    ChartSpec,
    MappingRole,
    mapped_columns,
)
from luxtrade.viz.time_charts import AreaChart, RankingBarChart

CARTESIAN_ROLES = (
    MappingRole(name="x", label="X axis", required=True),
    MappingRole(name="y", label="Values (Y axis)", required=True, multiple=True, numeric=True),
    MappingRole(name="color", label="Series / color"),
    MappingRole(name="hover", label="Hover details", multiple=True),
)


class LineOptions(ChartOptions):
    """Line and time-axis display settings."""

    markers: bool = True
    sort_x: bool = True
    range_slider: bool = False


class BarOptions(ChartOptions):
    """Bar orientation and grouping settings."""

    orientation: Literal["v", "h"] = "v"
    barmode: Literal["group", "stack", "relative"] = "group"


class PieOptions(ChartOptions):
    """Optional donut opening, expressed as a fraction."""

    hole: float = Field(default=0, ge=0, le=0.8)


def _cartesian_args(spec: ChartSpec) -> dict:
    values = mapped_columns(spec, "y")
    color = mapped_columns(spec, "color")
    # Express handles wide measures or a long-format grouping column. Combining both
    # obscures the measure legend, so require the query to unpivot that combination.
    if len(values) > 1 and color:
        raise ValueError("Use one Y column with a series column, or multiple Y columns without it.")
    return {
        "x": mapped_columns(spec, "x")[0],
        "y": values if len(values) > 1 else values[0],
        "color": color[0] if color else None,
        "hover_data": mapped_columns(spec, "hover"),
        "labels": spec.labels,
        "color_discrete_sequence": SERIES,
    }


class LineChart(ChartPlugin):
    """Lines over any X column, including explicitly typed temporal columns."""

    type, label = "line", "Line chart"
    roles = CARTESIAN_ROLES
    options_model = LineOptions

    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: LineOptions) -> go.Figure:
        """Sort within series and optionally expose a time range slider."""
        if options.sort_x:
            frame = frame.sort_values(mapped_columns(spec, "x")[0], kind="stable")
        fig = px.line(frame, **_cartesian_args(spec), markers=options.markers)
        fig.update_xaxes(rangeslider_visible=options.range_slider)
        return fig


class BarChart(ChartPlugin):
    """Grouped or stacked bars; X always maps the category, Y always maps measures."""

    type, label = "bar", "Bar chart"
    roles = CARTESIAN_ROLES
    options_model = BarOptions

    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: BarOptions) -> go.Figure:
        """Swap physical axes for horizontal bars while keeping mapping semantics stable."""
        args = _cartesian_args(spec)
        if options.orientation == "h":
            args["x"], args["y"] = args["y"], args["x"]
        return px.bar(frame, **args, orientation=options.orientation, barmode=options.barmode)


class PieChart(ChartPlugin):
    """Part-to-whole charts with explicit labels and nonnegative values."""

    type, label = "pie", "Pie chart"
    roles = (
        MappingRole(name="names", label="Slice labels", required=True),
        MappingRole(name="values", label="Slice values", required=True, numeric=True),
        MappingRole(name="hover", label="Hover details", multiple=True),
    )
    options_model = PieOptions

    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: PieOptions) -> go.Figure:
        """Reject invalid parts instead of silently dropping or clipping values."""
        values = frame[mapped_columns(spec, "values")[0]]
        if values.isna().any() or (values < 0).any() or values.sum() <= 0:
            raise ValueError("Pie values must be nonnegative, non-null, and sum to more than zero.")
        return px.pie(
            frame,
            names=mapped_columns(spec, "names")[0],
            values=mapped_columns(spec, "values")[0],
            hover_data=mapped_columns(spec, "hover"),
            labels=spec.labels,
            hole=options.hole,
            color_discrete_sequence=SERIES,
        )


def create_registry() -> ChartRegistry:
    """Construct the standard registry; callers may register additional plugins."""
    registry = ChartRegistry()
    for plugin in (LineChart(), BarChart(), PieChart(), RankingBarChart(), AreaChart()):
        registry.register(plugin)
    return registry


CHARTS = create_registry()
