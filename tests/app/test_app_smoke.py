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
    assert at.title[0].value == "LuxTrade Lens"  # the app name, above every page
    assert at.title[1].value == "Luxembourg's trade in goods at a glance"
    assert [t.label for t in at.tabs] == ["The challenge", "Key findings", "More evidence"]
    # key findings: a headline figure per finding, and a card each opening its details
    assert len(at.metric) == 5
    assert [b.key for b in at.button if (b.key or "").startswith("more-")] == [
        "more-diversification",
        "more-shocks",
        "more-europe",
        "more-prices",
        "more-composition",
        "more-conclusion",
    ]
    # at a glance: the five business questions
    assert len(at.main.subheader) == 5
    assert any(b.key == "explore-partners" for b in at.button)


@pytest.mark.parametrize(
    "key", ["diversification", "shocks", "europe", "prices", "composition", "conclusion"]
)
def test_to_know_more_opens_the_details_of_a_finding(app_env, key):
    at = _app()
    at.run()
    at.button(key=f"more-{key}").click().run()
    assert not at.exception


def test_app_loads_and_answers_a_preset(app_env):
    at = _app()
    at.run()
    assert not at.exception
    assert any("Placeholder data" in w.value for w in at.warning)
    assert not at.sidebar.button  # presets and sessions live on the Ask page only
    at.switch_page("app_pages/ask.py").run()
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
    preset = at.button(key="preset-Q1")
    question = (
        "Quels étaient les 10 principaux partenaires commerciaux du Luxembourg en 2025, "
        "à l'exportation et à l'importation ?"
    )
    assert preset.label == f"**Q1** · {question}"
    assert preset.help == "Principaux partenaires"


def test_dashboard_builds_reorders_and_removes_charts(app_env):
    at = _app().run()
    at.switch_page("app_pages/dashboard.py").run()
    assert not at.exception
    assert at.title[1].value == "Dashboard builder"
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


def test_a_new_answer_is_scrolled_into_view(app_env):
    at = _app()
    at.run()
    at.switch_page("app_pages/ask.py").run()
    at.button(key="preset-Q1").click().run()
    assert not at.exception
    assert at.query_params.get("session")  # the run finished and the session is in the URL
    assert any("scrollIntoView" in h.proto.body for h in at.get("html"))
    assert "scroll_to" not in at.session_state  # scrolls once, not on every rerun


def test_sessions_are_managed_on_the_ask_page(app_env):
    at = _app()
    at.run()
    at.switch_page("app_pages/ask.py").run()
    at.button(key="preset-Q1").click().run()
    first = at.session_state["session_id"]
    at.button(key="new-session").click().run()
    assert not at.exception
    assert at.session_state["session_id"] != first
    assert not at.tabs  # the new conversation is empty
    at.button(key=f"open-{first}").click().run()
    assert at.session_state["session_id"] == first
    assert len(at.tabs) == 4  # the earlier answer is back


@pytest.mark.parametrize(
    ("page", "title"), [("app_pages/data.py", "The data"), ("app_pages/method.py", "How it works")]
)
def test_reference_pages_open_with_the_team_footer(app_env, page, title):
    at = _app()
    at.run()
    at.switch_page(page).run()
    assert not at.exception
    assert at.title[1].value == title
    assert any("Mina Naseh (PwC)" in c.value for c in at.caption)  # footer on every page


def test_presentation_mode_steps_through_the_slides_and_closes(app_env):
    at = _app()
    at.run()
    at.button(key="present-btn").click().run()
    assert not at.exception
    assert not at.tabs  # the page's tabs are replaced by the slides
    assert at.button(key="deck-back").disabled
    shown = 1
    while not at.button(key="deck-next").disabled:
        at.button(key="deck-next").click().run()
        assert not at.exception
        shown += 1
    assert shown == 11  # challenge, tool, title, five findings, conclusion, options, team
    # Save as PDF: every slide laid out for the print dialog, then back to the slides
    at.button(key="deck-pdf").click().run()
    assert not at.exception
    assert at.button(key="deck-print-back")
    at.button(key="deck-print-back").click().run()
    assert not at.exception and at.button(key="deck-close")
    at.button(key="deck-close").click().run()
    assert at.title[1].value == "Luxembourg's trade in goods at a glance"
