"""Defaults table: fill what the user didn't say and state every assumption (SOLUTION_DESIGN §4)."""

from datetime import date

from luxtrade.agents.spec import LEVEL_DIGITS, SERIES_INTENTS, SNAPSHOT_INTENTS, QuerySpec
from luxtrade.config import (
    BENCHMARK_REPORTERS,
    DEFAULT_TOP_N,
    FORECAST_DEFAULT_HORIZON,
    FORECAST_MAX_HORIZON,
    REPORTER,
    SERIES_FIRST_YEAR,
)
from luxtrade.semantic.layer import Coverage

_FINER = {0: "HS2", 2: "HS4", 4: "HS6", 6: "CN8", 8: "CN8"}


def _month(text: str, end: bool) -> date:
    """Parse 'YYYY' or 'YYYY-MM' into the first day of its first (or last) month."""
    parts = text.strip().split("-")
    year = int(parts[0])
    if len(parts) > 1:
        return date(year, int(parts[1]), 1)
    return date(year, 12 if end else 1, 1)


def period_bounds(spec: QuerySpec) -> tuple[date, date]:
    """Resolved spec → [start, end) dates for SQL."""
    start = _month(spec.period_start or str(SERIES_FIRST_YEAR), end=False)
    last = _month(spec.period_end or spec.period_start or str(SERIES_FIRST_YEAR), end=True)
    end = date(last.year + (last.month == 12), last.month % 12 + 1, 1)
    return start, end


def _fmt(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def apply_defaults(spec: QuerySpec, cov: Coverage) -> QuerySpec:
    """Return a fully specified copy of ``spec``, with the defaults listed in assumptions."""
    s = spec.model_copy(deep=True)
    notes = list(s.assumptions)

    if s.intent in ("ranking", "composition", "pivot") and s.breakdown == "none":
        s.breakdown = "partner" if (s.products or not s.partners) else "product"
        notes.append(f"broken down by {s.breakdown} (not stated)")
    if s.intent == "drilldown":
        s.breakdown = "product"

    if s.product_level is None:
        if s.breakdown == "product":
            finest = max((len(p) for p in s.products if p.isdigit()), default=0)
            s.product_level = _FINER[finest] if s.intent == "drilldown" or finest else "HS2"
            if finest == 0:
                notes.append(f"{s.product_level} chapters (no level given)")
        else:
            s.product_level = "TOTAL"

    if s.flow is None:
        s.flow = "both"
        notes.append("exports and imports (no flow given)")

    latest_year = cov.latest_complete_year
    complete = _fmt(cov.latest_complete_period)
    if s.period_start is None and s.period_end is None:
        if s.intent in SNAPSHOT_INTENTS:
            s.period_start = s.period_end = str(latest_year)
            notes.append(f"latest complete year {latest_year} (no period given)")
        elif s.intent == "pivot":
            s.period_start, s.period_end = str(latest_year - 4), str(latest_year)
            notes.append(f"last five complete years {latest_year - 4}–{latest_year}")
        elif s.intent == "benchmark":
            s.period_start, s.period_end = "2015", str(latest_year)
            notes.append(f"2015–{latest_year}, indexed to 2015")
        else:
            s.period_start, s.period_end = f"{SERIES_FIRST_YEAR}-01", complete
            notes.append(f"full series {SERIES_FIRST_YEAR}–{complete} (no period given)")
    elif s.period_end is None:
        s.period_end = s.period_start if s.intent in SNAPSHOT_INTENTS else complete
    elif s.period_start is None:
        s.period_start = s.period_end if s.intent in SNAPSHOT_INTENTS else f"{SERIES_FIRST_YEAR}-01"

    if s.freq is None:
        if s.intent in ("seasonality", "forecast"):
            s.freq = "M"
        elif s.intent == "time_series":
            start, end = period_bounds(s)
            s.freq = "A" if (end.year - start.year) > 3 else "M"
        else:
            s.freq = "A"

    if s.top_n is None and s.breakdown != "none":
        s.top_n = DEFAULT_TOP_N
    if s.intent == "forecast":
        s.forecast_horizon = min(
            s.forecast_horizon or FORECAST_DEFAULT_HORIZON, FORECAST_MAX_HORIZON
        )
    if s.intent == "benchmark" and not s.compare_reporters:
        s.compare_reporters = [r for r in BENCHMARK_REPORTERS if r != REPORTER]
        notes.append("compared with " + ", ".join(s.compare_reporters))

    s.partners = [p.upper() for p in s.partners]
    s.assumptions = list(dict.fromkeys(notes))
    return s


def product_digits(level: str | None) -> int:
    """Number of code digits for a product level (TOTAL = 0)."""
    return LEVEL_DIGITS.get(level or "TOTAL", 0)


def is_series(spec: QuerySpec) -> bool:
    """True for intents whose answer is a time series."""
    return spec.intent in SERIES_INTENTS
