"""Build the processed-data contract (GUIDELINES §1.3) from the interim LU extracts.

Input: ``data/interim/`` (written by ``python -m luxtrade.ingest.download``) and the EN/FR/DE
code lists in ``data/raw/codelists/``. Output, in ``data/processed/``:

- ``trade.parquet``: LU, monthly, one row per period × partner × flow × trade type × product.
  CN8 detail (level 8, masked codes flagged ``is_confidential``) plus the bulk ``TOTAL`` rows
  (level 0, for reconciliation only). Summed over ``STAT_PROCEDURE`` and the classification
  columns (DATA_CARD §4b); ``qty_kg`` is null when any part is reported as 0 (unknown).
- ``products.parquet`` / ``partners.parquet``: dimensions with official EN/FR/DE labels.
- ``benchmark.parquet``: BE, NL, DE, FR, AT and LU totals by HS2 chapter.
- ``meta.json``, ``lineage.json``, ``quality_report.json``.

Then rebuilds the DuckDB semantic layer. Usage: ``python -m luxtrade.process.build``
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pycountry

from luxtrade.config import (
    BENCHMARK_FILE,
    BENCHMARK_REPORTERS,
    DATASET_ID,
    INTERIM_DIR,
    LINEAGE_FILE,
    MANIFEST_FILE,
    META_FILE,
    PARTNERS_FILE,
    PROCESSED_DIR,
    PRODUCTS_FILE,
    QUALITY_REPORT_FILE,
    RAW_DIR,
    TRADE_FILE,
)
from luxtrade.ingest.manifest import git_commit
from luxtrade.ingest.reduce import EU_HS2_SUBDIR, LU_SUBDIR
from luxtrade.logging_setup import setup_logging, timed
from luxtrade.process.codelists import load_codelist
from luxtrade.process.nomenclature import (
    CHAPTERS,
    HEADINGS,
    PARTNERS,
    is_eu27_2020,
    is_special,
    section_of,
)
from luxtrade.process.validate import validate

logger = logging.getLogger(__name__)

SOURCE = f"Eurostat Comext {DATASET_ID}, bulk monthly files full_v2_YYYYMM.7z"
_CONFIDENTIAL = ("Confidential", "Confidentiel", "Vertraulich")
# Eurostat partner codes that are not ISO 3166 alpha-2 (pycountry handles the rest)
_ISO3_OVERRIDES = {"XS": "SRB", "XK": "XKX"}

_TRADE_SQL = """
SELECT 'M' AS freq,
       CAST(strptime(period, '%Y%m') AS DATE) AS period,
       reporter, partner,
       CASE flow WHEN '1' THEN 'import' WHEN '2' THEN 'export' END AS flow,
       product_nc AS product,
       CAST(CASE WHEN product_nc = 'TOTAL' THEN 0 ELSE length(product_nc) END AS TINYINT) AS level,
       CASE trade_type WHEN 'I' THEN 'intra' WHEN 'E' THEN 'extra' END AS trade_type,
       product_nc LIKE '%X%' AS is_confidential,
       sum(value_eur) AS value_eur,
       CASE WHEN bool_or(coalesce(quantity_kg, 0) = 0) THEN NULL
            ELSE sum(quantity_kg) END AS qty_kg
FROM read_parquet('{src}')
GROUP BY ALL
ORDER BY period, partner, flow, level, product, trade_type
"""

# Other classifications of each CN8 code, from the most recent month it was traded
_ATTR_SQL = """
SELECT product_nc AS product,
       arg_max(nullif(regexp_replace(product_sitc, '^\\.+$', ''), ''), period) AS sitc,
       arg_max(nullif(regexp_replace(coalesce(nullif(product_cpa22, ''), product_cpa21),
                                     '^\\.+$', ''), ''), period) AS cpa,
       arg_max(nullif(regexp_replace(product_bec, '^\\.+$', ''), ''), period) AS bec,
       arg_max(nullif(regexp_replace(product_bec5, '^\\.+$', ''), ''), period) AS bec5
