"""Reduce one monthly bulk archive (``full_v2_YYYYMM.7z``) to two small Parquet extracts.

A monthly file holds ~5 M rows for all EU reporters (~400 MB unzipped). We keep:

- ``lu/lu_YYYYMM.parquet``: **every** Luxembourg row, all columns except ``VALUE_NAC`` (identical
  to EUR for LU, DATA_CARD §4b). Lossless for LU, so the archive itself can be deleted.
- ``eu_hs2/eu_hs2_YYYYMM.parquet``: value per reporter × trade type × flow × HS2 chapter for all
  EU reporters (the EU benchmark, DATA_CARD S03).

Codes stay text (leading zeros!); numbers become DOUBLE. No cleaning happens here: that is
``process/build.py``'s job. Outputs are written to a temporary name and renamed when complete.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb
import py7zr

from luxtrade.config import REPORTER

LU_SUBDIR = "lu"
EU_HS2_SUBDIR = "eu_hs2"

_LU_SQL = """
SELECT REPORTER AS reporter, PARTNER AS partner, TRADE_TYPE AS trade_type,
       PRODUCT_NC AS product_nc, PRODUCT_SITC AS product_sitc, PRODUCT_CPA21 AS product_cpa21,
       PRODUCT_CPA22 AS product_cpa22, PRODUCT_BEC AS product_bec, PRODUCT_BEC5 AS product_bec5,
       PRODUCT_SECTION AS product_section, FLOW AS flow, STAT_PROCEDURE AS stat_procedure,
       SUPPL_UNIT AS suppl_unit, PERIOD AS period,
       CAST(VALUE_EUR AS DOUBLE) AS value_eur, CAST(QUANTITY_KG AS DOUBLE) AS quantity_kg,
       CAST(QUANTITY_SUPPL_UNIT AS DOUBLE) AS quantity_suppl_unit
FROM src WHERE REPORTER = '{reporter}'
ORDER BY partner, trade_type, flow, product_nc, stat_procedure
"""

_EU_HS2_SQL = """
SELECT REPORTER AS reporter, TRADE_TYPE AS trade_type, FLOW AS flow,
       left(PRODUCT_NC, 2) AS hs2, PERIOD AS period, sum(CAST(VALUE_EUR AS DOUBLE)) AS value_eur
FROM src WHERE PRODUCT_NC <> 'TOTAL'
GROUP BY ALL ORDER BY ALL
"""


@dataclass(frozen=True)
class ReduceResult:
    """Row counts of one reduced archive."""

    period: str
    rows_total: int
    rows_lu: int
    rows_eu_hs2: int


def interim_paths(interim_dir: Path, period: str) -> tuple[Path, Path]:
    """Return the LU and EU-HS2 extract paths for a ``YYYYMM`` period."""
    return (
        interim_dir / LU_SUBDIR / f"lu_{period}.parquet",
        interim_dir / EU_HS2_SUBDIR / f"eu_hs2_{period}.parquet",
    )


def _extract_dat(archive: Path, work_dir: Path) -> Path:
    """Extract the single ``.dat`` file of a bulk archive into ``work_dir``."""
    with py7zr.SevenZipFile(archive, mode="r") as z:
        names = [n for n in z.getnames() if n.lower().endswith(".dat")]
        if len(names) != 1:
            raise ValueError(f"{archive.name}: expected one .dat file, found {names}")
        z.extract(path=work_dir, targets=names)
    return work_dir / names[0]


def reduce_archive(archive: Path, period: str, interim_dir: Path, work_dir: Path) -> ReduceResult:
    """Extract ``archive`` and write its LU and EU-HS2 extracts; return row counts.

    Args:
        archive: path to ``full_v2_YYYYMM.7z``.
        period: ``YYYYMM`` of the archive (checked against the file content).
        interim_dir: root of the interim extracts.
        work_dir: scratch folder for the ~400 MB ``.dat`` file (deleted afterwards).

    """
    lu_path, eu_path = interim_paths(interim_dir, period)
    lu_path.parent.mkdir(parents=True, exist_ok=True)
    eu_path.parent.mkdir(parents=True, exist_ok=True)
    work = work_dir / f"reduce_{period}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        dat = _extract_dat(archive, work)
        with duckdb.connect() as con:
            path = dat.as_posix().replace("'", "''")
            con.execute(
                f"CREATE VIEW src AS SELECT * FROM read_csv('{path}', header = true, "
                "all_varchar = true)"
            )
            periods = [r[0] for r in con.execute("SELECT DISTINCT PERIOD FROM src").fetchall()]
            if periods != [period]:
                raise ValueError(f"{archive.name}: PERIOD values {periods}, expected [{period}]")
            rows_total = con.execute("SELECT count(*) FROM src").fetchone()[0]
            for sql, path in (
                (_LU_SQL.format(reporter=REPORTER), lu_path),
                (_EU_HS2_SQL, eu_path),
            ):
                tmp = path.with_suffix(".parquet.tmp")
                con.execute(f"COPY ({sql}) TO '{tmp.as_posix()}' (FORMAT parquet)")
                tmp.replace(path)
            rows_lu = con.execute(f"SELECT count(*) FROM '{lu_path.as_posix()}'").fetchone()[0]
            rows_eu = con.execute(f"SELECT count(*) FROM '{eu_path.as_posix()}'").fetchone()[0]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if rows_lu == 0:
        raise ValueError(f"{archive.name}: no {REPORTER} rows")
    return ReduceResult(period, rows_total, rows_lu, rows_eu)
