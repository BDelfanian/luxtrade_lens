"""The share card's title and subtitle: written from the checked answer, checked, then kept."""

import pytest

from luxtrade.agents.evidence import EvidenceFigure
from luxtrade.agents.llm import FakeLLM, LLMError
from luxtrade.agents.scenario import ScenarioBuilder
from luxtrade.agents.share import ShareText, review_share, write_share
from luxtrade.runs.scenarios import ScenarioRecord, ScenarioStore

FIGURE = EvidenceFigure(
    kind="change",
    title="Iron and steel vs all exports: change in each period",
    flow="export",
    steps=[1],
    rows=[{"group": "2008 → 2009", "series": "Iron and steel", "value": -48.4, "step": 1}],
    tiles=[{"value": "3.0 ×", "label": "as far as all exports, on average", "tone": "down"}],
)
GOOD = ShareText(
    basis="headline",
    title="Iron and steel takes the hardest hit when crises strike",
    subtitle="In 2009 iron and steel exports to Germany fell 48.4 %, 3.0 × as far as all exports.",
)


def record(**changes: object) -> ScenarioRecord:
    values = {
        "scenario_id": "abc1234567",
        "session_id": "s1",
        "created_at": "2026-10-16T22:25:40+00:00",
        "question": "Which products break first in a crisis?",
        "headline": "Iron and steel exports fall furthest in crises.",
        "points": [{"text": "Exports to Germany fell 48.4 % in 2009.", "steps": [1]}],
        "conclusion": "Iron and steel is the most exposed. Goods only.",
    } | changes
    return ScenarioRecord(**values)


def share_text(**changes: str) -> ShareText:
    return GOOD.model_copy(update=changes)


def test_a_restatement_of_the_answer_passes(semantic):
    assert review_share(GOOD, record(), [FIGURE], semantic) == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"subtitle": "Exports fell 52.0 % in 2009."}, "number 52 is not in the facts"),
        ({"subtitle": "Exports to the United States fell."}, "partner United States"),
        ({"subtitle": "Exports are expected to fall in 2009."}, "projected or expected"),
        ({"title": "Which products break first?"}, "a question, not a statement"),
        ({"title": "Iron and steel " * 10}, "characters, at most 90"),
        ({"title": "Iron and steel fell 48.4 % and 3.0 ×"}, "2 figures (48.4, 3), at most 1"),
        ({"title": ""}, "the title is empty"),
    ],
)
def test_the_checks_catch_what_the_answer_does_not_say(semantic, changes, problem):
    found = review_share(share_text(**changes), record(), [FIGURE], semantic)
    assert any(problem in p for p in found), found


def test_too_many_figures_in_the_subtitle_ask_for_words(semantic):
    rec = record(
        points=[{"text": "Falls of 48.4 %, 26.0 %, 27.1 %, 50.2 % and 19.9 %.", "steps": [1]}]
    )
    text = share_text(subtitle="Falls of 48.4 %, 26.0 %, 27.1 %, 50.2 % and 19.9 % in 2009.")
    (problem,) = review_share(text, rec, [FIGURE], semantic)
    assert "5 figures" in problem and "say the rest in words" in problem


def test_a_failing_draft_is_redrafted_with_its_problems(semantic):
    llm = FakeLLM(responses={"scenario_share": [share_text(subtitle="It fell 61.0 %."), GOOD]})
    text, source, notes = write_share(llm, record(), [FIGURE], semantic)
    assert (text, source) == (GOOD, "llm")
    redraft = llm.calls[1][1]
    assert "PREVIOUS DRAFT" in redraft and "It fell 61.0 %." in redraft
    assert "number 61 is not in the facts" in redraft
    assert notes[-1].startswith("share title and subtitle passed")


def test_a_passing_title_is_kept_when_the_subtitle_fails_twice(semantic):
    bad = share_text(subtitle="It fell 61.0 %.")
    llm = FakeLLM(responses={"scenario_share": [bad, bad]})
    text, source, _ = write_share(llm, record(), [FIGURE], semantic)
    assert source == "llm" and text.title == GOOD.title
    assert text.subtitle == "Iron and steel exports fall furthest in crises."  # the headline


def test_without_a_usable_draft_the_checked_headline_is_the_title(semantic):
    for llm in (None, FakeLLM(responses={"scenario_share": LLMError("down")})):
        text, source, _ = write_share(llm, record(), [FIGURE], semantic)
        assert source == "template"
        assert text.title == "Iron and steel exports fall furthest in crises."
        assert text.subtitle == "Iron and steel is the most exposed."


def test_the_share_text_is_kept_in_the_record_and_renewed_on_request(make_assistant, tmp_path):
    second = share_text(title="Crises hit iron and steel exports hardest")
    llm = FakeLLM(responses={"scenario_share": [GOOD, second]})
    store = ScenarioStore(tmp_path / "scn", tmp_path / "demo")
    builder = ScenarioBuilder(make_assistant(llm), store)
    rec = record()
    store.save(rec)

    first = builder.share(rec)
    assert first["title"] == GOOD.title and first["source"] == "llm"
    kept = store.load(rec.scenario_id)
    assert kept.share["title"] == GOOD.title
    assert kept.llm_usage[-1]["step"] == "scenario_share"
    assert builder.share(kept) == kept.share and len(llm.calls) == 1  # written once

    renewed = builder.share(kept, renew=True)
    assert renewed["title"] == second.title and renewed["earlier"] == [GOOD.title]
    assert f"TITLES ALREADY WRITTEN (write a different one):\n- {GOOD.title}" in llm.calls[1][1]


def test_offline_the_headline_is_used_and_nothing_is_kept(make_assistant, tmp_path):
    store = ScenarioStore(tmp_path / "scn", tmp_path / "demo")
    builder = ScenarioBuilder(make_assistant(None), store)
    rec = record()
    store.save(rec)
    assert builder.share(rec)["source"] == "template"
    assert store.load(rec.scenario_id).share == {}
