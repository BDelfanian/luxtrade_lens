"""Spec → SQL compiler: one deterministic template per intent (SOLUTION_DESIGN §5.4).

Codes are validated before they are inlined, so the SQL shown to the user is readable and can
be copied and re-run as is. Every compiled query still passes ``sql_guard``.
"""

import re
from dataclasses import dataclass

from luxtrade.agents.defaults import period_bounds
from luxtrade.agents.spec import RANKED_INTENTS, QuerySpec
from luxtrade.config import REPORTER, SQL_ROW_LIMIT

_CODE_RE = re.compile(r"^[0-9A-Z]{2,8}$")
_LEVEL_COL = {
    "TOTAL": "'TOTAL'",
    "SECTION": "section",
    "HS2": "hs2",
    "HS4": "hs4",
    "HS6": "hs6",
    "CN8": "cn8",
}
_PRODUCT_COL = {2: "hs2", 4: "hs4", 6: "hs6", 8: "cn8"}
PARTNER_KEY = "CASE WHEN partner_is_special THEN 'UNDISCLOSED' ELSE partner END"
_EU = "(partner_is_eu27_2020 OR (partner_is_special AND trade_type = 'intra'))"
# keys without an "X": rankings.is_hidden_key treats X as a masked code
SPLIT_KEYS = {
    "partner_group": f"CASE WHEN {_EU} THEN 'EU27' ELSE 'NON_EU27' END",
    "confidentiality": "CASE WHEN is_confidential THEN 'CONFIDENTIAL' ELSE 'DISCLOSED' END",
}


class SpecError(ValueError):
    """Raised when a spec can't be compiled (e.g. an invalid code)."""


@dataclass(frozen=True)
class CompiledQuery:
    """SQL for the answer, for the scope statistics used by the guard and for share totals."""

    sql: str
    view: str
    stats_sql: str | None
    total_sql: str | None = None  # the whole a share is taken of (see ``share_base``)
    share_of: str = ""  # which filter that total leaves out: "partner" or "product"


def share_base(spec: QuerySpec) -> tuple[QuerySpec, str] | None:
    """The whole a share is taken of, when the spec filters the dimension being shared.

    "What share of imports came from Belgium, Germany and France?" ranks three partners, but
    their shares are of *all* imports, not of the three. So the total drops the filter on the
    shared dimension (partners for a partner breakdown, products for a product breakdown, and
    for one series the partner filter first, else the product filter) and keeps every other
    filter: shares of fuel imports by partner stay shares of fuel imports. ``None`` when no
    such filter is set (the result's own total is then the whole).
    """
    if spec.measure != "share" or spec.flow == "balance":
        return None
    if spec.intent not in RANKED_INTENTS | {"time_series", "pivot"}:
        return None
    partner_filter = bool(spec.partners) or spec.partner_group != "WORLD"
    if spec.breakdown == "partner" or (spec.breakdown == "none" and partner_filter):
        if not partner_filter:
            return None
        return spec.model_copy(update={"partners": [], "partner_group": "WORLD"}), "partner"
    if spec.breakdown in ("product", "none") and spec.products:
        return spec.model_copy(update={"products": []}), "product"
    return None


def _total_sql(spec: QuerySpec, base: QuerySpec, view: str) -> str:
    """Totals per flow (snapshots) or per period and flow (series) for ``share_base``."""
    where = _filters(base)
    measures = "sum(value_eur) AS value_eur"
    if spec.intent in RANKED_INTENTS:
        return _render(["flow", measures], view, where, ["flow"], "flow")
    bucket = "year" if spec.freq == "A" or spec.intent == "pivot" else "period"
    return _render(
        [f"{bucket} AS period", "flow", measures], view, where, [bucket, "flow"], "period, flow"
    )


def _quote(code: str) -> str:
    if not _CODE_RE.match(code):
        raise SpecError(f"invalid code {code!r}")
    return f"'{code}'"


def _in(column: str, codes: list[str]) -> str:
    return f"{column} IN ({', '.join(_quote(c) for c in codes)})"


def needs_detail(spec: QuerySpec) -> bool:
    """True if the query needs CN8 detail (finer than HS2, unit values, confidential split)."""
    return (
        spec.product_level in ("HS4", "HS6", "CN8")
        or any(len(p) > 2 for p in spec.products)
        or spec.measure == "unit_value"
        or spec.breakdown == "confidentiality"
    )


def _filters(spec: QuerySpec, shift_years: int = 0) -> list[str]:
    start, end = period_bounds(spec)
    start = start.replace(year=start.year - shift_years)
    where = [f"period >= DATE '{start}'", f"period < DATE '{end}'"]
    if spec.flow in ("import", "export"):
        where.append(f"flow = '{spec.flow}'")
    if spec.partners:
        where.append(_in("partner", spec.partners))
    if spec.partner_group == "EU27_2020":
        where.append(_EU)
    elif spec.partner_group == "EXTRA_EU27_2020":
        where.append(f"NOT {_EU}")
    if spec.products:
        by_len: dict[int, list[str]] = {}
        for code in spec.products:
            if len(code) not in _PRODUCT_COL:
                raise SpecError(f"invalid product code {code!r}")
            by_len.setdefault(len(code), []).append(code)
        parts = [_in(_PRODUCT_COL[n], codes) for n, codes in sorted(by_len.items())]
        where.append(parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")")
    return where


