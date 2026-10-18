"""A scenario's answer as the title and subtitle of a post, for its share card.

The checked answer reads like a report ("During financial crises, Luxembourg's exports and
imports of Iron and steel are the most vulnerable product category compared to others."). A
post needs a short title that states the insight, and a subtitle that carries the question and
the evidence. The language model rewrites the checked answer and nothing else; code then checks
that every number, year and country is in the answer or its key figures, that nothing observed
is called projected, and the lengths. One redraft (shown its draft and problems); a passing
title is kept with the checked headline as subtitle; else the checked headline is the title.
"""

import json
import re

from pydantic import BaseModel, Field

from luxtrade.agents.evidence import EvidenceFigure
from luxtrade.agents.grounding import (
    describes_future,
    numbers_in,
    parse_numbers,
    partners_named,
    plain_numbers,
    unknown_partners,
    unsupported_numbers,
)
from luxtrade.agents.interpret import prompt
from luxtrade.agents.llm import LLMError
from luxtrade.runs.scenarios import ScenarioRecord
from luxtrade.viz.share_card import first_sentence

MAX_TITLE, MAX_SUBTITLE = 90, 220
MAX_FIGURES = {"title": 1, "subtitle": 4}  # statistics, years not counted: a card is not a table
_CODES = re.compile(r"\b[A-Za-z]+-?\d+\b")  # EU27, HS4, CN8, G7: part of a name


class ShareText(BaseModel):
    """The post's words: written by the language model from the checked answer."""

    basis: str = Field(description="The sentences of ANSWER the title and subtitle restate.")
    title: str = Field(description="The insight as a short statement.")
    subtitle: str = Field(description="One sentence: the question's context and the evidence.")


def answer_texts(record: ScenarioRecord, figures: list[EvidenceFigure]) -> list[str]:
    """Everything the share text may draw on: the checked answer and the figures of the card."""
    texts = [record.question, record.headline, record.conclusion]
    texts += [p["text"] for p in record.points]
    for fig in figures[:1]:
        texts += [fig.title] + [str(r["group"]) for r in fig.rows]
        texts += [t.get(k) or "" for t in fig.tiles for k in ("value", "label", "detail")]
    return texts


def review_share(
    text: ShareText,
    record: ScenarioRecord,
    figures: list[EvidenceFigure],
    sem: object,
    user: bool = False,
) -> list[str]:
    """Problems of a drafted title and subtitle; empty if they may go on the card.

    ``user``: the user's own words, checked the same way, except that a question may be a hook.
    """
    lang = record.language
    texts = answer_texts(record, figures)
    allowed = numbers_in(texts, lang)
    named = set(partners_named(" ".join(texts), sem, lang))
    found = [] if text.title.strip() else ["the title is empty"]
    for label, part, most in (
        ("title", text.title, MAX_TITLE),
        ("subtitle", text.subtitle, MAX_SUBTITLE),
    ):
        if len(part) > most:
            found.append(f"{label}: {len(part)} characters, at most {most}")
        if "?" in part and not user:
            found.append(f"{label}: a question, not a statement")
        bare = _CODES.sub(" ", plain_numbers(part))  # "EU27", "HS4": names, not figures
        figures_in = [v for v, d in parse_numbers(bare, lang) if d or not 1900 <= v <= 2100]
        if len(figures_in) > MAX_FIGURES[label]:
            listed = ", ".join(f"{v:g}" for v in figures_in)
            found.append(
                f"{label}: {len(figures_in)} figures ({listed}), at most {MAX_FIGURES[label]}; "
                "keep one or two that carry the insight and say the rest in words (e.g. "
                '"fell in all three crises", "about three times as far")'
            )
        found += [f"{label}: {p}" for p in unsupported_numbers(part, allowed, lang)]
        found += [f"{label}: {p}" for p in unknown_partners(part, named, sem, lang)]
        if describes_future(part) and not describes_future(" ".join(texts)):
            found.append(f"{label}: observed data described as projected or expected")
    return found


def write_share(
    llm: object | None,
    record: ScenarioRecord,
    figures: list[EvidenceFigure],
    sem: object,
    avoid: list[str] | None = None,
) -> tuple[ShareText, str, list[str]]:
    """The title and subtitle, their source ("llm" or "template") and the check notes.

    ``avoid``: titles already written, for a new one (the model runs at temperature 0).
    """
    fallback = ShareText(
        basis="", title=record.headline, subtitle=first_sentence(record.conclusion)
    )
    if llm is None or not record.headline or record.status == "failed":
        return fallback, "template", ["no language model: the card uses the checked headline"]
    answer = {
        "headline": record.headline,
        "points": [p["text"] for p in record.points],
        "conclusion": record.conclusion,
    }
    tiles = figures[0].tiles if figures else []
    user = "\n\n".join(
        [
            f"QUESTION: {record.question}",
            f"LANGUAGE: {record.language}",
            "ANSWER:\n" + json.dumps(answer, ensure_ascii=False, indent=1),
            "KEY FIGURES:\n"
            + (
                "\n".join(
                    f"- {t['value']}: {t['label']}"
                    + (f" ({t['detail']})" if t.get("detail") else "")
                    for t in tiles
                )
                or "none"
            ),
        ]
    )
    if avoid:
        user += "\n\nTITLES ALREADY WRITTEN (write a different one):\n- " + "\n- ".join(avoid)
    notes: list[str] = []
    problems: list[str] = []
    kept_title = ""
    previous: dict = {}
    for _ in range(2):
        draft = user
        if problems:
            draft += "\n\nPREVIOUS DRAFT:\n" + json.dumps(previous, ensure_ascii=False)
            draft += "\n\nPROBLEMS in the previous draft:\n- " + "\n- ".join(problems)
        try:
            out = llm.parse(
                step="scenario_share",
                system=prompt("scenario_share"),
                user=draft,
                schema=ShareText,
            )
        except LLMError as exc:
            notes.append(f"share text LLM failed: {exc}")
            break
        problems = review_share(out, record, figures, sem)
        if not problems:
            notes.append("share title and subtitle passed the number, country and wording checks")
            return out, "llm", notes
        notes.append("share text check failed: " + "; ".join(problems))
        previous = {"title": out.title, "subtitle": out.subtitle}
        if not any(p.startswith(("title", "the title")) for p in problems):
            kept_title = out.title
    if kept_title:  # the subtitle failed twice: the checked headline carries the answer
        notes.append("share title kept; the checked headline is the subtitle")
        return ShareText(basis="", title=kept_title, subtitle=record.headline), "llm", notes
    notes.append("share card falls back to the checked headline")
    return fallback, "template", notes
