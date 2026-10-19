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
        "title": "Crisis exposure of products",
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
    # without share text: the checked headline, and the conclusion's first sentence below it
    assert c.title.startswith("Iron and steel exports fall first")
    assert c.subtitle == "Iron and steel is the most exposed."
    assert c.topic == "Crisis exposure of products"
    assert c.tiles == FIGURE.tiles and c.figure["rows"] == FIGURE.rows


def test_the_share_text_leads_the_card():
    share = {"title": "Iron and steel takes the hardest hit", "subtitle": "In 2009 it fell 48.4 %."}
    c = content_from(record(), [FIGURE], "data to Jun 2026", share)
    assert (c.title, c.subtitle) == (share["title"], share["subtitle"])
    assert c.question == "Which products break first in a crisis?"  # for the caption only


def test_first_sentence():
    assert first_sentence("Imports rose 5.2 %. Exports fell.") == "Imports rose 5.2 %."
    assert first_sentence("One sentence only") == "One sentence only"


def test_the_data_note_is_localised():
    assert data_note(date(2026, 6, 1)) == "data to Jun 2026"
    assert data_note(date(2026, 6, 1), "de") == "Daten bis Juni 2026"
    assert data_note(date(2026, 6, 1), "fr") == "données jusqu'à juin 2026"


def test_the_caption_repeats_the_checked_words_and_says_how():
    share = {"title": "Iron and steel takes the hardest hit", "subtitle": "In 2009 it fell 48.4 %."}
    post = linkedin_post(content_from(record(), [FIGURE], "data to Jun 2026", share), steps=2)
    assert post.startswith("Iron and steel takes the hardest hit\n\nIn 2009 it fell 48.4 %.")
    assert "▪ 2 / 2: Iron and steel: periods with falling exports" in post
    assert "▪ −48.4 %: Iron and steel, 2008 → 2009 (all: −12.4 %)" in post
    assert "Which products break first in a crisis?" in post
    assert "2 precise questions" in post and "Comext DS-045409" in post
    assert "(data to Jun 2026)" in post and "abc1234567" not in post  # no scenario ID
    assert f"https://{REPO}" in post and "#OpenData" in post


def test_the_caption_follows_the_scenario_language():
    post = linkedin_post(content(language="fr"), steps=2)
    assert "Comment : j'ai demandé à LuxTrade Lens" in post and "Open source :" in post


def test_a_concentration_figure_is_drawn_as_small_multiples():
    rows = [
        {"group": y, "series": f"{flow} by {dim}", "value": v, "step": k, "flow": flow, "dim": dim}
        for k, (flow, dim, values) in enumerate(
            [
                ("Exports", "product", (1374, 1028, 764, 620, 602)),
                ("Exports", "partner", (1091, 1041, 1169, 1273, 1281)),
                ("Imports", "product", (880, 617, 621, 554, 562)),
                ("Imports", "partner", (1561, 1809, 1615, 2061, 1882)),
            ],
            start=1,
        )
        for y, v in zip((2005, 2010, 2015, 2020, 2025), values, strict=True)
    ]
    tiles = [{"value": "602", "label": f"Panel {k}, 2025", "tone": "up"} for k in range(4)]
    figure = {"kind": "concentration", "title": "Concentration (HHI), 2005–2025", "rows": rows}
    c = content_from(record(), [], "data to Jun 2026")
    c.figure, c.tiles = figure, tiles  # four tiles: one per panel
    for size, expected in (("portrait", (1080, 1350)), ("square", (1080, 1080))):
        assert size_of(render_card(c, size, scale=1)) == expected


def test_a_question_cut_short_is_not_a_topic():
    asked = (
        "Is Luxembourg's trade shifting from extra-EU to intra-EU partners between 2005 and 2025?"
    )
    own_chain = record(question=asked, title=asked[:60])  # no planner title: the question's start
    assert content_from(own_chain, [], "x").topic == ""
    assert content_from(
        own_chain.model_copy(update={"name": "Intra vs extra EU"}), [], "x"
    ).topic == ("Intra vs extra EU")
    assert content_from(record(), [], "x").topic == "Crisis exposure of products"


def test_series_panels_are_drawn_each_on_its_own_scale():
    rows = [
        {"group": y, "series": name, "value": v, "step": k, "flow": "import", "unit": "share"}
        for k, (name, values) in enumerate(
            [("EU27 countries, share of imports", (70.3, 75.0, 86.6)), ("Japan", (0.7, 0.9, 4.5))]
        )
        for y, v in zip((2005, 2015, 2025), values, strict=True)
    ]
    c = content_from(record(), [], "data to Jun 2026")
    c.figure = {"kind": "series", "title": "Year by year, 2005–2025", "rows": rows}
    assert size_of(render_card(c, "square", scale=1)) == (1080, 1080)


def test_long_tile_labels_keep_their_year():
    c = content_from(record(), [FIGURE], "data to Jun 2026")
    c.tiles = [
        {"value": "19.71 €/kg", "label": "Non-EU27 countries, imports: value per kg, 2025"}
    ] * 4
    for size in ("portrait", "square"):
        render_card(c, size, scale=1)


def test_a_projection_is_drawn_with_its_band_and_method_line():
    rows = []
    for flow, base in (("export", 1.3e9), ("import", 2.0e9)):
        for i in range(48):
            ahead = i >= 30
            value = base * (1 + 0.1 * (i % 12 == 2) - 0.12 * (i % 12 == 7))
            rows.append(
                {
                    "group": 2024 + i / 12,
                    "series": flow.title() + "s",
                    "value": value,
                    "lo80": value * 0.8 if ahead else None,
                    "hi80": value * 1.25 if ahead else None,
                    "kind": "projection" if ahead else "actual",
                    "flow": flow,
                    "step": 1,
                    "unit": "value_eur",
                }
            )
    c = content_from(record(), [], "data to Jun 2026")
    c.figure = {
        "kind": "projection",
        "title": "Observed and projected, monthly, 2024–2027",
        "rows": rows,
        "caption": "ETS on log values, damped trend, monthly season: Exports α 0.50, φ 0.98",
    }
    for size, expected in (("portrait", (1080, 1350)), ("square", (1080, 1080))):
        assert size_of(render_card(c, size, scale=1)) == expected
