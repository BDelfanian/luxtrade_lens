"""Grounding check: every number and partner in the insight must come from the fact sheet."""

import re

from luxtrade.agents.facts import FactSheet
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.semantic.lookup import normalise

_NUM = {
    "en": re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"),
    "fr": re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?"),
    "de": re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"),
}


# observed years written as forecasts ("exports are projected to reach … in 2025", seen on real
# data): only a fact sheet with a projection may use these words
_FUTURE = re.compile(
    r"\b(projected|expected to|forecast to|will (?:reach|be|represent|make up|remain)|"
    r"devrai(?:t|ent)|prévu(?:e|es|s)? |voraussichtlich|werden .{0,40} erreichen)\b",
    re.IGNORECASE,
)


def parse_numbers(text: str, lang: str) -> list[tuple[float, int]]:
    """Numbers in ``text`` as (value, decimals), parsed with the locale's separators."""
    out = []
    for m in _NUM.get(lang, _NUM["en"]).finditer(text):
        raw = m.group(0)
        if lang == "en":
            raw = raw.replace(",", "")
        elif lang == "fr":
            raw = re.sub(r"[   ]", "", raw).replace(",", ".")
        else:
            raw = raw.replace(".", "").replace(",", ".")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append((float(raw), decimals))
    return out


def _matches(value: float, decimals: int, allowed: list[float]) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(value - a) <= tol or abs(value - round(a, decimals)) <= 1e-9 for a in allowed)


ALWAYS_ALLOWED = [float(n) for n in range(0, 13)] + [100.0, 80.0, 95.0]


def supports(value: float, decimals: int, allowed: list[float]) -> bool:
    """True if ``value``, written with ``decimals``, is one of ``allowed`` at that rounding."""
    return _matches(value, decimals, allowed)


def numbers_in(texts: list[str], lang: str) -> list[float]:
    """Every number written in ``texts``: what a grounded text may quote."""
    return [v for t in texts for v, _ in parse_numbers(t, lang)]


_YEAR_SPAN = re.compile(r"\b((?:19|20)\d{2})\s*([–-])\s*(\d{2})\b")
_EVENT_NUMBERS = re.compile(r"\bCOVID-19\b", re.IGNORECASE)


def plain_numbers(text: str) -> str:
    """``text`` as the number checks read it: '2022–23' → '2022–2023', 'COVID-19' → 'COVID'.

    Seen on real data: "the 2022–23 aftershock" failed as the number 23, "COVID-19" as 19.
    """
    text = _EVENT_NUMBERS.sub("COVID", text)
    return _YEAR_SPAN.sub(lambda m: f"{m[1]}{m[2]}{m[1][:2]}{m[3]}", text)


def unsupported_numbers(text: str, allowed: list[float], lang: str) -> list[str]:
    """Problems for each number in ``text`` that is not in ``allowed`` (at its rounding)."""
    return [
        f"number {value:g} is not in the facts"
        for value, decimals in parse_numbers(plain_numbers(text), lang)
        if not _matches(value, decimals, allowed + ALWAYS_ALLOWED)
    ]


def partners_named(text: str, sem: SemanticLayer, lang: str) -> dict[str, str]:
    """The partner countries named in ``text``, as {code: label}."""
    norm = f" {normalise(text)} "
    col = {"en": "label_en", "fr": "label_fr", "de": "label_de"}.get(lang, "label_en")
    return {
        code: str(row[col])
        for code, row in sem.partners.iterrows()
        if not row["is_special"] and f" {normalise(str(row[col]))} " in norm
    }


def unknown_partners(text: str, allowed: set[str], sem: SemanticLayer, lang: str) -> list[str]:
    """Problems for each partner country named in ``text`` whose code is not in ``allowed``."""
    return [
        f"partner {label} is not in the result"
        for code, label in partners_named(text, sem, lang).items()
        if code not in allowed
    ]


def describes_future(text: str) -> bool:
    """True if ``text`` calls something projected, expected or forecast."""
    return bool(_FUTURE.search(text))


def check(sentences: list[str], sheet: FactSheet, sem: SemanticLayer) -> list[str]:
    """Return the grounding problems found (empty list = grounded)."""
    lang = sheet.language
    texts = [f.text for f in sheet.facts] + [sheet.question, *sheet.template]
    allowed = numbers_in(texts, lang)
    allowed += numbers_in(sheet.limitations, "en")
    text = " ".join(sentences)
    problems = unsupported_numbers(text, allowed, lang)
    problems = [p.replace("in the facts", "in the fact sheet") for p in problems]
    problems += unknown_partners(text, set(sheet.entities), sem, lang)
    if describes_future(text) and not any("projection" in f.text for f in sheet.facts):
        problems.append("observed data described as projected or expected")
    if not 2 <= len(sentences) <= 6:
        problems.append(f"expected 4–5 sentences, got {len(sentences)}")
    return problems
