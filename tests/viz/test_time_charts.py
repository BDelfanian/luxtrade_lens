import pandas as pd
import plotly.graph_objects as go
import pytest

from luxtrade.config import DASHBOARD_MAX_ANIMATION_PERIODS
from luxtrade.viz.mapped_charts import create_registry
from luxtrade.viz.registry import ChartSpec


@pytest.fixture
def rankings():
    return pd.DataFrame(
        {
            "year": [2025, 2024, 2025, 2024, 2025],
            "partner": ["A", "A", "B", "B", "C"],
            "amount": [30.0, 10.0, 5.0, 20.0, 40.0],
            "detail": ["a25", "a24", "b25", "b24", "c25"],
        }
    )


def ranking_spec(**options):
    return ChartSpec(
        type="bar_race",
        title="Trade rankings",
        mapping={"time": "year", "category": "partner", "value": "amount", "hover": "detail"},
        options={"top_n": 2, **options},
    )


def test_ranking_slider_reorders_and_replaces_top_categories_per_period(rankings):
    original = rankings.copy(deep=True)
    fig = create_registry().render(rankings, ranking_spec())
    assert list(fig.data[0].y) == ["B", "A"]
    assert list(fig.data[0].x) == [20, 10]
    assert list(fig.frames[1].data[0].y) == ["C", "A"]
    assert list(fig.frames[1].data[0].x) == [40, 30]
    assert list(fig.frames[1].layout.yaxis.categoryarray) == ["C", "A"]
    assert fig.frames[1].layout.yaxis.range == (1.5, -0.5)
    steps = fig.layout.sliders[0].steps
    assert [step.label for step in steps] == ["2024", "2025"]
    assert [step.args[0][0] for step in steps] == [frame.name for frame in fig.frames]
    assert steps[1].args[1]["frame"]["redraw"]
    assert list(fig.frames[1].data[0].customdata[0]) == ["2025", "c25"]
    assert fig.layout.margin.b >= 100
    pd.testing.assert_frame_equal(rankings, original)


def test_ranking_colors_and_scale_stay_consistent_during_playback(rankings):
    fig = create_registry().render(rankings, ranking_spec(frame_duration=1200))
    first, second = (frame.data[0] for frame in fig.frames)
    assert (
        first.marker.color[list(first.y).index("A")]
        == second.marker.color[list(second.y).index("A")]
    )
    assert fig.frames[0].layout.xaxis.range == fig.frames[1].layout.xaxis.range
    buttons = fig.layout.updatemenus[0].buttons
    assert buttons[0].args[1]["frame"]["duration"] == 1200
    assert buttons[1].args[0] == (None,)


def test_ranking_can_rescale_each_period_and_render_signed_values(rankings):
    rankings.loc[rankings.partner == "A", "amount"] *= -1
    fig = create_registry().render(rankings, ranking_spec(fixed_scale=False, top_n=3))
    assert fig.frames[0].layout.xaxis.range != fig.frames[1].layout.xaxis.range
    for frame in fig.frames:
        low, high = frame.layout.xaxis.range
        assert low < min(frame.data[0].x)
        assert high > max(frame.data[0].x)


def test_ranking_dates_ties_and_a_single_period():
    data = pd.DataFrame({"date": ["2025-01-01"] * 2, "name": ["B", "A"], "value": [10.0, 10.0]})
    fig = create_registry().render(
        data,
        ChartSpec(
            type="bar_race",
            mapping={"time": "date", "category": "name", "value": "value"},
            column_types={"date": "temporal"},
        ),
    )
    assert fig.layout.sliders[0].steps[0].label == "2025-01-01"
    assert list(fig.data[0].y) == ["A", "B"]
    assert len(fig.data[0].customdata) == 2


@pytest.mark.parametrize("kind", ["duplicate", "null_time", "null_category", "null_value"])
def test_ranking_rejects_ambiguous_or_missing_data(rankings, kind):
    if kind == "duplicate":
        rankings = pd.concat([rankings, rankings.iloc[:1]], ignore_index=True)
    else:
        column = {"null_time": "year", "null_category": "partner", "null_value": "amount"}[kind]
        rankings.loc[0, column] = None
    with pytest.raises(ValueError, match="one row per time|must not contain nulls"):
        create_registry().render(rankings, ranking_spec())


def test_ranking_period_limit_does_not_silently_drop_history():
    count = DASHBOARD_MAX_ANIMATION_PERIODS + 1
    data = pd.DataFrame({"time": range(count), "category": ["A"] * count, "value": [1.0] * count})
    with pytest.raises(ValueError, match="Filter the query"):
        create_registry().render(
            data,
            ChartSpec(
                type="bar_race", mapping={"time": "time", "category": "category", "value": "value"}
            ),
        )


def test_ranking_frames_and_controls_survive_json_round_trip(rankings):
    fig = create_registry().render(rankings, ranking_spec())
    restored = go.Figure(fig.to_plotly_json())
    assert len(restored.frames) == 2
    assert restored.layout.sliders[0].steps[1].args[0][0] == restored.frames[1].name