FROM read_parquet('{src}') WHERE product_nc <> 'TOTAL'
GROUP BY 1
"""

_BENCHMARK_SQL = """
SELECT reporter,
       CASE trade_type WHEN 'I' THEN 'intra' WHEN 'E' THEN 'extra' END AS trade_type,
       CASE flow WHEN '1' THEN 'import' WHEN '2' THEN 'export' END AS flow,
       hs2, CAST(strptime(period, '%Y%m') AS DATE) AS period, sum(value_eur) AS value_eur
FROM read_parquet('{src}')
WHERE reporter IN ({reporters})
GROUP BY ALL
ORDER BY reporter, trade_type, flow, hs2, period
"""


def _glob(interim_dir: Path, subdir: str, prefix: str) -> str:
    files = sorted((interim_dir / subdir).glob(f"{prefix}_*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"no {prefix}_*.parquet in {interim_dir / subdir}: "
            "run python -m luxtrade.ingest.download first"
        )
    return (interim_dir / subdir / f"{prefix}_*.parquet").as_posix()


def _sentence_case(label: str) -> str:
    """'LIVE ANIMALS' → 'Live animals' (HS chapter labels are all caps in the code lists)."""
    return label[:1] + label[1:].lower() if label.isupper() else label


def product_labels(code: str, level: int, cn: pd.DataFrame) -> tuple[str, str, str]:
    """EN/FR/DE label of a product code at a given level (2, 4, 6, 8; masked codes too)."""
    if "X" in code:
        if code.startswith("99"):
            return CHAPTERS["99"]
        base = code.rstrip("X")
        parent = product_labels(base, len(base), cn)
        return tuple(f"{c} — {lab}" for c, lab in zip(_CONFIDENTIAL, parent, strict=True))
    curated = CHAPTERS if level == 2 else HEADINGS if level == 4 else {}
    if code in curated:
        return curated[code]
    if code in cn.index:
        row = cn.loc[code]
        return tuple(_sentence_case(row[c]) for c in ("label_en", "label_fr", "label_de"))
    if level == 2:
        return (f"Chapter {code}", f"Chapitre {code}", f"Kapitel {code}")
    parent = product_labels(code[: level - 2], level - 2, cn)
    return tuple(f"{lab} ({code})" for lab in parent)


@timed
def build_products(con: duckdb.DuckDBPyConnection, lu_src: str, cn: pd.DataFrame) -> pd.DataFrame:
    """Product dimension: every CN8/masked code traded by LU plus its HS6, HS4, HS2 parents."""
    attrs = con.execute(_ATTR_SQL.format(src=lu_src)).df()
    rows = []
    for code in sorted(attrs["product"]):
        for level in (2, 4, 6, 8):
            rows.append((code[:level], level, code[: level - 2] if level > 2 else "TOTAL"))
    df = pd.DataFrame(rows, columns=["product", "level", "parent"]).drop_duplicates("product")
    labels = [product_labels(c, lv, cn) for c, lv in zip(df["product"], df["level"], strict=True)]
    df["label_en"], df["label_fr"], df["label_de"] = zip(*labels, strict=True)
    df["label"] = df["label_en"]
    df["section"] = df["product"].str[:2].map(section_of)
    df["is_confidential"] = df["product"].str.contains("X", regex=False)
    df = df.merge(attrs, on="product", how="left")
    cols = ["product", "level", "parent", "label", "label_en", "label_fr", "label_de"]
    cols += ["section", "is_confidential", "sitc", "cpa", "bec", "bec5"]
    return df[cols].sort_values(["level", "product"]).reset_index(drop=True)


def iso3_of(partner: str) -> str | None:
    """ISO-3 code for maps; None for special and non-country codes."""
    if is_special(partner):
        return None
    if partner in _ISO3_OVERRIDES:
        return _ISO3_OVERRIDES[partner]
    country = pycountry.countries.get(alpha_2=partner)
    if country is None:
        country = pycountry.historic_countries.get(alpha_2=partner)
    return getattr(country, "alpha_3", None)


@timed
def build_partners(codes: list[str], labels: pd.DataFrame) -> pd.DataFrame:
    """Partner dimension: curated labels where defined, else the official code list."""
    rows = []
    for code in sorted(codes):
        if code in PARTNERS:
            iso3, *labs = PARTNERS[code]
        else:
            iso3 = iso3_of(code)
            labs = list(labels.loc[code]) if code in labels.index else [code, code, code]
        rows.append((code, iso3, *labs))
    df = pd.DataFrame(rows, columns=["partner", "iso3", "label_en", "label_fr", "label_de"])
    df["label"] = df["label_en"]
    df["is_aggregate"] = False
    df["is_eu27_2020"] = df["partner"].map(is_eu27_2020)
    df["is_special"] = df["partner"].map(is_special)
    return df


def _copy(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> None:
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({sql}) TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    tmp.replace(path)


def _write_df(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, path: Path) -> None:
    con.register("_df", df)
    _copy(con, "SELECT * FROM _df", path)
    con.unregister("_df")


def _lineage(raw_dir: Path, interim_dir: Path) -> dict:
    manifest_path = raw_dir / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    files = manifest.get("files", {})
    periods = sorted(p.stem.split("_")[-1] for p in (interim_dir / LU_SUBDIR).glob("lu_*.parquet"))
    by_period = {e.get("period"): {"file": name, **e} for name, e in files.items()}
    inputs = [by_period.get(p, {"period": p, "file": None}) for p in periods]
    return {"inputs": inputs, "codelists": manifest.get("codelists", {})}


@timed
def build(
    interim_dir: Path = INTERIM_DIR, raw_dir: Path = RAW_DIR, out_dir: Path = PROCESSED_DIR
) -> dict:
    """Write the five contract files plus lineage and quality report; return the report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lu_src = _glob(interim_dir, LU_SUBDIR, "lu")
    eu_src = _glob(interim_dir, EU_HS2_SUBDIR, "eu_hs2")
    cn = load_codelist(raw_dir, "CN.txt")
    partner_labels = load_codelist(raw_dir, "PARTNERS_ISO.txt")
    with duckdb.connect() as con:
        _copy(con, _TRADE_SQL.format(src=lu_src), out_dir / TRADE_FILE)
        logger.info("trade.parquet written")
        _write_df(con, build_products(con, lu_src, cn), out_dir / PRODUCTS_FILE)
        codes = [r[0] for r in con.execute(f"SELECT DISTINCT partner FROM '{lu_src}'").fetchall()]
        _write_df(con, build_partners(codes, partner_labels), out_dir / PARTNERS_FILE)
        reporters = ", ".join(f"'{r}'" for r in BENCHMARK_REPORTERS)
        _copy(con, _BENCHMARK_SQL.format(src=eu_src, reporters=reporters), out_dir / BENCHMARK_FILE)
    report = validate(out_dir)
    (out_dir / QUALITY_REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")
    lineage = _lineage(raw_dir, interim_dir)
    (out_dir / LINEAGE_FILE).write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    dates = [i.get("downloaded_at") for i in lineage["inputs"] if i.get("downloaded_at")]
    now = datetime.now(UTC)
    meta = {
        "is_placeholder": False,
        "source": SOURCE,
        "extraction_date": max(dates)[:10] if dates else now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "first_month": report["first_month"],
        "last_complete_month": report["latest_complete_month"],
        "latest_month": report["last_month"],
        "git_commit": git_commit(),
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info(
        "processed data written to %s (%s to %s, complete until %s)",
        out_dir,
        meta["first_month"],
        meta["latest_month"],
        meta["last_complete_month"],
    )
    return report


def main() -> None:
    """CLI entry point: build the contract files, then the semantic layer."""
    from luxtrade.semantic.build import build_database

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interim", type=Path, default=INTERIM_DIR)
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--out", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--skip-semantic", action="store_true", help="don't rebuild DuckDB")
    args = parser.parse_args()
    setup_logging()
    build(args.interim, args.raw, args.out)
    if not args.skip_semantic:
        build_database(args.out)


if __name__ == "__main__":
    main()
