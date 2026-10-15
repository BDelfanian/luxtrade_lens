# Dashboard builder and API

Launch Streamlit as usual and open **Dashboard**, or navigate to `/dashboard`. Run a SQL
query, inspect its output, then choose a chart and map columns to chart
locations. Set a title, description, labels and display options before adding the chart.
Dashboards support 1–3 charts per row, up to 24 charts, reordering and removal.

The current dashboard lives in the browser session. **Download dashboard JSON** saves its
queries, mappings and layout; **Load a dashboard** restores that definition in a later
session. Loading a definition executes its queries when the dashboard is rendered. Data is
queried again on Streamlit reruns, so saved layouts use the current database rather than
storing stale results. Query and data evidence and source attribution accompany every panel.

All queries use the existing SQL guard and semantic-layer connection: one read-only SELECT
against the allowed views, a 10,000-row limit, external access disabled, and a 10-second
timeout. If a query reaches the row limit, refine or aggregate it before interpreting the
chart. SQL controls filtering and aggregation; column names are arbitrary and may use aliases.

## HTTP API

Install the project requirements, then run the API beside Streamlit:

```bash
python -m uvicorn luxtrade.api.app:app --host 127.0.0.1 --port 8000
```

The API uses the same `LUXTRADE_DB` setting as Streamlit. Open
`http://127.0.0.1:8000/docs` for interactive request schemas. It runs locally without an
LLM or API key. The API has no authentication and should remain bound to localhost unless
an authenticated deployment proxy is configured.

| Method and path | Purpose |
| --- | --- |
| `GET /api/charts/types` | Chart names, role cardinalities and option JSON schemas |
| `GET /api/query/schema` | Allowed semantic views and documented columns |
| `POST /api/query/preview` | `{ "query": "SELECT …" }` → checked SQL, typed columns, rows |
| `POST /api/charts/render` | Query + chart definition → Plotly JSON and query evidence |
| `POST /api/charts/{type}/render` | Same request, with URL type required to match `chart.type` |
| `POST /api/charts/render?format=html` | Same request → standalone interactive HTML with Plotly included |
| `POST /api/dashboards/render` | Dashboard JSON → ordered panels; failed panels carry an `error` |

The type-specific route also supports `?format=html`. Invalid SQL, mappings or options return
HTTP 422; a missing database returns 503. Dashboard rendering isolates panel errors so valid
charts still render, and runs identical checked queries once per dashboard request.

Example with Python (or paste the JSON into the API docs):

```python
import requests

definition = {
    "query": """
        SELECT period, flow, SUM(value_eur) AS amount
        FROM v_lu_trade_hs2
        GROUP BY period, flow
        ORDER BY period, flow
    """,
    "chart": {
        "type": "line",
        "title": "Monthly trade",
        "description": "Exports and imports in current euros",
        "mapping": {"x": "period", "y": "amount", "color": "flow"},
        "column_types": {"period": "temporal"},
        "labels": {"amount": "Trade value (EUR)", "period": "Month"},
        "options": {"markers": False, "range_slider": True},
    },
}

response = requests.post(
    "http://127.0.0.1:8000/api/charts/render", json=definition, timeout=30
)
response.raise_for_status()
result = response.json()
# result: figure, rows, columns, checked sql, row_count, row_limit,
# at_row_limit, source, is_placeholder

# To view or embed a standalone chart:
html = requests.post(
    "http://127.0.0.1:8000/api/charts/line/render?format=html",
    json=definition, timeout=30,
)
html.raise_for_status()
from pathlib import Path
Path("chart.html").write_text(html.text, encoding="utf-8")
```

Render the same chart in a dashboard with:

```python
dashboard = {
    "version": 1,
    "title": "Trade dashboard",
    "description": "Monthly indicators",
    "columns": 2,
    "charts": [definition],
}
response = requests.post(
    "http://127.0.0.1:8000/api/dashboards/render", json=dashboard, timeout=60
)
response.raise_for_status()
```

## Mapping contract

`mapping` is a dictionary of **role → query output column name(s)**. Required single roles
accept a string or one-element list. Multiple roles accept either a string or a list.
Unknown roles, missing columns, duplicate columns within a role, and wrong cardinalities
are rejected. Empty query results produce an explicit empty chart after mapping validation.

| Chart | Required roles | Optional roles | Options |
| --- | --- | --- | --- |
| `line` | `x` (one), `y` (one or more numeric) | `color` (one), `hover` (many) | `markers`, `sort_x`, `range_slider` |
| `bar` | `x` (one category), `y` (one or more numeric) | `color` (one), `hover` (many) | `orientation`: `v`/`h`; `barmode`: `group`/`stack`/`relative` |
| `pie` | `names` (one), `values` (one numeric) | `hover` (many) | `hole`: 0–0.8 |
| `bar_race` | `time` (one), `category` (one), `value` (one numeric) | `hover` (many) | `top_n`: 1–30; `frame_duration`: 100–3000 ms; `fixed_scale` |
| `area` | `x` (time), `y` (one or more numeric) | `color` (one), `hover` (many) | `range_slider`, `normalize` (percentage shares) |

For cartesian charts, use multiple `y` columns for wide results, or one `y` column plus a
`color` column for long results. Combining multiple `y` columns with `color` is rejected;
unpivot the measures in SQL to express that combination as long-format data. Horizontal
bars retain the same logical mapping: `x` remains the category and `y` remains the measures.

