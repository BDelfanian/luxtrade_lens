import pytest
from fastapi.testclient import TestClient

from luxtrade.agents.dashboard import DashboardService
from luxtrade.api.app import create_app, get_service


@pytest.fixture
def client(semantic):
    app = create_app()
    app.dependency_overrides[get_service] = lambda: DashboardService(semantic)
    with TestClient(app) as test_client:
        yield test_client


def request_body(chart_type="bar"):
    return {
        "query": "SELECT flow, SUM(value_eur) AS amount FROM v_lu_trade_hs2 GROUP BY flow",
        "chart": {"type": chart_type, "title": "Trade", "mapping": {"x": "flow", "y": "amount"}},
    }


def test_discovery_and_openapi(client):
    response = client.get("/api/charts/types")
    assert {chart["type"] for chart in response.json()} == {
        "line",
        "bar",
        "pie",
        "bar_race",
        "area",
    }
    assert client.get("/api/query/schema").json()["v_lu_trade_hs2"]["columns"]
    assert client.get("/openapi.json").status_code == 200


def test_preview(client):
    response = client.post("/api/query/preview", json={"query": request_body()["query"]})
    assert response.status_code == 200
    assert response.json()["row_count"] == 2
    assert response.json()["columns"][1]["type"] == "numeric"


@pytest.mark.parametrize("path", ["/api/charts/render", "/api/charts/bar/render"])
def test_generic_and_type_specific_routes_share_contract(client, path):
    response = client.post(path, json=request_body())
    assert response.status_code == 200
    payload = response.json()
    assert payload["figure"]["data"][0]["type"] == "bar"
    assert payload["is_placeholder"]
    assert "Eurostat" in payload["source"]


def test_html_chart_is_standalone_with_source(client):
    response = client.post("/api/charts/bar/render?format=html", json=request_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Plotly.newPlot" in response.text
    assert "Synthetic placeholder data" in response.text
    assert "Eurostat" in response.text


@pytest.mark.parametrize("kind", ["sql", "mapping", "type", "options", "mismatch", "syntax"])
def test_invalid_requests_are_client_errors(client, kind):
    body = request_body()
    path = "/api/charts/render"
    if kind == "sql":
        body["query"] = "DROP TABLE v_lu_trade"
    elif kind == "syntax":
        body["query"] = "SELECT missing FROM v_lu_trade"
    elif kind == "mapping":
        body["chart"]["mapping"]["y"] = "missing"
    elif kind == "type":
        body["chart"]["type"] = "unknown"
    elif kind == "options":
        body["chart"]["options"] = {"orientation": "diagonal"}
    else:
        path = "/api/charts/pie/render"
    response = client.post(path, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_dashboard_api_keeps_working_panels(client):
    bad = request_body()
    bad["chart"]["mapping"]["y"] = "missing"
    response = client.post(
        "/api/dashboards/render", json={"title": "Trade", "charts": [request_body(), bad]}
    )
    assert response.status_code == 200
    assert "figure" in response.json()["panels"][0]
    assert "error" in response.json()["panels"][1]


def test_ranking_api_preserves_frames_slider_and_playback_in_json_and_html(client):
    body = {
        "query": (
            "SELECT year, flow, SUM(value_eur) AS amount FROM v_lu_trade_hs2 GROUP BY year, flow"
        ),
        "chart": {
            "type": "bar_race",
            "mapping": {"time": "year", "category": "flow", "value": "amount"},
        },
    }
    response = client.post("/api/charts/bar_race/render", json=body)
    assert response.status_code == 200
    figure = response.json()["figure"]
    assert len(figure["frames"]) > 1
    assert len(figure["layout"]["sliders"][0]["steps"]) == len(figure["frames"])
    assert figure["layout"]["margin"]["l"] == 200
    assert not figure["layout"]["yaxis"]["automargin"]
    response = client.post("/api/charts/bar_race/render?format=html", json=body)
    assert response.status_code == 200
    assert "Plotly.addFrames" in response.text
    assert "luxtrade-category-names" in response.text
    assert "Plotly.animate(" not in response.text.split("Plotly.addFrames")[-1]
