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


def check(sentences: list[str], sheet: FactSheet, sem: SemanticLayer) -> list[str]:
    """Return the grounding problems found (empty list = grounded)."""
    lang = sheet.language
    allowed = [v for f in sheet.facts for v, _ in parse_numbers(f.text, lang)]
    allowed += [v for v, _ in parse_numbers(sheet.question, lang)]
    allowed += [v for msg in sheet.limitations for v, _ in parse_numbers(msg, "en")]
    allowed += [v for s in sheet.template for v, _ in parse_numbers(s, lang)]
    allowed += [float(n) for n in range(0, 13)] + [100.0, 80.0, 95.0]
    problems = []
    text = " ".join(sentences)
    for value, decimals in parse_numbers(text, lang):
        if not _matches(value, decimals, allowed):
            problems.append(f"number {value:g} is not in the fact sheet")
    norm = f" {normalise(text)} "
    col = {"en": "label_en", "fr": "label_fr", "de": "label_de"}.get(lang, "label_en")
    for code, row in sem.partners.iterrows():
        if row["is_special"] or code in sheet.entities:
            continue
        label = normalise(str(row[col]))
        if f" {label} " in norm:
            problems.append(f"partner {row[col]} is not in the result")
    if _FUTURE.search(text) and not any("projection" in f.text for f in sheet.facts):
        problems.append("observed data described as projected or expected")
    if not 2 <= len(sentences) <= 6:
        problems.append(f"expected 4–5 sentences, got {len(sentences)}")
    return problems
