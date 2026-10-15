import pandas as pd

from luxtrade.runs.store import RunRecord, make_run_id, result_hash


def test_run_id_is_deterministic_and_content_addressed():
    args = dict(
        session_id="abc123",
        turn=1,
        question="Main partners?",
        spec={"intent": "ranking"},
        sql="SELECT 1",
        vintage="2026-10-14",
    )
    assert make_run_id(**args) == make_run_id(**{**args, "question": "  main PARTNERS? "})
    assert make_run_id(**args) != make_run_id(**{**args, "sql": "SELECT 2"})
    assert make_run_id(**args) != make_run_id(**{**args, "session_id": "other1"})
    assert len(make_run_id(**args)) == 10


def test_result_hash_ignores_row_and_column_order():
    a = pd.DataFrame({"key": ["DE", "FR"], "value": [1.0, 2.0]})
    b = pd.DataFrame({"value": [2.0, 1.0], "key": ["FR", "DE"]})
    assert result_hash(a) == result_hash(b)
    assert result_hash(a) != result_hash(a.assign(value=[1.0, 2.5]))


def _record(run_id: str, session_id: str, created_at: str, language: str = "en") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        session_id=session_id,
        turn=1,
        created_at=created_at,
        origin="ask",
        status="answered",
        question=f"Question {run_id}?",
        language=language,
    )


def test_sessions_keep_language_and_last_activity(stores):
    runs, sessions = stores
    for rec in (
        _record("r1", "aaaaaa", "2026-10-14T09:00:00+00:00", "fr"),
        _record("r2", "bbbbbb", "2026-10-14T10:00:00+00:00"),
        _record("r3", "aaaaaa", "2026-10-15T08:00:00+00:00", "en"),  # follow-up, next day
    ):
        runs.save(rec)
        sessions.append(rec)
    first = sessions.get("aaaaaa")
    assert first.language == "fr"  # the language of the first question
    assert first.last_active == "2026-10-15T08:00:00+00:00"
    # most recently active first, and findable by the date of any activity
    assert [s.session_id for s in sessions.recent()] == ["aaaaaa", "bbbbbb"]
    assert [s.session_id for s in sessions.search("2026-10-15")] == ["aaaaaa"]


def test_older_session_files_are_completed_from_their_runs(stores):
    runs, sessions = stores
    rec = _record("r9", "oldone", "2026-10-13T12:00:00+00:00", "de")
    runs.save(rec)
    # a session file as written before 15 Oct 2026: no language, no last activity
    legacy = '{"session_id": "oldone", "created_at": "2026-10-13T11:59:00+00:00", "runs": ["r9"]}'
    (sessions.root / "oldone.json").write_text(legacy, encoding="utf-8")
    (found,) = sessions.recent()
    assert (found.language, found.last_active) == ("de", "2026-10-13T12:00:00+00:00")
    # the shared file is left as it was
    assert "updated_at" not in (sessions.root / "oldone.json").read_text(encoding="utf-8")
