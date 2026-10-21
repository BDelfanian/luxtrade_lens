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
    if spec.year_step and (spec.freq == "A" or spec.intent == "pivot"):
        # "every five years from 2005": 2005, 2010, …, counted from the first year
        where.append(f"(year - {start.year}) % {int(spec.year_step)} = 0")
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


def _hhi(spec: QuerySpec, view: str, where: list[str]) -> str:
    """Concentration per year and flow: the sum of squared shares × 10,000 (Herfindahl-Hirschman).

    Shares are of each year's flow across every item of the breakdown, not only the top ones:
    product chapters (or the level asked for), or partners without the undisclosed ones (as in
    the Overview's diversification card). Also returns how many items trade, the largest one
    and its share, so the answer can say what drives the index.
    """
    if spec.breakdown == "partner":
        key, where = "partner", [*where, "NOT partner_is_special"]
    else:
        key = _LEVEL_COL[spec.product_level or "HS2"]
    filters = "\n    AND ".join(where)
    return f"""WITH by_key AS (
  SELECT year AS period, flow, {key} AS key, sum(value_eur) AS value_eur
  FROM {view}
  WHERE {filters}
  GROUP BY year, flow, key
), shares AS (
  SELECT period, flow, key,
         value_eur / sum(value_eur) OVER (PARTITION BY period, flow) AS s
  FROM by_key
  WHERE value_eur > 0
)
SELECT period, flow, 10000 * sum(s * s) AS hhi, count(*) AS n,
       arg_max(key, s) AS top_key, 100 * max(s) AS top_share
FROM shares
GROUP BY period, flow
ORDER BY period, flow
LIMIT {SQL_ROW_LIMIT}"""


def _two_way(spec: QuerySpec, where: list[str]) -> str:
    """Exports and imports of the same product code, and how much of it goes both ways.

    Grubel-Lloyd per code: 100 × (1 − |X − M| / (X + M)); for all trade, the matched part
    100 × Σ(X + M − |X − M|) / Σ(X + M), over every code of the level asked for. A code masked
    at that level ("87XX" for headings) mixes products and is left out of the index; at a
    coarser level its chapter is known and it counts. The totals keep everything, so shares are
    of all exports and imports. A ranking returns every code (the largest first); a series one
    row per year with its largest two-way product.
    """
    key = _LEVEL_COL[spec.product_level or "HS2"]
    filters = "\n    AND ".join(where)
    head = f"""WITH rows AS (
  SELECT year AS period, {key} AS key, flow, {key} LIKE '%X%' AS masked, value_eur
  FROM v_lu_trade
  WHERE {filters}
), totals AS (
  SELECT period,
         sum(value_eur) FILTER (WHERE flow = 'export') AS x_total,
         sum(value_eur) FILTER (WHERE flow = 'import') AS m_total,
         coalesce(sum(value_eur) FILTER (WHERE masked), 0) AS confidential
  FROM rows
  GROUP BY period
), by_key AS (
  SELECT period, key,
         coalesce(sum(value_eur) FILTER (WHERE flow = 'export'), 0) AS x,
         coalesce(sum(value_eur) FILTER (WHERE flow = 'import'), 0) AS m
  FROM rows
  WHERE NOT masked
  GROUP BY period, key
)"""
    if spec.intent == "time_series":
        return f"""{head}
SELECT b.period, 100 * sum(b.x + b.m - abs(b.x - b.m)) / sum(b.x + b.m) AS value,
       count(*) AS n, arg_max(b.key, least(b.x, b.m)) AS top_key,
       arg_max(b.x, least(b.x, b.m)) AS top_export, arg_max(b.m, least(b.x, b.m)) AS top_import,
       any_value(t.x_total) AS x_total, any_value(t.m_total) AS m_total,
       any_value(t.confidential) AS confidential
FROM by_key AS b JOIN totals AS t USING (period)
GROUP BY b.period
ORDER BY b.period
LIMIT {SQL_ROW_LIMIT}"""
    return f"""{head}
SELECT b.period, b.key, b.x AS export, b.m AS import,
       100 * (1 - abs(b.x - b.m) / nullif(b.x + b.m, 0)) AS gl,
       100 * sum(b.x + b.m - abs(b.x - b.m)) OVER w / sum(b.x + b.m) OVER w AS gl_all,
       count(*) OVER w AS n, t.x_total, t.m_total, t.confidential
FROM by_key AS b JOIN totals AS t USING (period)
WINDOW w AS (PARTITION BY b.period)
ORDER BY b.period, b.x + b.m DESC
LIMIT {SQL_ROW_LIMIT}"""


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

    if spec.measure == "hhi":
        sql = _hhi(spec, view, where)
    elif spec.measure == "two_way":
        view = "v_lu_trade"  # the confidential flag is on the detail rows
        sql = _two_way(spec, where)
    elif spec.intent in RANKED_INTENTS and spec.measure == "change":
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
