"""Investigation trails: definitions, number checks and loading stored runs."""

from luxtrade.agents import trails
from luxtrade.runs.store import RunRecord, RunStore

FINDING_KEYS = {"diversification", "shocks", "europe", "prices", "composition", "conclusion"}


def record(run_id: str, facts: list[str], **extra) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        session_id="s1",
        turn=1,
        created_at="2026-10-16T00:00:00+00:00",
        origin="ask",
        status="answered",
        question="q",
        facts=[{"key": str(i), "text": t} for i, t in enumerate(facts)],
        **extra,
    )


def test_every_finding_has_a_trail_of_several_questions():
    defs = trails.definitions()
    assert set(defs) == FINDING_KEYS
    assert all(len(t.steps) >= 3 and t.synthesis for t in defs.values())


def test_check_finds_numbers_in_facts_and_ranked_rows():
    rec = record(
        "r1",
        ["exports Iron and steel: 2.67 bn € 2008 → 1.38 bn € 2009 (-1.29 bn €, −48.4 %)"],
        frames={"main": [{"label": "China", "share": 3.0333}]},
    )
    assert trails.check(rec, ["-48.4 %", "China: 3.0 %", "99.9 %"]) == {
        "-48.4 %": True,
        "China: 3.0 %": True,
        "99.9 %": False,
    }


def test_load_joins_definitions_index_and_runs(tmp_path, monkeypatch):
    runs = RunStore(root=tmp_path, demo_root=tmp_path)
    trail = trails.definitions()["composition"]
    steps = []
    for n, _ in enumerate(trail.steps):
        runs.save(record(f"r{n}", ["x"]))
        steps.append(trails.BuiltStep(run_id=f"r{n}", status="answered"))
    built = trails.BuiltTrail(session_id="s1", built_at="2026-10-16", code_version="x", steps=steps)
    (tmp_path / "trails").mkdir()
    (tmp_path / "trails" / "composition.json").write_text(built.model_dump_json())
    monkeypatch.setattr(trails, "INDEX_DIR", tmp_path / "trails")
    view = trails.load("composition", runs)
    assert view is not None and [r.run_id for _, _, r in view.steps] == ["r0", "r1", "r2", "r3"]
    assert trails.load("shocks", runs) is None  # never built: the dialog says so
