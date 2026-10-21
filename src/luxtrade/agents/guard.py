"""Limitation guard: apply the limitations registry to specs and results (SOLUTION_DESIGN §5.3).

Blocks and warnings come from rules, never from the LLM. Runs before the query (on the spec and
the question text) and after it (on shares of confidential and undisclosed trade).
"""

from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import yaml

from luxtrade.agents.defaults import period_bounds
from luxtrade.agents.spec import Limitation, QuerySpec
from luxtrade.config import SERIES_FIRST_YEAR
from luxtrade.semantic.layer import Coverage
from luxtrade.semantic.lookup import normalise

REGISTRY_FILE = Path(__file__).resolve().parents[1] / "semantic" / "limitations.yaml"

# Deterministic topic checks (normalised, whole words); the interpreter's out_of_scope adds more
_TOPICS: dict[str, tuple[str, list[str]]] = {
    "S01": (
        "block",
        [
            "services",
            "service trade",
            "dienstleistungen",
            "prestations de services",
            "commerce de services",
            "dienstleistungshandel",
        ],
    ),
    "S02": (
        "block",
        [
            "gdp",
            "pib",
            "bip",
            "population",
            "bevolkerung",
            "per capita",
            "par habitant",
            "pro kopf",
            "inflation",
            "employment",
            "emploi",
            "beschaftigung",
            "unemployment",
            "chomage",
            "arbeitslosigkeit",
        ],
    ),
    "S04": (
        "warn",
        [
            "why",
            "pourquoi",
            "warum",
            "cause",
            "causes",
            "reason",
            "raison",
            "grund",
            "company",
            "companies",
            "firm",
            "firms",
            "entreprise",
            "entreprises",
            "unternehmen",
            "firma",
            "firmen",
        ],
    ),
    "L10": (
        "block",
        [
            "mirror",
            "miroir",
            "spiegel",
            "spiegelstatistik",
            "as reported by",
            "according to their statistics",
            "selon leurs statistiques",
        ],
    ),
}


@dataclass(frozen=True)
class ScopeStats:
    """Shares needed by the post-query rules."""

    total: float
    confidential: float
    special: float

    def pct(self, part: float) -> float:
        """Share of the total in percent (0 when the total is 0)."""
        return 100.0 * part / self.total if self.total else 0.0


@cache
def registry() -> dict[str, dict]:
    """Load the limitations registry, keyed by ID."""
    entries = yaml.safe_load(REGISTRY_FILE.read_text(encoding="utf-8"))
    return {e["id"]: e for e in entries}


def make(lim_id: str, severity: str, value: float | None = None, **fmt: object) -> Limitation:
    """Build a Limitation from the registry, formatting its message."""
    entry = registry()[lim_id]
    params = {k: v for k, v in entry.items() if k not in ("id", "key", "section", "message")}
    message = entry["message"].format(value=value or 0.0, **params, **fmt)
    return Limitation(id=lim_id, key=entry["key"], severity=severity, message=message, value=value)


def date_after(d: date) -> date:
    """First day of the month after ``d``."""
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _mentions(question: str, phrases: list[str]) -> bool:
    text = f" {normalise(question)} "
    return any(f" {normalise(p)} " in text for p in phrases)


def check_question(question: str, out_of_scope: list[str] = ()) -> list[Limitation]:
    """Topic checks on the raw question plus what the interpreter flagged."""
    found: list[Limitation] = []
    for lim_id, (severity, phrases) in _TOPICS.items():
        if lim_id in out_of_scope or (question and _mentions(question, phrases)):
            found.append(make(lim_id, severity))
    return found


def check_spec(spec: QuerySpec, cov: Coverage) -> list[Limitation]:
    """Pre-query rules on a resolved spec."""
    found: list[Limitation] = []
    start, end = period_bounds(spec)
    latest = cov.latest_complete_period
    if start.year < SERIES_FIRST_YEAR:
        found.append(make("L01", "block"))
    if end > date_after(latest):
        severity = "warn" if spec.partner_group == "EXTRA_EU27_2020" else "block"
        found.append(make("L04", severity, latest=f"{latest:%b %Y}"))
    fine = spec.product_level in ("HS6", "CN8") or any(len(p) >= 6 for p in spec.products)
    max_years = registry()["L05"]["max_years"]
    if fine and (end.year - start.year) > max_years and spec.intent != "benchmark":
        found.append(make("L05", "warn"))
    if spec.measure in ("value_eur", "share", "growth_yoy", "change", "hhi", "two_way"):
        found.append(make("L06", "warn"))
    if spec.measure in ("qty_kg", "unit_value"):
        found.append(make("L07", "warn"))
    if spec.partner_group != "WORLD" and start.year <= 2020 and end.year >= 2021:
        found.append(make("L08", "warn"))
    if spec.intent == "benchmark" and (spec.partners or any(len(p) > 2 for p in spec.products)):
        found.append(make("S03", "block"))
    if spec.intent == "forecast" or spec.forecast_horizon:
        found.append(make("S05", "warn"))
    return found


def check_result(spec: QuerySpec, stats: ScopeStats | None) -> list[Limitation]:
    """Post-query rules on the shares of confidential and undisclosed trade."""
    if stats is None or not stats.total:
        return []
    found: list[Limitation] = []
    conf_pct, special_pct = stats.pct(stats.confidential), stats.pct(stats.special)
    if spec.breakdown == "product" and conf_pct > registry()["L02"]["threshold_pct"]:
        found.append(make("L02", "warn", value=conf_pct))
    if spec.breakdown == "partner" and special_pct > registry()["L03"]["threshold_pct"]:
        found.append(make("L03", "warn", value=special_pct))
    return found


def is_blocked(limitations: list[Limitation]) -> bool:
    """True if any limitation blocks the answer."""
    return any(lim.severity == "block" for lim in limitations)


def merge(*groups: list[Limitation]) -> list[Limitation]:
    """Combine limitation lists, keeping the first occurrence of each ID."""
    seen: dict[str, Limitation] = {}
    for group in groups:
        for lim in group:
            seen.setdefault(lim.id, lim)
    return list(seen.values())
