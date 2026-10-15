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
    assert [t.label for t in at.tabs] == ["Key findings", "At a glance"]
    # key findings: five cards, four with a headline figure, each opening its details
    assert len(at.metric) == 4
    assert [b.key for b in at.button if (b.key or "").startswith("more-")] == [
        "more-diversification",
        "more-shocks",
        "more-europe",
        "more-prices",
        "more-conclusion",
    ]
    # at a glance: the five business questions
    assert len(at.main.subheader) == 5
    assert any(b.key == "explore-partners" for b in at.button)


@pytest.mark.parametrize("key", ["diversification", "shocks", "europe", "prices", "conclusion"])
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
