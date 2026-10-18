"""The scenario history: rename, favourites, delete, and when a scenario was made."""

from datetime import datetime

from luxtrade.runs.scenarios import ScenarioRecord, ScenarioStore


def record(sid: str, created_at: str = "2026-10-18T18:26:27+00:00", **changes) -> ScenarioRecord:
    values = {
        "scenario_id": sid,
        "session_id": "s1",
        "created_at": created_at,
        "question": "How concentrated is Luxembourg's trade?",
        "title": "HHI Concentration Trends",
    } | changes
    return ScenarioRecord(**values)


def stores(tmp_path) -> ScenarioStore:
    return ScenarioStore(tmp_path / "own", tmp_path / "demo")


def test_a_scenario_shows_its_name_else_its_title_else_its_question():
    assert record("a").label == "HHI Concentration Trends"
    assert record("a", name="Weekly post 42").label == "Weekly post 42"
    assert record("a", title="").label == "How concentrated is Luxembourg's trade?"


def test_the_creation_time_is_shown_in_local_time():
    rec = record("a")
    local = datetime.fromisoformat(rec.created_at).astimezone()
    assert rec.created_local == f"{local:%Y-%m-%d %H:%M}"


def test_rename_and_favourite_are_kept(tmp_path):
    store = stores(tmp_path)
    store.save(record("a"))
    store.rename("a", "  HHI,   every five years ")
    store.set_favorite("a", True)
    kept = store.load("a")
    assert (kept.name, kept.favorite, kept.title) == (
        "HHI, every five years",
        True,
        "HHI Concentration Trends",  # the planner's title stays in the record
    )
    store.rename("a", "")
    assert store.load("a").label == "HHI Concentration Trends"


def test_an_own_scenario_is_deleted_for_good(tmp_path):
    store = stores(tmp_path)
    store.save(record("a"))
    store.save(record("b", created_at="2026-10-18T19:00:00+00:00"))
    assert store.delete("a") is True
    assert store.load("a") is None and not (tmp_path / "own" / "a.json").exists()
    assert [r.scenario_id for r in store.recent()] == ["b"]
    assert store.delete("missing") is False


def test_a_recorded_example_is_hidden_not_deleted(tmp_path):
    store = stores(tmp_path)
    example = ScenarioStore(tmp_path / "demo")  # the examples folder, as shipped
    example.save(record("ex"))
    assert store.is_example("ex") and [r.scenario_id for r in store.recent()] == ["ex"]
    assert store.delete("ex") is True
    assert (tmp_path / "demo" / "ex.json").exists()  # read-only: the file stays
    assert store.recent() == []  # but it is out of the history
    assert store.load("ex").hidden  # and still opens from a link
