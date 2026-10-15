"""Dashboard builder: query preview, registry-driven mapping controls and portable layouts."""

import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from luxtrade.agents.dashboard import (
    ChartRequest,
    DashboardService,
    DashboardSpec,
    QueryRequest,
    describe_columns,
)
from luxtrade.agents.dashboard_examples import time_series_examples
from luxtrade.app.chart_view import render_chart
from luxtrade.app.components import get_assistant
from luxtrade.semantic.catalog import VIEWS
from luxtrade.semantic.layer import QueryError
from luxtrade.viz.registry import ChartPlugin, ChartSpec

EXAMPLE_QUERY = """SELECT period, flow, SUM(value_eur) AS value_eur
FROM v_lu_trade_hs2
GROUP BY period, flow
ORDER BY period, flow"""


def _mapping_controls(plugin: ChartPlugin, columns: list[dict]) -> dict[str, str | list[str]]:
    names = [c["name"] for c in columns]
    numeric = [c["name"] for c in columns if c["type"] == "numeric"]
    mapping = {}
    for role in plugin.roles:
        key = f"dashboard-map-{plugin.type}-{role.name}"
        preferred = numeric if role.numeric and numeric else names
        if role.multiple:
            selected = st.multiselect(
                role.label + (" *" if role.required else ""),
                names,
                default=preferred[:1] if role.required else [],
                key=key,
            )
        else:
            choices = names if role.required else [None, *names]
            selected = st.selectbox(
                role.label + (" *" if role.required else ""),
                choices,
                index=choices.index(preferred[0]) if role.required and names else 0,
                format_func=lambda value: value if value is not None else "None",
                key=key,
            )
        if selected:
            mapping[role.name] = selected
    return mapping


def _option_controls(plugin: ChartPlugin) -> dict:
    options = {}
    for name, schema in plugin.options_model.model_json_schema()["properties"].items():
        label = schema.get("title", name.replace("_", " ").title())
        default = schema.get("default")
        key = f"dashboard-option-{plugin.type}-{name}"
        if "enum" in schema:
            choices = schema["enum"]
            options[name] = st.selectbox(label, choices, index=choices.index(default), key=key)
        elif schema.get("type") == "boolean":
            options[name] = st.checkbox(label, value=default, key=key)
        elif schema.get("type") in ("integer", "number"):
            cast = int if schema["type"] == "integer" else float
            options[name] = st.number_input(
                label,
                min_value=cast(schema["minimum"]) if "minimum" in schema else None,
                max_value=cast(schema["maximum"]) if "maximum" in schema else None,
                value=cast(default),
                key=key,
            )
        else:
            options[name] = st.text_input(label, value=default or "", key=key)
    return options


def _column_controls(columns: list[dict]) -> tuple[dict, dict]:
    types, labels = {}, {}
    with st.expander("Column types and display labels"):
        st.caption(
            "Override text dates as temporal, numeric text as numeric, or codes as categorical."
        )
        for column in columns:
            name = column["name"]
            left, right = st.columns(2)
            kind = left.selectbox(
                f"Type: {name}",
                ["auto", "numeric", "temporal", "categorical"],
                key=f"dashboard-type-{name}",
            )
            label = right.text_input(f"Label: {name}", value=name, key=f"dashboard-label-{name}")
            if kind != "auto":
                types[name] = kind
            if label != name:
                labels[name] = label
    return types, labels


def _load_dashboard() -> None:
    with st.expander("Load a dashboard"):
        uploaded = st.file_uploader("Dashboard JSON", type=["json"], key="dashboard-import")
        if st.button("Load dashboard", disabled=uploaded is None):
            try:
                loaded = DashboardSpec.model_validate_json(uploaded.getvalue())
                # Validate plugin names and options immediately; columns are checked on execution.
                registry = DashboardService(get_assistant().sem).registry
                for panel in loaded.charts:
                    plugin = registry.get(panel.chart.type)
                    plugin.options_model.model_validate(panel.chart.options)
                st.session_state.dashboard_spec = loaded
                st.session_state["dashboard-title"] = loaded.title
                st.session_state["dashboard-description"] = loaded.description
                st.session_state["dashboard-columns"] = loaded.columns
                st.rerun()
            except (ValueError, ValidationError) as exc:
                st.error(f"Cannot load dashboard: {exc}")