`column_types` overrides output types per column with `numeric`, `temporal` or `categorical`.
Omit a column to retain its query dtype. Text dates can therefore map to a temporal axis,
numeric text can map to values, and numeric-looking codes can remain categorical. Invalid
conversions fail with the column name. Numeric-to-date conversions must be explicit in SQL
to avoid interpreting years as timestamps in nanoseconds. `labels` maps column names to
display labels. Chart `height` defaults to 420 and accepts 200–1200 pixels.

Numeric roles reject text, booleans and infinite values. Pie charts additionally reject
negative/null values and all-zero totals. Lines default to sorting X values and can expose
a time range slider. Bar charts preserve query ordering. Chart height is also configurable
under **Chart options** in the dashboard builder.

## Time-series charts

Open **Try a time-series example** in the builder and click **Load example**. The example
runs its SQL and fills in all chart mappings, labels and options. Choose either:

- **Partner rankings over time**: annual export values for the last six complete years,
  with the top ten partners sorted by value for each year. Drag the year slider beneath
  the chart or press Play/Pause. Change **Top N**, playback speed, or the value-axis scale
  under Chart options. Equal values sort by category name for a stable ranking.
- **Monthly trade composition**: exports and imports as stacked areas. Drag the range
  selection beneath the chart to zoom, or enable **Normalize** to compare shares out of 100%.

Ranking bars require exactly one query row per time/category pair. Aggregate in SQL first;
duplicate pairs and null times/categories/values are rejected. Time may be numeric (years),
temporal (dates/timestamps), or ordered text. Text sorts lexically, so use a temporal type
override for date strings. Each frame shows the largest `top_n` values for that period,
including categories newly entering the rankings. Missing categories are absent in that
period; they are not silently filled with zero. Category colors remain consistent across
periods. The default fixed value scale allows direct comparison between periods; turn it off
to rescale for each period. Signed values are supported. Playback advances through ranked
snapshots, and starts only when Play is pressed. Up to 360 periods are supported per chart;
filter longer histories or aggregate them to quarters/years.

Category labels occupy a fixed-width column throughout playback, so long names entering
the rankings never shift or shrink the bars. In Streamlit and HTML charts, scroll that
column horizontally (or focus it and use the arrow keys) to read long names. The scroll
position is retained when changing periods. Adjust **Category label width (pixels)** under
Chart options (`category_width` in API options, 80–400 pixels; default 180). Plain Plotly
JSON clients receive the complete names and fixed margins; clients rendering JSON directly
can use the label metadata to add the same scrolling presentation. The HTML renderer uses
the figure's
`layout.meta.category_labels` metadata to display full, scrollable names.

**Sort order** chooses descending (largest at the top, the default) or ascending
(smallest at the top) for the displayed bars. `top_n` still selects the largest N values
in each period, so changing sort direction changes their display order without changing
which categories are included. API options use `"sort_order": "ascending"` or `"descending"`.

Area charts require one query row per time/series, or one row per time when using multiple
wide value columns. They sort by time and accept nonnegative, non-null values. Use lines for
signed balances. Missing series/time combinations follow Plotly's stacking behavior; supply
a complete time grid in SQL when explicit zero or missing-period handling is needed. In
percentage mode the Y axis shows shares while query values remain available in hover data.

Both chart types work through the existing API routes, dashboard JSON export/import and
multi-panel layouts. Animation frames, sliders and playback buttons are retained in the
JSON figure and standalone HTML response. HTML charts open paused.

Example ranking definition for `POST /api/charts/bar_race/render`:

```json
{
  "query": "SELECT year, partner, SUM(value_eur) AS amount FROM v_lu_trade_hs2 WHERE flow = 'export' AND year BETWEEN 2020 AND 2025 GROUP BY year, partner",
  "chart": {
    "type": "bar_race",
    "title": "Leading export partners",
    "mapping": {"time": "year", "category": "partner", "value": "amount"},
    "labels": {"year": "Year", "amount": "Exports (EUR)"},
    "options": {"top_n": 10, "frame_duration": 900, "fixed_scale": true},
    "height": 560
  }
}
```

## Adding a chart

`viz/registry.py` contains the pure chart contract. `viz/mapped_charts.py` supplies the built-in
plugins; `viz/time_charts.py` contains the time-series implementations.
`agents/dashboard.py` owns guarded SQL execution; the Streamlit page and FastAPI
routes both use this service. Existing question-driven chart selection remains independent.

1. Subclass `ChartPlugin`, declare a unique `type`, human `label`, and `MappingRole` tuple.
2. Define a `ChartOptions` subclass for any options; extra/unknown options are rejected.
3. Implement `build(frame, spec, options) -> plotly.graph_objects.Figure`. The registry has
   already validated mappings and converted column types; do not mutate the source frame.
4. Register the plugin in `create_registry()` in `viz/mapped_charts.py`.

The UI discovers role controls and basic option controls from the registry. The API type
catalog and generic/type-specific routes work without route changes. Option controls support
boolean, enum, numeric and string fields; complex option schemas need a dedicated UI widget.

A future forecast chart can declare roles such as `time`, `observed`, `forecast`, `lower`
and `upper`, with numeric requirements on the value/bound roles. These names need no changes
to `ChartSpec` or the service. Use `column_types={"month": "temporal"}` for the mapped time
column, and implement the forecast and band traces in that plugin's builder. Computation of
forecasts belongs in analytics; the plugin renders columns supplied by its query.
