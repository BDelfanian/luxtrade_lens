import pytest
from streamlit.testing.v1 import AppTest

from luxtrade import config


@pytest.fixture
def app_env(processed_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", processed_dir / config.DUCKDB_FILE)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "DEMO_RUNS_DIR", tmp_path / "demo")
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # offline: the Assistant must never reach a real LLM from this test
    monkeypatch.setattr("luxtrade.agents.service.default_llm", lambda: None)


def _app() -> AppTest:
    return AppTest.from_file(str(config.ROOT_DIR / "src/luxtrade/app/Home.py"), default_timeout=120)


def test_app_opens_on_the_overview(app_env):
    at = _app()
    at.run()
    assert not at.exception
    assert at.title[0].value == "Luxembourg's trade in goods at a glance"
    assert len(at.metric) == 4
    assert len(at.main.subheader) == 5
    assert any(b.key == "explore-partners" for b in at.button)


def test_app_loads_and_answers_a_preset(app_env):
    at = _app()
    at.run()
    assert not at.exception
    assert any("Placeholder data" in w.value for w in at.sidebar.warning)
    at.button(key="preset-Q1").click().run()
    assert not at.exception
    assert len(at.tabs) == 4
    assert any("largest partner" in m.value for m in at.markdown)


def test_explore_opens_the_question_in_the_assistant(app_env):
    at = _app()
    at.run()
    at.button(key="explore-products").click().run()
    assert not at.exception
    assert len(at.tabs) == 4
    assert any("from the overview" in c.value for c in at.caption)


def test_language_survives_the_switch_to_the_assistant(app_env):
    at = _app()
    at.run()
    at.segmented_control(key="lang_choice").set_value("fr").run()
    assert at.main.subheader[0].value.startswith("1. Quel est le poids")
    at.button(key="explore-partners").click().run()
    assert not at.exception
    assert at.button(key="preset-Q1").label == "Q1 · Principaux partenaires"


def test_dashboard_builds_reorders_and_removes_charts(app_env):
    at = _app().run()
    at.switch_page("app_pages/dashboard.py").run()
    assert not at.exception
    assert at.title[0].value == "Dashboard builder"
    at.button(key="dashboard-run-query").click().run()
    assert not at.exception
    at.selectbox(key="dashboard-map-line-color").set_value("flow").run()
    at.text_input(key="dashboard-chart-title").set_value("Monthly trade").run()
    at.button(key="dashboard-add").click().run()
    assert not at.exception
    assert len(at.session_state["dashboard_spec"].charts) == 1
    at.selectbox(key="dashboard-chart-type").set_value("bar").run()
    at.text_input(key="dashboard-chart-title").set_value("Trade bars").run()
    at.button(key="dashboard-add").click().run()
    assert not at.exception
    at.button(key="dashboard-up-1").click().run()
    assert at.session_state["dashboard_spec"].charts[0].chart.type == "bar"
    at.button(key="dashboard-remove-0").click().run()
    assert not at.exception
    assert len(at.session_state["dashboard_spec"].charts) == 1


def test_dashboard_pie_and_changed_query_require_new_preview(app_env):
    at = _app().run()
    at.switch_page("app_pages/dashboard.py").run()
    at.text_area(key="dashboard-query").set_value(
        "SELECT flow, SUM(value_eur) AS amount FROM v_lu_trade_hs2 GROUP BY flow"
    ).run()
    at.button(key="dashboard-run-query").click().run()
    at.selectbox(key="dashboard-chart-type").set_value("pie").run()
    at.button(key="dashboard-add").click().run()
    assert not at.exception
    assert at.session_state["dashboard_spec"].charts[0].chart.type == "pie"
    at.text_area(key="dashboard-query").set_value("SELECT * FROM dim_partner").run()
    assert any("query has changed" in info.value for info in at.info)
    assert not any(button.key == "dashboard-add" for button in at.button)


@pytest.mark.parametrize(
    ("example", "chart_type"),
    [
        ("Partner rankings over time", "bar_race"),
        ("Monthly trade composition", "area"),
    ],
)
def test_dashboard_time_examples_load_mappings_and_add_to_dashboard(app_env, example, chart_type):
    at = _app().run()
    at.switch_page("app_pages/dashboard.py").run()
    at.selectbox(key="dashboard-example").set_value(example).run()
    at.button(key="dashboard-load-example").click().run()
    assert not at.exception
    assert at.selectbox(key="dashboard-chart-type").value == chart_type
    if chart_type == "bar_race":
        assert at.selectbox(key="dashboard-map-bar_race-category").value == "partner"
        at.number_input(key="dashboard-option-bar_race-top_n").set_value(5).run()
        at.selectbox(key="dashboard-option-bar_race-sort_order").set_value("ascending").run()
    else:
        at.checkbox(key="dashboard-option-area-normalize").set_value(True).run()
    at.button(key="dashboard-add").click().run()
    assert not at.exception
    panel = at.session_state["dashboard_spec"].charts[0]
    assert panel.chart.type == chart_type
    if chart_type == "bar_race":
        assert panel.chart.options["top_n"] == 5
        assert panel.chart.options["sort_order"] == "ascending"
        assert panel.chart.options["category_width"] == 180
    else:
        assert panel.chart.options["normalize"]
