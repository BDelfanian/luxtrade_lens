import pandas as pd
import plotly.graph_objects as go
import pytest

from luxtrade.viz.mapped_charts import create_registry
from luxtrade.viz.registry import ChartPlugin, ChartSpec, MappingRole


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "month": ["2025-02-01", "2025-01-01"],
            "exports": [20.0, 10.0],
            "imports": [8.0, 6.0],
            "country": ["FR", "DE"],
        }
    )


def test_line_maps_wide_values_and_sorts_dates_without_mutation(frame):
    original = frame.copy(deep=True)
    spec = ChartSpec(
        type="line",
        title="Trade",
        mapping={"x": "month", "y": ["exports", "imports"]},
        column_types={"month": "temporal"},
        options={"range_slider": True},
    )
    fig = create_registry().render(frame, spec)
    assert len(fig.data) == 2
    assert list(fig.data[0].y) == [10.0, 20.0]
    assert pd.Timestamp(fig.data[0].x[0]) == pd.Timestamp("2025-01-01")
    assert fig.layout.xaxis.rangeslider.visible
    assert fig.layout.title.text == "Trade"
    pd.testing.assert_frame_equal(frame, original)


def test_line_maps_long_series_and_hover(frame):
    fig = create_registry().render(
        frame,
        ChartSpec(
            type="line",
            mapping={"x": "month", "y": "exports", "color": "country", "hover": ["imports"]},
        ),
    )
    assert {trace.name for trace in fig.data} == {"FR", "DE"}
    assert {trace.name: trace.customdata[0][0] for trace in fig.data} == {"FR": 8.0, "DE": 6.0}


def test_horizontal_bar_keeps_category_and_measure_mapping(frame):
    fig = create_registry().render(
        frame,
        ChartSpec(
            type="bar",
            mapping={"x": "country", "y": ["exports", "imports"]},
            options={"orientation": "h", "barmode": "stack"},
        ),
    )
    assert fig.layout.barmode == "stack"
    assert len(fig.data) == 2
    assert fig.data[0].orientation == "h"
    assert list(fig.data[0].x) == [20.0, 10.0]
    assert list(fig.data[0].y) == ["FR", "DE"]


def test_pie_maps_names_values_and_donut(frame):
    fig = create_registry().render(
        frame,
        ChartSpec(
            type="pie", mapping={"names": "country", "values": "exports"}, options={"hole": 0.4}
        ),
    )
    assert fig.data[0].type == "pie"
    assert list(fig.data[0].labels) == ["FR", "DE"]
    assert list(fig.data[0].values) == [20.0, 10.0]
    assert fig.data[0].hole == 0.4


@pytest.mark.parametrize(
    ("mapping", "options", "message"),
    [
        ({"x": "month"}, {}, "'y'"),
        ({"x": "missing", "y": "exports"}, {}, "was not returned"),
        ({"x": ["month", "country"], "y": "exports"}, {}, "only one"),
        ({"x": "month", "y": ["exports", "exports"]}, {}, "duplicate"),
        ({"x": "month", "y": "country"}, {}, "must be numeric"),
        ({"x": "month", "y": "exports", "unknown": "country"}, {}, "Unsupported"),
        ({"x": "month", "y": "exports"}, {"typo": True}, "Extra inputs"),
        ({"x": "month", "y": ["exports", "imports"], "color": "country"}, {}, "Use one Y"),
    ],
)
def test_invalid_mapping_and_options_are_actionable(frame, mapping, options, message):
    with pytest.raises(ValueError, match=message):
        create_registry().render(frame, ChartSpec(type="line", mapping=mapping, options=options))


@pytest.mark.parametrize("values", [[-1, 5], [0, 0], [None, 1], [float("inf"), 1]])
def test_pie_rejects_invalid_parts(values):
    data = pd.DataFrame({"category": ["A", "B"], "value": values})
    with pytest.raises(ValueError):
        create_registry().render(
            data, ChartSpec(type="pie", mapping={"names": "category", "values": "value"})
        )


def test_explicit_numeric_override_and_invalid_temporal_values(frame):
    frame["exports"] = frame["exports"].astype(str)
    fig = create_registry().render(
        frame,
        ChartSpec(
            type="bar",
            mapping={"x": "country", "y": "exports"},
            column_types={"exports": "numeric"},
            labels={"exports": "Exports in EUR"},
        ),
    )
    assert fig.layout.yaxis.title.text == "Exports in EUR"
    frame["country"] = ["2025-01-01", "2025-02-30"]
    with pytest.raises(ValueError, match="Cannot interpret"):
        create_registry().render(
            frame,
            ChartSpec(
                type="line",
                mapping={"x": "country", "y": "imports"},
                column_types={"country": "temporal"},
            ),
        )


def test_empty_results_still_validate_mappings(frame):
    spec = ChartSpec(type="bar", mapping={"x": "country", "y": "exports"})
    fig = create_registry().render(frame.iloc[:0], spec)
    assert not fig.data
    assert "No rows" in fig.layout.annotations[0].text
    with pytest.raises(ValueError, match="not returned"):
        create_registry().render(
            frame.iloc[:0], spec.model_copy(update={"mapping": {"x": "bad", "y": "exports"}})
        )


def test_new_plugin_roles_are_discovered_and_rendered_without_switches(frame):
    class BoundsChart(ChartPlugin):
        type, label = "bounds", "Forecast bounds"
        roles = (
            MappingRole(name="time", label="Time", required=True),
            MappingRole(name="upper", label="Upper bound", required=True, numeric=True),
        )

        def build(self, data, spec, options):
            return go.Figure(
                go.Scatter(x=data[spec.mapping["time"]], y=data[spec.mapping["upper"]])
            )

    registry = create_registry()
    registry.register(BoundsChart())
    assert registry.describe()[-1]["roles"][1]["name"] == "upper"
    fig = registry.render(
        frame, ChartSpec(type="bounds", mapping={"time": "month", "upper": "exports"})
    )
    assert list(fig.data[0].y) == [20, 10]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(BoundsChart())
