"""Data-quality checks on the processed contract files (GUIDELINES §3).

Structural problems (bad codes, duplicate keys, wrong schema) stop the pipeline. Data facts
(confidential share, reconciliation gaps, missing months, negative values) go into
``quality_report.json`` and are logged as warnings when unexpected.
"""

import logging
from pathlib import Path

import duckdb

from luxtrade.config import BENCHMARK_FILE, TRADE_FILE

logger = logging.getLogger(__name__)

TRADE_COLUMNS = [
    "freq",
    "period",
    "reporter",
    "partner",
    "flow",
    "product",
    "level",
    "trade_type",
    "is_confidential",
    "value_eur",
    "qty_kg",
]
RECONCILE_TOLERANCE_EUR = 1.0
RECONCILE_TOLERANCE_REL = 1e-6  # TOTAL rows are rounded separately (gaps of a few hundred EUR)


class DataValidationError(ValueError):
    """Raised when the processed data breaks the contract."""


def _one(con: duckdb.DuckDBPyConnection, sql: str):
    return con.execute(sql).fetchone()[0]


def _reconcile(con: duckdb.DuckDBPyConnection, keys: str) -> dict:
    """Compare CN8 detail (incl. masked codes) with the bulk TOTAL rows, grouped by ``keys``."""
    row = con.execute(
        f"""
        WITH det AS (SELECT {keys}, sum(value_eur) AS v FROM d GROUP BY ALL),
             tot AS (SELECT {keys}, sum(value_eur) AS v FROM t WHERE level = 0 GROUP BY ALL),
             j AS (SELECT abs(coalesce(det.v, 0) - coalesce(tot.v, 0)) AS gap,
                          greatest({RECONCILE_TOLERANCE_EUR},
                                   {RECONCILE_TOLERANCE_REL} * abs(coalesce(tot.v, 0))) AS tol,
                          tot.v IS NULL AS no_total
                   FROM det FULL JOIN tot USING ({keys}))
        SELECT count(*), count(*) FILTER (WHERE gap > tol),
               coalesce(max(gap), 0), count(*) FILTER (WHERE no_total)
        FROM j
        """
    ).fetchone()
    return {
        "keys": keys,
        "groups": row[0],
        "groups_off_tolerance": row[1],
        "max_abs_gap_eur": row[2],
        "groups_without_total_row": row[3],
        "tolerance": f"max({RECONCILE_TOLERANCE_EUR} EUR, {RECONCILE_TOLERANCE_REL:.0e} x TOTAL)",
    }


def _ym(value) -> str | None:
    return value.strftime("%Y-%m") if value is not None else None


def validate(processed_dir: Path) -> dict:
    """Check ``trade.parquet`` and ``benchmark.parquet``; return the quality report."""
    trade = (processed_dir / TRADE_FILE).as_posix()
    bench = (processed_dir / BENCHMARK_FILE).as_posix()
    with duckdb.connect() as con:
        con.execute(f"CREATE VIEW t AS SELECT * FROM '{trade}'")
        con.execute("CREATE VIEW d AS SELECT * FROM t WHERE level = 8")
        columns = [r[0] for r in con.execute("DESCRIBE t").fetchall()]
        errors = []
        if columns != TRADE_COLUMNS:
            errors.append(f"trade columns {columns} != contract {TRADE_COLUMNS}")
        checks = {
            "unknown flow or trade type": "flow IS NULL OR trade_type IS NULL",
            "level not 0 or 8": "level NOT IN (0, 8)",
            "level 8 code not 8 characters": "level = 8 AND length(product) <> 8",
            "level 0 code not TOTAL": "level = 0 AND product <> 'TOTAL'",
            "null value": "value_eur IS NULL",
            "zero quantity (should be null)": "qty_kg = 0",
        }
        for name, cond in checks.items():
            if n := _one(con, f"SELECT count(*) FROM t WHERE {cond}"):
                errors.append(f"{name}: {n} rows")
        dupes = _one(
            con,
            "SELECT count(*) FROM (SELECT 1 FROM t GROUP BY period, partner, flow, trade_type, "
            "product HAVING count(*) > 1)",
        )
        if dupes:
            errors.append(f"duplicate keys: {dupes}")
        if errors:
            raise DataValidationError("; ".join(errors))

        months = con.execute(
            "SELECT period, count(DISTINCT trade_type) AS n FROM d GROUP BY 1 ORDER BY 1"
        ).fetchall()
        all_months = con.execute(
            "SELECT range::DATE FROM range((SELECT min(period) FROM d), "
            "(SELECT max(period) FROM d) + INTERVAL 1 MONTH, INTERVAL 1 MONTH)"
        ).fetchall()
        present = {m[0] for m in months}
        missing = [_ym(m[0]) for m in all_months if m[0] not in present]
        complete = [m[0] for m in months if m[1] == 2]
        recon = _reconcile(con, "period, flow, trade_type")
        # Per partner, TOTAL rows put trade hidden as QY/QZ in the detail back under the real
        # country (e.g. DE import TOTAL > DE detail), so gaps here are expected: info only.
        recon_partner = _reconcile(con, "period, partner, flow, trade_type")
        rows = con.execute(
            "SELECT freq, level, count(*) FROM t GROUP BY ALL ORDER BY ALL"
        ).fetchall()
        confidential = con.execute(
            """
            SELECT year(period) AS year, flow,
                   round(100 * sum(value_eur) FILTER (WHERE is_confidential) / sum(value_eur), 2)
            FROM d GROUP BY ALL ORDER BY ALL
            """
        ).fetchall()
        report = {
            "rows": {f"{f}/level_{lv}": n for f, lv, n in rows},
            "first_month": _ym(months[0][0]) if months else None,
            "last_month": _ym(months[-1][0]) if months else None,
            "latest_complete_month": _ym(max(complete)) if complete else None,
            "months_extra_eu_only": [_ym(m[0]) for m in months if m[1] == 1],
            "missing_months": missing,
            "partners": _one(con, "SELECT count(DISTINCT partner) FROM d"),
            "products_cn8": _one(con, "SELECT count(DISTINCT product) FROM d"),
            "negative_values": _one(con, "SELECT count(*) FROM t WHERE value_eur < 0"),
            "unknown_quantity_share_pct": round(
                100 * _one(con, "SELECT avg(CASE WHEN qty_kg IS NULL THEN 1 ELSE 0 END) FROM d"),
                2,
            ),
            "reconciliation": recon,
            "reconciliation_by_partner_info": recon_partner,
            "confidential_share_pct": [
                {"year": y, "flow": f, "pct": p} for y, f, p in confidential
            ],
            "benchmark_rows_by_reporter": dict(
                con.execute(
                    f"SELECT reporter, count(*) FROM '{bench}' GROUP BY 1 ORDER BY 1"
                ).fetchall()
            ),
        }
    if missing:
        logger.warning("%d missing months, first: %s", len(missing), missing[:6])
    if report["reconciliation"]["groups_off_tolerance"]:
        logger.warning("detail != TOTAL beyond tolerance: %s", report["reconciliation"])
    if report["negative_values"]:
        logger.warning("%d negative values", report["negative_values"])
    logger.info(
        "validation ok: %s to %s, complete until %s",
        report["first_month"],
        report["last_month"],
        report["latest_complete_month"],
    )
    return report