def test_long_category_names_do_not_change_label_column_or_plot_geometry():
    long_name = "A very long category name that only enters the rankings in the second year"
    data = pd.DataFrame(
        {
            "year": [2024, 2024, 2025, 2025],
            "partner": ["Short", "Other", long_name, "Short"],
            "amount": [20.0, 10.0, 30.0, 5.0],
        }
    )
    spec = ChartSpec(
        type="bar_race",
        mapping={"time": "year", "category": "partner", "value": "amount"},
        options={"category_width": 160},
    )
    figure = create_registry().render(data, spec)
    assert figure.layout.margin.l == 180
    assert not figure.layout.margin.autoexpand
    assert not figure.layout.yaxis.automargin
    assert not figure.layout.xaxis.automargin
    assert figure.layout.meta["category_labels"]["width"] == 160
    assert long_name in figure.layout.meta["category_labels"]["names"]
    for snapshot in figure.frames:
        assert not snapshot.layout.yaxis.automargin
        assert snapshot.layout.margin.l is None  # Inherits the same fixed base margin.
        assert snapshot.layout.xaxis.domain is None
        assert list(snapshot.layout.yaxis.ticktext) == list(snapshot.data[0].y)
    assert figure.frames[1].data[0].y[0] == long_name
    assert figure.frames[1].data[0].ids[0] == long_name
    assert figure.frames[1].layout.yaxis.ticktext[0] == long_name


def test_ranking_ascending_changes_display_order_while_retaining_top_n(rankings):
    registry = create_registry()
    ascending = registry.render(rankings, ranking_spec(sort_order="ascending"))
    descending = registry.render(rankings, ranking_spec(sort_order="descending"))
    assert list(ascending.data[0].x) == [10, 20]
    assert list(ascending.data[0].y) == ["A", "B"]
    assert list(ascending.frames[1].data[0].x) == [30, 40]
    assert list(ascending.frames[1].layout.yaxis.categoryarray) == ["A", "C"]
    for lower_first, higher_first in zip(ascending.frames, descending.frames, strict=True):
        assert set(lower_first.data[0].y) == set(higher_first.data[0].y)


def test_ranking_sort_order_is_validated(rankings):
    with pytest.raises(ValueError, match="ascending"):
        create_registry().render(rankings, ranking_spec(sort_order="sideways"))


def test_scrollable_labels_keep_full_names_as_data_and_escape_fallback_markup():
    name = "<b>Category & label</b>"
    data = pd.DataFrame({"year": [2024], "partner": [name], "amount": [10.0]})
    figure = create_registry().render(
        data,
        ChartSpec(
            type="bar_race",
            mapping={"time": "year", "category": "partner", "value": "amount"},
            options={"category_width": 400},
        ),
    )
    assert figure.data[0].y[0] == name
    assert "%{y}" in figure.data[0].hovertemplate
    assert figure.layout.yaxis.ticktext[0] == "&lt;b&gt;Category &amp; label&lt;/b&gt;"


def test_area_sorts_time_and_supports_long_series_and_percentages(rankings):
    fig = create_registry().render(
        rankings,
        ChartSpec(
            type="area",
            mapping={"x": "year", "y": "amount", "color": "partner"},
            options={"normalize": True},
        ),
    )
    assert {trace.name for trace in fig.data} == {"A", "B", "C"}
    assert list(fig.data[0].x) == [2024, 2025]
    assert list(fig.data[0].y) == [10, 30]
    assert fig.data[0].stackgroup
    assert fig.data[0].groupnorm == "percent"
    assert [row[-1] for row in fig.data[0].customdata] == [10, 30]
    assert "%{customdata[0]}" in fig.data[0].hovertemplate
    assert "Share: %{y:.1f}%" in fig.data[0].hovertemplate
    assert fig.layout.yaxis.range == (0, 100)
    assert fig.layout.yaxis.title.text == "Share (%)"
    assert fig.layout.xaxis.rangeslider.visible


def test_area_supports_multiple_wide_measures():
    data = pd.DataFrame({"month": [2, 1], "exports": [20.0, 10.0], "imports": [5.0, 4.0]})
    fig = create_registry().render(
        data,
        ChartSpec(
            type="area",
            mapping={"x": "month", "y": ["exports", "imports"]},
            options={"range_slider": False},
        ),
    )
    assert len(fig.data) == 2
    assert list(fig.data[0].y) == [10, 20]
    assert not fig.layout.xaxis.rangeslider.visible


def test_percent_area_keeps_raw_values_and_hover_details_for_wide_data():
    data = pd.DataFrame(
        {"month": [2, 1], "exports": [20.0, 10.0], "imports": [5.0, 4.0], "note": ["Feb", "Jan"]}
    )
    figure = create_registry().render(
        data,
        ChartSpec(
            type="area",
            mapping={"x": "month", "y": ["exports", "imports"], "hover": "note"},
            options={"normalize": True},
        ),
    )
    assert [list(row) for row in figure.data[0].customdata] == [["Jan", 10.0], ["Feb", 20.0]]
    assert [list(row) for row in figure.data[1].customdata] == [["Jan", 4.0], ["Feb", 5.0]]
    assert "%{customdata[1]}" in figure.data[1].hovertemplate


@pytest.mark.parametrize("kind", ["negative", "duplicate", "null", "wide_and_color"])
def test_area_rejects_misleading_stacks(rankings, kind):
    spec = ChartSpec(type="area", mapping={"x": "year", "y": "amount", "color": "partner"})
    if kind == "negative":
        rankings.loc[0, "amount"] = -1
    elif kind == "duplicate":
        rankings = pd.concat([rankings, rankings.iloc[:1]], ignore_index=True)
    elif kind == "null":
        rankings.loc[0, "amount"] = None
    else:
        rankings["another"] = 1.0
        spec.mapping["y"] = ["amount", "another"]
    with pytest.raises(ValueError):
        create_registry().render(rankings, spec)
