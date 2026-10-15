"""Chart contracts and column-role validation, independent of SQL and Streamlit."""

from abc import ABC, abstractmethod
from typing import Literal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pydantic import BaseModel, ConfigDict, Field

ColumnType = Literal["numeric", "temporal", "categorical"]


class ChartSpec(BaseModel):
    """A portable chart definition; mapping keys are declared by its chart plugin."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    title: str = ""
    description: str = ""
    mapping: dict[str, str | list[str]]
    column_types: dict[str, ColumnType] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    height: int = Field(default=420, ge=200, le=1200)


class MappingRole(BaseModel):
    """One chart location, accepting one or several output columns."""

    name: str
    label: str
    required: bool = False
    multiple: bool = False
    numeric: bool = False


class ChartOptions(BaseModel):
    """Base for plugin-specific, validated display options."""

    model_config = ConfigDict(extra="forbid")


class ChartPlugin(ABC):
    """Extend with a type, roles, options model and a pure figure builder."""

    type: str
    label: str
    roles: tuple[MappingRole, ...]
    options_model: type[ChartOptions] = ChartOptions

    @abstractmethod
    def build(self, frame: pd.DataFrame, spec: ChartSpec, options: ChartOptions) -> go.Figure:
        """Build a figure from validated data and mappings."""


def mapped_columns(spec: ChartSpec, role: str) -> list[str]:
    """Return a mapping as a list, including optional unmapped roles."""
    value = spec.mapping.get(role, [])
    return [value] if isinstance(value, str) else value


def plotly_config(figure: go.Figure) -> dict:
    """Keep the hover toolbar from covering an animated chart's playback controls."""
    config = {"displaylogo": False}
    if figure.frames:
        config["displayModeBar"] = False
    return config


class ChartRegistry:
    """Discover and render plugins through a single validation path."""

    def __init__(self) -> None:
        self._plugins: dict[str, ChartPlugin] = {}

    def register(self, plugin: ChartPlugin) -> None:
        """Register a chart once; duplicate type names are programming errors."""
        if plugin.type in self._plugins:
            raise ValueError(f"Chart type already registered: {plugin.type}")
        self._plugins[plugin.type] = plugin

    def get(self, chart_type: str) -> ChartPlugin:
        """Find a chart or report the available types."""
        if chart_type not in self._plugins:
            raise ValueError(
                f"Unknown chart type '{chart_type}'. Choose: {', '.join(self._plugins)}."
            )
        return self._plugins[chart_type]

    def describe(self) -> list[dict]:
        """Expose roles and option schemas for UI controls and API clients."""
        return [
            {
                "type": p.type,
                "label": p.label,
                "roles": [r.model_dump() for r in p.roles],
                "options_schema": p.options_model.model_json_schema(),
            }
            for p in self._plugins.values()
        ]

    def render(self, frame: pd.DataFrame, spec: ChartSpec) -> go.Figure:
        """Validate mappings, convert explicit types, and render without mutating input."""
        plugin = self.get(spec.type)
        options = plugin.options_model.model_validate(spec.options)
        data = _prepare_columns(frame, spec)
        roles = {r.name: r for r in plugin.roles}
        if unknown := spec.mapping.keys() - roles.keys():
            raise ValueError(f"Unsupported mapping roles: {', '.join(sorted(unknown))}.")
        for role in plugin.roles:
            columns = mapped_columns(spec, role.name)
            if role.required and not columns:
                raise ValueError(f"Map at least one column to '{role.name}'.")
            if not role.multiple and len(columns) > 1:
                raise ValueError(f"Role '{role.name}' accepts only one column.")
            if len(columns) != len(set(columns)):
                raise ValueError(f"Role '{role.name}' contains duplicate columns.")
            for column in columns:
                if column not in data.columns:
                    raise ValueError(f"Column '{column}' mapped to '{role.name}' was not returned.")
                if role.numeric:
                    _validate_numeric(data[column], column)
        if data.empty:
            fig = go.Figure()
            fig.add_annotation(text="No rows returned by the query", showarrow=False)
        else:
            fig = plugin.build(data, spec, options)
        fig.update_layout(
            title={"text": spec.title, "x": 0},
            height=spec.height,
            margin={"l": 16, "r": 16, "t": 56, "b": 24} | fig.layout.margin.to_plotly_json(),
            legend_title_text="",
        )
        return fig


def _validate_numeric(series: pd.Series, column: str) -> None:
    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        raise ValueError(f"Column '{column}' must be numeric. Set its column type if needed.")
    if not np.isfinite(series.dropna().astype(float)).all():
        raise ValueError(f"Column '{column}' contains infinite values.")


def _prepare_columns(frame: pd.DataFrame, spec: ChartSpec) -> pd.DataFrame:
    if not frame.columns.is_unique:
        raise ValueError("Query columns must have unique names; use SQL aliases.")
    data = frame.copy()
    for column in spec.column_types.keys() | spec.labels.keys():
        if column not in data.columns:
            raise ValueError(f"Column '{column}' was not returned by the query.")
    for column, kind in spec.column_types.items():
        try:
            if kind == "numeric":
                data[column] = pd.to_numeric(data[column], errors="raise")
            elif kind == "temporal":
                if pd.api.types.is_numeric_dtype(data[column]):
                    raise ValueError("use SQL to construct dates from numeric values")
                data[column] = pd.to_datetime(data[column], errors="raise")
            else:
                data[column] = data[column].astype("string")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Cannot interpret '{column}' as {kind}: {exc}") from exc
    return data