def _example_controls(service: DashboardService) -> None:
    with st.expander("Try a time-series example"):
        examples = time_series_examples(service.sem.coverage.latest_complete_year)
        choice = st.selectbox("Example", list(examples), key="dashboard-example")
        if st.button("Load example", key="dashboard-load-example"):
            request = examples[choice]
            try:
                result = service.preview(request)
            except (ValueError, QueryError) as exc:
                st.error(str(exc))
                return
            for key in list(st.session_state):
                if key.startswith(
                    ("dashboard-map-", "dashboard-type-", "dashboard-label-", "dashboard-option-")
                ):
                    del st.session_state[key]
            st.session_state["dashboard-query"] = request.query
            st.session_state["dashboard-chart-type"] = request.chart.type
            st.session_state["dashboard-chart-title"] = request.chart.title
            st.session_state["dashboard-chart-description"] = request.chart.description
            st.session_state["dashboard-chart-height"] = request.chart.height
            st.session_state.dashboard_preview = (request.query, result)
            plugin = service.registry.get(request.chart.type)
            for role in plugin.roles:
                value = request.chart.mapping.get(role.name)
                if value is not None:
                    if role.multiple and isinstance(value, str):
                        value = [value]
                    st.session_state[f"dashboard-map-{plugin.type}-{role.name}"] = value
            for name, kind in request.chart.column_types.items():
                st.session_state[f"dashboard-type-{name}"] = kind
            for name, label in request.chart.labels.items():
                st.session_state[f"dashboard-label-{name}"] = label
            for name, value in request.chart.options.items():
                st.session_state[f"dashboard-option-{plugin.type}-{name}"] = value


def _builder(service: DashboardService, dashboard: DashboardSpec) -> None:
    st.subheader("Add a chart")
    _example_controls(service)
    query = st.text_area("SQL query", value=EXAMPLE_QUERY, height=160, key="dashboard-query")
    if st.button("Run query", type="primary", key="dashboard-run-query"):
        try:
            result = service.preview(QueryRequest(query=query))
            st.session_state.dashboard_preview = (query, result)
            # Old mapping widget values belong to the previous result schema.
            for key in list(st.session_state):
                if key.startswith(("dashboard-map-", "dashboard-type-", "dashboard-label-")):
                    del st.session_state[key]
        except (ValueError, QueryError) as exc:
            st.session_state.pop("dashboard_preview", None)
            st.error(str(exc))
    with st.expander("Available tables and columns"):
        for name, (description, columns) in VIEWS.items():
            st.markdown(f"**{name}** — {description}")
            st.code(", ".join(column[0] for column in columns))
    preview = st.session_state.get("dashboard_preview")
    if preview is None:
        st.info("Run a query to preview its output and map columns to a chart.")
        return
    preview_query, result = preview
    if query != preview_query:
        st.info("The query has changed. Run it again to update the chart mappings.")
        return
    st.dataframe(result.frame.head(100), hide_index=True, width="stretch")
    st.caption(f"{len(result.frame):,} rows returned; showing the first 100.")
    if result.payload()["at_row_limit"]:
        st.warning(
            "The query reached the row limit. Aggregate or filter it to avoid incomplete charts."
        )
    types = service.registry.describe()
    chart_type = st.selectbox(
        "Chart type",
        [p["type"] for p in types],
        format_func=lambda value: service.registry.get(value).label,
        key="dashboard-chart-type",
    )
    plugin = service.registry.get(chart_type)
    title = st.text_input("Chart title", key="dashboard-chart-title")
    description = st.text_input("Chart description", key="dashboard-chart-description")
    columns = describe_columns(result.frame)
    mapping = _mapping_controls(plugin, columns)
    column_types, labels = _column_controls(columns)
    with st.expander("Chart options"):
        options = _option_controls(plugin)
        height = st.number_input(
            "Chart height (pixels)",
            min_value=200,
            max_value=1200,
            value=420,
            key="dashboard-chart-height",
        )
    request = ChartRequest(
        query=query,
        chart=ChartSpec(
            type=chart_type,
            title=title,
            description=description,
            mapping=mapping,
            column_types=column_types,
            labels=labels,
            options=options,
            height=height,
        ),
    )
    try:
        figure = service.registry.render(result.frame, request.chart)
        render_chart(figure, "dashboard-preview-chart")
        st.caption(service.source)
        if st.button("Add to dashboard", key="dashboard-add", disabled=len(dashboard.charts) >= 24):
            dashboard.charts.append(request)
            st.rerun()
    except ValueError as exc:
        st.warning(str(exc))
    with st.expander("API request"):
        st.code("POST http://127.0.0.1:8000/api/charts/render")
        st.code(request.model_dump_json(indent=2), language="json")


