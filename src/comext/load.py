"""Sequential, bounded-memory imports with one transaction per source file."""

import csv
import re
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import py7zr
from sqlalchemy import URL, create_engine, insert, select

from .download import read_receipt, sha256
from .models import Base, ImportedFile, TradeData
from .settings import get_settings

TRADE_COLUMNS = [
    "REPORTER",
    "PARTNER",
    "TRADE_TYPE",
    "PRODUCT_NC",
    "PRODUCT_SITC",
    "PRODUCT_CPA21",
    "PRODUCT_CPA22",
    "PRODUCT_BEC",
    "PRODUCT_BEC5",
    "PRODUCT_SECTION",
    "FLOW",
    "STAT_PROCEDURE",
    "SUPPL_UNIT",
    "PERIOD",
    "VALUE_EUR",
    "VALUE_NAC",
    "QUANTITY_KG",
    "QUANTITY_SUPPL_UNIT",
]
MEASURES = TRADE_COLUMNS[-4:]


def sql_literal(value):
    """Quote a SQL string literal (paths are never interpolated unescaped)."""
    return "'" + str(value).replace("'", "''") + "'"


def make_engine():
    """Create/open the configured DuckDB and create SQLAlchemy tables."""
    config = get_settings().database
    config.path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("duckdb", database=str(config.path)),
        connect_args={
            "config": {
                "memory_limit": config.memory_limit,
                "threads": config.threads,
                "preserve_insertion_order": True,
            }
        },
    )
    # DuckDB's DBAPI returns Decimal natively. The PostgreSQL-derived dialect default
    # would otherwise round exact DECIMAL values through SQLAlchemy's float processor.
    engine.dialect.supports_native_decimal = True
    Base.metadata.create_all(engine)
    return engine


def local_files():
    """Find archives and metadata recursively; avoid importing existing extractions twice."""
    root = get_settings().download.directory
    archives = sorted(root.rglob("*.7z"))
    metadata = sorted(
        p for p in root.rglob("*.txt") if p.name in {"CN.txt", "PARTNERS_ISO.txt", "PARTNERS.txt"}
    )
    loose = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".dat", ".csv"} or not path.is_file():
            continue
        if any(
            path.is_relative_to(archive.with_suffix(""))
            or path == archive.parent / re.sub(r"_v2_", "_", archive.stem + path.suffix)
            for archive in archives
        ):
            continue
        loose.append(path)
    return metadata + archives + loose


def classification_years(files):
    """Include configured years and years of already downloaded trade files."""
    config = get_settings().download
    years = set(range(int(config.start_date[:4]), int(config.end_date[:4]) + 1))
    for path in files:
        match = re.search(r"(\d{4})(?:0[1-9]|1[0-2]|52)\.(?:7z|dat|csv)$", path.name)
        if match:
            years.add(int(match[1]))
    return sorted(years)


@contextmanager
def trade_csv(path):
    """Extract one archive's data file into an automatically cleaned temporary directory."""
    if path.suffix.lower() != ".7z":
        yield path
        return
    with TemporaryDirectory(prefix="comext-") as directory:
        destination = Path(directory).resolve()
        with py7zr.SevenZipFile(path) as archive:
            members = archive.list()
            for member in members:
                name = PurePosixPath(member.filename.replace("\\", "/"))
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or ":" in member.filename
                    or getattr(member, "is_symlink", False)
                ):
                    raise ValueError(f"Unsafe archive member: {member.filename}")
            data = [
                m.filename
                for m in members
                if not m.is_directory and Path(m.filename).suffix.lower() in {".dat", ".csv"}
            ]
            if len(data) != 1:
                raise ValueError(
                    f"Expected exactly one trade CSV/.dat in archive, found {len(data)}"
                )
            archive.extract(path=destination, targets=data)
        extracted = (destination / data[0]).resolve()
        if not extracted.is_relative_to(destination):
            raise ValueError("Extracted file escapes temporary directory")
        yield extracted


