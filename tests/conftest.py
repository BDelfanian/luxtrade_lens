import json

import pytest
from fixtures.comext import bulk_raw  # noqa: F401  (synthetic Comext archives)

from luxtrade.agents.llm import FakeLLM
from luxtrade.agents.service import Assistant
from luxtrade.agents.spec import InsightOutput
from luxtrade.config import DUCKDB_FILE
from luxtrade.process.placeholder import SMALL, write_placeholder
from luxtrade.runs.sessions import SessionStore
from luxtrade.runs.store import RunStore
from luxtrade.semantic.build import build_database
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.semantic.lookup import EntityIndex


@pytest.fixture(scope="session")
def processed_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("processed")
    write_placeholder(out, SMALL)
    build_database(out)
    return out


@pytest.fixture(scope="session")
def semantic(processed_dir):
    return SemanticLayer(processed_dir / DUCKDB_FILE)


@pytest.fixture(scope="session")
def index(semantic):
    return EntityIndex(semantic)


@pytest.fixture
def stores(tmp_path):
    runs = RunStore(tmp_path / "runs", tmp_path / "demo")
    return runs, SessionStore(runs, tmp_path / "sessions", tmp_path / "demo_sessions")


@pytest.fixture
def make_assistant(semantic, stores):
    runs, sessions = stores

    def _make(llm=None):
        return Assistant(sem=semantic, llm=llm, runs=runs, sessions=sessions)

    return _make


def insight_from_facts(user: str) -> InsightOutput:
    """A well-behaved fake insight writer: copies fact texts verbatim (always grounded)."""
    payload = user.split("FACT SHEET:\n", 1)[1].split("\n\nPROBLEMS", 1)[0]
    facts = json.loads(payload)["facts"]
    return InsightOutput(sentences=[f"{f['text']}." for f in facts[:4]] or ["No data."])


@pytest.fixture
def fake_llm():
    def _make(**responses):
        responses.setdefault("insight", insight_from_facts)
        return FakeLLM(responses=responses)

    return _make