def _render_panels(service: DashboardService, dashboard: DashboardSpec) -> None:
    st.subheader(dashboard.title or "My dashboard")
    if dashboard.description:
        st.write(dashboard.description)
    if not dashboard.charts:
        st.info("Your dashboard is empty. Build a chart above and add it here.")
        return
    rendered = service.render_dashboard(dashboard)
    for start in range(0, len(rendered["panels"]), dashboard.columns):
        cols = st.columns(dashboard.columns)
        for offset, panel in enumerate(rendered["panels"][start : start + dashboard.columns]):
            index = start + offset
            with cols[offset], st.container(border=True):
                if "error" in panel:
                    st.error(f"{panel['chart']['title'] or 'Chart'}: {panel['error']}")
                else:
                    figure = go.Figure(panel["figure"])
                    render_chart(figure, f"dashboard-panel-{index}")
                    if panel["chart"]["description"]:
                        st.caption(panel["chart"]["description"])
                    st.caption(panel["source"])
                    if panel["at_row_limit"]:
                        st.warning("Row limit reached; aggregate or filter this query.")
                    with st.expander("Query and data"):
                        st.code(panel["sql"], language="sql")
                        st.dataframe(panel["rows"], hide_index=True, width="stretch")
                left, middle, right = st.columns(3)
                if left.button("Move up", key=f"dashboard-up-{index}", disabled=index == 0):
                    dashboard.charts[index - 1], dashboard.charts[index] = (
                        dashboard.charts[index],
                        dashboard.charts[index - 1],
                    )
                    st.rerun()
                if middle.button(
                    "Move down",
                    key=f"dashboard-down-{index}",
                    disabled=index == len(dashboard.charts) - 1,
                ):
                    dashboard.charts[index + 1], dashboard.charts[index] = (
                        dashboard.charts[index],
                        dashboard.charts[index + 1],
                    )
                    st.rerun()
                if right.button("Remove", key=f"dashboard-remove-{index}"):
                    dashboard.charts.pop(index)
                    st.rerun()


def render_page() -> None:
    """Render the builder and the current session's dashboard."""
    service = DashboardService(get_assistant().sem)
    st.title("Dashboard builder")
    st.caption("Build charts from SQL, map output columns, and arrange them into a dashboard.")
    st.session_state.setdefault("dashboard_spec", DashboardSpec())
    dashboard = st.session_state.dashboard_spec
    _load_dashboard()
    dashboard.title = st.text_input("Dashboard title", value=dashboard.title, key="dashboard-title")
    dashboard.description = st.text_input(
        "Dashboard description", value=dashboard.description, key="dashboard-description"
    )
    dashboard.columns = st.selectbox(
        "Charts per row", [1, 2, 3], index=dashboard.columns - 1, key="dashboard-columns"
    )
    _builder(service, dashboard)
    st.divider()
    _render_panels(service, dashboard)
    st.download_button(
        "Download dashboard JSON",
        dashboard.model_dump_json(indent=2),
        file_name="luxtrade-dashboard.json",
        mime="application/json",
        key="dashboard-export",
    )


render_page()