def _measures(detail: bool) -> str:
    cols = "sum(value_eur) AS value_eur, sum(qty_kg) AS qty_kg"
    if detail:
        cols += ", sum(value_eur) FILTER (WHERE qty_kg IS NOT NULL) AS value_eur_with_qty"
    return cols


def _key(spec: QuerySpec) -> str | None:
    if spec.breakdown == "partner":
        return PARTNER_KEY
    if spec.breakdown == "product":
        return _LEVEL_COL[spec.product_level or "HS2"]
    return SPLIT_KEYS.get(spec.breakdown)


def _render(select: list[str], view: str, where: list[str], group: list[str], order: str) -> str:
    sql = "SELECT " + ",\n       ".join(select) + f"\nFROM {view}\nWHERE " + "\n  AND ".join(where)
    if group:
        sql += "\nGROUP BY " + ", ".join(group)
    return sql + f"\nORDER BY {order}\nLIMIT {SQL_ROW_LIMIT}"


def compile_spec(spec: QuerySpec) -> CompiledQuery:
    """Compile a resolved spec into SQL over the semantic views."""
    if spec.intent == "benchmark":
        return CompiledQuery(sql=_benchmark(spec), view="v_eu_reporters_hs2", stats_sql=None)

    detail = needs_detail(spec)
    view = "v_lu_trade" if detail else "v_lu_trade_hs2"
    where = _filters(spec)
    key = _key(spec)
    bucket = "year" if spec.freq == "A" else "period"  # group by the column, alias it as period
    measures = _measures(detail)

    if spec.intent in RANKED_INTENTS and spec.measure == "change":
        # only the two years compared: the change is computed per key in the analysis step
        years = sorted({int(spec.period_start[:4]), int(spec.period_end[:4])})
        where.append(f"year IN ({', '.join(map(str, years))})")
        select = ["year", f"{key or chr(39) + 'TOTAL' + chr(39)} AS key", "flow", measures]
        sql = _render(select, view, where, ["year", "key", "flow"], "year, value_eur DESC")
    elif spec.intent in RANKED_INTENTS:
        select = [f"{key or chr(39) + 'TOTAL' + chr(39)} AS key", "flow", measures]
        sql = _render(select, view, where, ["key", "flow"], "value_eur DESC")
    elif spec.intent in ("time_series", "pivot"):
        if spec.intent == "pivot":
            bucket = "year"
        select = [f"{bucket} AS period"] + ([f"{key} AS key"] if key else []) + ["flow", measures]
        group = [bucket] + (["key"] if key else []) + ["flow"]
        sql = _render(select, view, where, group, "period" + (", value_eur DESC" if key else ""))
    elif spec.intent in ("seasonality", "forecast"):
        sql = _render(["period", "flow", measures], view, where, ["period", "flow"], "period")
    elif spec.intent == "single_value":
        where = _filters(spec, shift_years=1)
        sql = _render(["year", "flow", measures], view, where, ["year", "flow"], "year")
    else:
        raise SpecError(f"unsupported intent {spec.intent}")

    stats_sql = (
        "SELECT sum(value_eur) AS total,\n"
        "       sum(value_eur) FILTER (WHERE is_confidential) AS confidential,\n"
        "       sum(value_eur) FILTER (WHERE partner_is_special) AS special\n"
        "FROM v_lu_trade\nWHERE " + "\n  AND ".join(_filters(spec))
    )
    based = share_base(spec)
    if based is None:
        return CompiledQuery(sql=sql, view=view, stats_sql=stats_sql)
    base, share_of = based
    return CompiledQuery(
        sql=sql,
        view=view,
        stats_sql=stats_sql,
        total_sql=_total_sql(spec, base, view),
        share_of=share_of,
    )


def _benchmark(spec: QuerySpec) -> str:
    start, end = period_bounds(spec)
    reporters = [REPORTER] + [r for r in spec.compare_reporters if r != REPORTER]
    where = [_in("reporter", reporters), f"period >= DATE '{start}'", f"period < DATE '{end}'"]
    if spec.flow in ("import", "export"):
        where.append(f"flow = '{spec.flow}'")
    if spec.products:
        where.append(_in("hs2", [p[:2] for p in spec.products]))
    select = ["reporter", "year AS period", "trade_type", "flow", "sum(value_eur) AS value_eur"]
    return _render(
        select,
        "v_eu_reporters_hs2",
        where,
        ["reporter", "year", "trade_type", "flow"],
        "reporter, year",
    )
