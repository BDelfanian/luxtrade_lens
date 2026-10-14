import logging

from luxtrade.logging_setup import timed


def test_timed_returns_result_and_logs(caplog):
    @timed
    def add(a, b):
        return a + b

    with caplog.at_level(logging.INFO):
        assert add(2, 3) == 5
    assert "start add" in caplog.text
    assert "end add" in caplog.text
