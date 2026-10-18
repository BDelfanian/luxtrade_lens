"""The LinkedIn share card: sizes, layout fallbacks, the caption and localisation."""

import io
from datetime import date

import pytest
from PIL import Image

from luxtrade.agents.evidence import EvidenceFigure
from luxtrade.runs.scenarios import ScenarioRecord
from luxtrade.viz.share_card import (
    REPO,
    CardContent,
    content_from,
    data_note,
    first_sentence,
    linkedin_post,
    render_card,
)

FIGURE = EvidenceFigure(
    kind="change",
    title="Iron and steel vs all exports: change in each period",
    flow="export",
    steps=[1, 2],
    rows=[
        {"group": "2008 → 2009", "series": "Iron and steel", "value": -48.4, "step": 1},
        {"group": "2008 → 2009", "series": "All exports", "value": -12.4, "step": 1},
        {"group": "2019 → 2020", "series": "Iron and steel", "value": -26.0, "step": 2},
        {"group": "2019 → 2020", "series": "All exports", "value": -17.0, "step": 2},
    ],
    tiles=[
        {"value": "2 / 2", "label": "Iron and steel: periods with falling exports", "tone": "down"},
        {"value": "−48.4 %", "label": "Iron and steel, 2008 → 2009", "detail": "all: −12.4 %"},
    ],
)


def record(**changes: object) -> ScenarioRecord:
    values = {
        "scenario_id": "abc1234567",
        "session_id": "s1",
        "created_at": "2026-10-16T22:25:40+00:00",
        "question": "Which products break first in a crisis?",
        "headline": "Iron and steel exports fall first and furthest in every crisis.",
        "points": [{"text": "Iron and steel fell 48.4 % in 2009.", "steps": [1]}],
        "conclusion": "Iron and steel is the most exposed. Goods only, not services.",
        "steps": [
            {"n": 1, "kind": "plan", "question": "q1"},
            {"n": 2, "kind": "plan", "question": "q2"},
        ],
    } | changes
    return ScenarioRecord(**values)


def content(**changes: object) -> CardContent:
    return content_from(record(**changes), [FIGURE], "data to Jun 2026")


def size_of(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


@pytest.mark.parametrize(
    ("size", "expected"), [("portrait", (1080, 1350)), ("square", (1080, 1080))]
)
def test_the_card_has_the_linkedin_sizes(size, expected):
    assert size_of(render_card(content(), size, scale=1)) == expected
    assert size_of(render_card(content(), size)) == (expected[0] * 2, expected[1] * 2)


def test_a_card_without_a_chart_shows_the_key_points():
    c = content_from(record(points=[{"text": f"Point {k}. " * 30} for k in range(6)]), [], "x")
    assert c.figure is None and c.tiles == []
    for size in ("portrait", "square"):
        assert size_of(render_card(c, size, scale=1)) > (0, 0)


def test_long_words_and_texts_do_not_break_the_layout():
    long = "Luxembourg's exports of electrical machinery and equipment " * 8
    c = content(headline=long, question=long, conclusion=long)
    for size in ("portrait", "square"):
        render_card(c, size, scale=1)


def test_the_content_comes_from_the_record_and_its_first_figure():
    c = content()
    assert c.headline.startswith("Iron and steel exports fall first")
    assert c.takeaway == "Iron and steel is the most exposed."  # the first sentence only
    assert c.tiles == FIGURE.tiles and c.figure["rows"] == FIGURE.rows
    assert c.when == date(2026, 10, 16) and c.scenario_id == "abc1234567"


def test_first_sentence():
    assert first_sentence("Imports rose 5.2 %. Exports fell.") == "Imports rose 5.2 %."
    assert first_sentence("One sentence only") == "One sentence only"


def test_the_data_note_is_localised():
    assert data_note(date(2026, 6, 1)) == "data to Jun 2026"
    assert data_note(date(2026, 6, 1), "de") == "Daten bis Juni 2026"
    assert data_note(date(2026, 6, 1), "fr") == "données jusqu'à juin 2026"


def test_the_caption_repeats_the_checked_words_and_says_how():
    post = linkedin_post(content(), steps=2)
    assert post.startswith("Iron and steel exports fall first")
    assert "▪ 2 / 2: Iron and steel: periods with falling exports" in post
    assert "▪ −48.4 %: Iron and steel, 2008 → 2009 (all: −12.4 %)" in post
    assert "Which products break first in a crisis?" in post
    assert "2 precise questions" in post and "Comext DS-045409" in post
    assert "scenario abc1234567, data to Jun 2026" in post
    assert f"https://{REPO}" in post and "#OpenData" in post


def test_the_caption_follows_the_scenario_language():
    post = linkedin_post(content(language="fr"), steps=2)
    assert "Comment : j'ai demandé à LuxTrade Lens" in post and "Open source :" in post
