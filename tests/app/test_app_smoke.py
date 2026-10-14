import pytest
from streamlit.testing.v1 import AppTest

from luxtrade import config


@pytest.fixture
def app_env(processed_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", processed_dir / config.DUCKDB_FILE)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "DEMO_RUNS_DIR", tmp_path / "demo")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("luxtrade.agents.llm.default_llm", lambda: None)


def test_app_loads_and_answers_a_preset(app_env):
    at = AppTest.from_file(str(config.ROOT_DIR / "src/luxtrade/app/Home.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("Placeholder data" in w.value for w in at.sidebar.warning)
    at.button(key="preset-Q1").click().run()
    assert not at.exception
    assert len(at.tabs) == 4
    assert any("largest partner" in m.value for m in at.markdown)
