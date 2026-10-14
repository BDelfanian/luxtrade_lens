import pandas as pd

from luxtrade.runs.store import make_run_id, result_hash


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
