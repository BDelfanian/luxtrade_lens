"""Run with ``python -m uvicorn luxtrade.api.app:app --host 127.0.0.1 --port 8000``."""

from html import escape
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from luxtrade.agents.dashboard import ChartRequest, DashboardService, DashboardSpec, QueryRequest
from luxtrade.semantic.catalog import VIEWS
from luxtrade.semantic.layer import QueryError, SemanticLayer
from luxtrade.viz.html import chart_html
from luxtrade.viz.mapped_charts import CHARTS


def get_service() -> DashboardService:
    """Resolve the configured database lazily, so API discovery needs no database."""
    return DashboardService(SemanticLayer())


Service = Annotated[DashboardService, Depends(get_service)]
OutputFormat = Annotated[Literal["json", "html"], Query()]


def create_app() -> FastAPI:
    """Build the API, with injectable services for offline tests."""
    api = FastAPI(title="LuxTrade dashboard API", version="1.0")

    @api.exception_handler(ValueError)
    async def invalid_chart(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(QueryError)
    async def invalid_query(request: Request, exc: QueryError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(FileNotFoundError)
    async def missing_database(request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @api.get("/api/charts/types")
    def chart_types() -> list[dict]:
        """Discover supported charts, mapping roles and validated option schemas."""
        return CHARTS.describe()

    @api.get("/api/query/schema")
    def query_schema() -> dict:
        """List queryable semantic views and their documented output columns."""
        return {
            name: {"description": description, "columns": columns}
            for name, (description, columns) in VIEWS.items()
        }

    @api.post("/api/query/preview")
    def preview(body: QueryRequest, service: Service) -> dict:
        """Execute a guarded query and describe its columns before mapping them."""
        return service.preview(body).payload()

    @api.post("/api/charts/render", response_model=None)
    def render_chart(body: ChartRequest, service: Service, format: OutputFormat = "json"):
        """Return a Plotly figure and evidence, or a standalone HTML chart."""
        result, figure = service.render(body)
        if format == "html":
            source = service.source
            if service.sem.coverage.is_placeholder:
                source = "Synthetic placeholder data. " + source
            figure.add_annotation(
                text=escape(source), x=0, y=-0.25, xref="paper", yref="paper", showarrow=False
            )
            figure.update_layout(margin_b=120)
            return HTMLResponse(chart_html(figure))
        return service.chart_payload(result, figure)

    @api.post("/api/charts/{chart_type}/render", response_model=None)
    def render_chart_type(
        chart_type: str, body: ChartRequest, service: Service, format: OutputFormat = "json"
    ):
        """Type-specific alias using exactly the same request and rendering contract."""
        if chart_type != body.chart.type:
            raise ValueError("The URL chart type must match chart.type in the request.")
        return render_chart(body, service, format)

    @api.post("/api/dashboards/render")
    def render_dashboard(body: DashboardSpec, service: Service) -> dict:
        """Render an ordered dashboard, retaining errors beside individual failed panels."""
        return service.render_dashboard(body)

    return api


app = create_app()
