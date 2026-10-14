"""Build the semantic-layer database (DuckDB views over the processed Parquet contract).

The app later opens this file read-only with external access disabled, so no query can read
or write files (SOLUTION_DESIGN §5.4). Usage: ``python -m luxtrade.semantic.build``
"""

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

from luxtrade.config import (
    BENCHMARK_FILE,
    DUCKDB_FILE,
    META_FILE,
    PARTNERS_FILE,
    PROCESSED_DIR,
    PRODUCTS_FILE,
    REPORTER,
    TRADE_FILE,
)
from luxtrade.logging_setup import setup_logging, timed
from luxtrade.process.nomenclature import SECTIONS

logger = logging.getLogger(__name__)

_VIEWS = f"""
CREATE OR REPLACE TABLE lu_detail AS
SELECT CAST(t.period AS DATE) AS period, year(t.period) AS year, month(t.period) AS month,
       t.partner, t.trade_type, t.flow,
       t.product AS cn8, left(t.product, 2) AS hs2, left(t.product, 4) AS hs4,
       left(t.product, 6) AS hs6, coalesce(p.section, 'XX') AS section,
       t.is_confidential,
       coalesce(pt.is_special, false) AS partner_is_special,
       coalesce(pt.is_eu27_2020, false) AS partner_is_eu27_2020,
       t.value_eur, t.qty_kg
FROM trade t
LEFT JOIN products p ON p.product = t.product
LEFT JOIN partners pt ON pt.partner = t.partner
WHERE t.reporter = '{REPORTER}' AND t.level = 8 AND t.freq = 'M';

CREATE OR REPLACE VIEW v_lu_trade AS SELECT * FROM lu_detail;

CREATE OR REPLACE VIEW v_lu_trade_hs2 AS
SELECT period, year, month, partner, trade_type, flow, hs2, section,
       partner_is_special, partner_is_eu27_2020,
       sum(value_eur) AS value_eur, sum(qty_kg) AS qty_kg,
       sum(CASE WHEN is_confidential THEN value_eur ELSE 0 END) AS confidential_value_eur
FROM lu_detail GROUP BY ALL;

CREATE OR REPLACE VIEW v_eu_reporters_hs2 AS
SELECT reporter, CAST(period AS DATE) AS period, year(period) AS year, month(period) AS month,
       trade_type, flow, hs2, value_eur
FROM benchmark;

CREATE OR REPLACE VIEW dim_product AS
SELECT product, level, parent, label_en, label_fr, label_de, section, is_confidential
FROM products;

CREATE OR REPLACE VIEW dim_partner AS
SELECT partner, iso3, label_en, label_fr, label_de, is_eu27_2020, is_special FROM partners;

CREATE OR REPLACE VIEW dim_section AS SELECT * FROM sections;

CREATE OR REPLACE TABLE coverage AS
WITH m AS (SELECT period, count(DISTINCT trade_type) AS n FROM lu_detail GROUP BY period)
SELECT (SELECT min(period) FROM m) AS first_period,
       (SELECT max(period) FROM m WHERE n = 2) AS latest_complete_period,
       (SELECT max(period) FROM m) AS latest_period,
       meta.extraction_date, meta.is_placeholder, meta.source
FROM meta;

CREATE OR REPLACE VIEW meta_coverage AS SELECT * FROM coverage;
"""


@timed
def build_database(processed_dir: Path = PROCESSED_DIR) -> Path:
    """Create ``luxtrade.duckdb`` in ``processed_dir`` from the contract files; return its path."""
    db_path = processed_dir / DUCKDB_FILE
    meta = json.loads((processed_dir / META_FILE).read_text(encoding="utf-8"))
    sections = pd.DataFrame(
        [(code, *vals) for code, vals in SECTIONS.items()],
        columns=["section", "roman", "label_en", "label_fr", "label_de"],
    )
    meta_df = pd.DataFrame(
        [
            {
                "extraction_date": meta.get("extraction_date"),
                "is_placeholder": bool(meta.get("is_placeholder", False)),
                "source": meta.get("source", "Eurostat Comext DS-045409"),
            }
        ]
    )
    with duckdb.connect(str(db_path)) as con:
        for table, file in (
            ("trade", TRADE_FILE),
            ("products", PRODUCTS_FILE),
            ("partners", PARTNERS_FILE),
            ("benchmark", BENCHMARK_FILE),
        ):
            path = (processed_dir / file).as_posix()
            con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path}')")
        con.register("sections_df", sections)
        con.register("meta_df", meta_df)
        con.execute("CREATE OR REPLACE TABLE sections AS SELECT * FROM sections_df")
        con.execute("CREATE OR REPLACE TABLE meta AS SELECT * FROM meta_df")
        con.execute(_VIEWS)
        rows = con.execute("SELECT count(*) FROM lu_detail").fetchone()[0]
    logger.info("semantic layer built: %s (%d LU detail rows)", db_path, rows)
    return db_path


if __name__ == "__main__":
    setup_logging()
    build_database()