def stage_trade(connection, path):
    """Preserve original CSV positions and exact decimals while selecting LU in DuckDB."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), None)
    if header != TRADE_COLUMNS:
        raise ValueError(f"Unsupported Comext header in {path.name}: {header!r}")
    columns = "{" + ", ".join(f"{sql_literal(c)}: 'VARCHAR'" for c in TRADE_COLUMNS) + "}"
    codes = "[" + ", ".join(sql_literal(c) for c in TRADE_COLUMNS[:-4]) + "]"
    expressions = []
    for column in TRADE_COLUMNS:
        if column in MEASURES:
            # DECIMAL casts can silently round; reject excess precision instead.
            expressions.append(
                f"CASE WHEN {column} IS NULL THEN NULL "
                f"WHEN regexp_full_match({column}, '[-+]?[0-9]+(\\.[0-9]{{1,4}})?') "
                f"THEN CAST({column} AS DECIMAL(28,4)) "
                f"ELSE error('Invalid/excess precision in {column}') END AS {column.lower()}"
            )
        else:
            expressions.append(f"{column} AS {column.lower()}")
    connection.exec_driver_sql(
        "CREATE TEMP TABLE staged_trade AS WITH numbered AS ("
        "SELECT row_number() OVER () AS row_number, * FROM read_csv("
        f"{sql_literal(path)}, header=true, delim=',', auto_detect=false, "
        f"columns={columns}, force_not_null={codes}, parallel=false, strict_mode=true, "
        "ignore_errors=false)) SELECT row_number, "
        + ", ".join(expressions)
        + " FROM numbered WHERE REPORTER = ?",
        (get_settings().import_.reporter,),
    )
    return connection.exec_driver_sql("SELECT count(*) FROM staged_trade").scalar_one()


def stage_metadata(connection, path, file_type, years):
    """Parse verified headerless TSV: code, valid-from, valid-to, English description."""
    connection.exec_driver_sql(
        "CREATE TEMP TABLE raw_metadata AS SELECT row_number() OVER () AS position, "
        "code, strptime(valid_from, '%d/%m/%Y')::DATE AS valid_from, "
        "strptime(valid_to, '%d/%m/%Y')::DATE AS valid_to, description FROM read_csv("
        f"{sql_literal(path)}, header=false, delim='\t', quote='', escape='', "
        "auto_detect=false, columns={'code':'VARCHAR','valid_from':'VARCHAR',"
        "'valid_to':'VARCHAR','description':'VARCHAR'}, "
        "force_not_null=['code','description'], parallel=false, strict_mode=true, "
        "ignore_errors=false)"
    )
    invalid = connection.exec_driver_sql(
        "SELECT count(*) FROM raw_metadata WHERE code = '' OR valid_from IS NULL "
        "OR valid_to IS NULL OR valid_from > valid_to"
    ).scalar_one()
    if invalid:
        raise ValueError(f"{invalid} invalid classification validity intervals")
    if file_type == "partner":
        connection.exec_driver_sql(
            "CREATE TEMP TABLE staged_metadata AS SELECT code, description AS name_en "
            "FROM raw_metadata QUALIFY row_number() OVER (PARTITION BY code "
            "ORDER BY valid_from DESC, valid_to DESC, position DESC) = 1"
        )
        table, cols = "dim_partner", "code, name_en"
    else:
        values = ",".join(f"({year})" for year in years)
        connection.exec_driver_sql(
            "CREATE TEMP TABLE staged_metadata AS SELECT y.year::INTEGER AS year, "
            "m.code, m.description AS description_en FROM raw_metadata m "
            f"CROSS JOIN (VALUES {values}) y(year) "
            "WHERE year(m.valid_from) <= y.year AND year(m.valid_to) >= y.year "
            "QUALIFY row_number() OVER (PARTITION BY y.year, m.code "
            "ORDER BY m.valid_from DESC, m.valid_to DESC, m.position DESC) = 1"
        )
        table, cols = "dim_product_nc", "year, code, description_en"
    count = connection.exec_driver_sql("SELECT count(*) FROM staged_metadata").scalar_one()
    if not count:
        raise ValueError("No applicable classification records")
    return count, table, cols


def import_file(engine, path, years):
    """Atomically load a single file; failures leave no tracking record or partial data."""
    source_path = path.relative_to(get_settings().download.directory).as_posix()
    if len(source_path) > 512:
        raise ValueError("source path exceeds 512 characters")
    file_type = (
        "cn"
        if path.name == "CN.txt"
        else ("partner" if path.name in {"PARTNERS_ISO.txt", "PARTNERS.txt"} else "trade")
    )
    with engine.begin() as connection:
        if connection.execute(
            select(ImportedFile.source_path).where(ImportedFile.source_path == source_path)
        ).first():
            print(f"skipped {source_path}", flush=True)
            return None
        digest = sha256(path)
        receipt = read_receipt(path)
        if receipt and (receipt["sha256"] != digest or receipt["size"] != path.stat().st_size):
            raise ValueError("file differs from completed download receipt")
        # Pre-existing downloads without provenance use a local URI, never a guessed URL.
        source_url = receipt["source_url"] if receipt else path.resolve().as_uri()
        if file_type == "trade":
            with trade_csv(path) as extracted:
                rows = stage_trade(connection, extracted)
        else:
            rows, table, columns = stage_metadata(connection, path, file_type, years)
        # Staging succeeded. The immediate source FK requires this insert before facts;
        # both writes remain invisible until the same transaction commits.
        connection.execute(
            insert(ImportedFile).values(
                source_path=source_path,
                file_type=file_type,
                source_url=source_url,
                sha256=digest,
                rows_loaded=rows,
            )
        )
        if file_type == "trade":
            columns = ", ".join(c.name for c in TradeData.__table__.columns)
            connection.exec_driver_sql(
                f"INSERT INTO trade_data ({columns}) SELECT ?, * FROM staged_trade",
                (source_path,),
            )
            connection.exec_driver_sql("DROP TABLE staged_trade")
        else:
            connection.exec_driver_sql(
                f"INSERT INTO {table} ({columns}) SELECT {columns} FROM staged_metadata "
                "ON CONFLICT DO UPDATE SET "
                + (
                    "name_en = excluded.name_en"
                    if file_type == "partner"
                    else "description_en = excluded.description_en"
                )
            )
            connection.exec_driver_sql("DROP TABLE staged_metadata")
            connection.exec_driver_sql("DROP TABLE raw_metadata")
    print(f"imported {source_path}: {rows} rows", flush=True)
    return rows


def run_load():
    """Process each downloaded source sequentially, committing or rolling back each file."""
    get_settings()
    files = local_files()
    if not files:
        raise ValueError("No downloaded files found; run python -m comext download first")
    years = classification_years(files)
    counts = dict.fromkeys(("imported", "skipped", "failed", "rows"), 0)
    engine = make_engine()
    try:
        for path in files:
            print(f"loading {path.name}", flush=True)
            try:
                rows = import_file(engine, path, years)
                counts["skipped" if rows is None else "imported"] += 1
                counts["rows"] += rows or 0
            except Exception as exc:
                counts["failed"] += 1
                print(f"failed {path.name}: {getattr(exc, 'orig', exc)}", flush=True)
    finally:
        engine.dispose()
    # TODO: explicit revision/re-import policy and extending CN years on incremental updates.
    print("load: " + ", ".join(f"{k}={v}" for k, v in counts.items()), flush=True)
    return counts["failed"]
