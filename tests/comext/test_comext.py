"""Offline checks for transactions, exact values, historical metadata, and downloads."""

import csv
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import py7zr
import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError

from comext import download, load, settings
from comext.models import TradeData


@pytest.fixture
def config(tmp_path):
    settings.get_settings.cache_clear()
    config = settings.get_settings()
    config.download.directory = tmp_path / "raw"
    config.download.directory.mkdir()
    config.database.path = tmp_path / "database" / "test.duckdb"
    yield config
    settings.get_settings.cache_clear()


@pytest.fixture
def engine(config):
    engine = load.make_engine()
    yield engine
    engine.dispose()


def trade_row(reporter="LU", value="123.1234"):
    return [
        reporter,
        "FR",
        "E",
        "01012100",
        "00111",
        "0143",
        "0143",
        "111",
        ".....",
        "01",
        "1",
        "1",
        "NO_SU",
        "200201",
        value,
        "0",
        "",
        "0",
    ]


def write_trade(path, rows, header=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(load.TRADE_COLUMNS if header is None else header)
        writer.writerows(rows)
    return path


def test_exact_values_codes_row_numbers_and_skip(config, engine):
    value = "123456789012345678901234.1234"
    row = trade_row(value=value)
    row[4] = ""
    path = write_trade(config.download.directory / "full_200201.dat", [trade_row("DE"), row])
    assert load.import_file(engine, path, [2002]) == 1
    assert load.import_file(engine, path, [2002]) is None
    with engine.connect() as connection:
        record = connection.execute(select(TradeData)).mappings().one()
        assert record["row_number"] == 2
        assert record["reporter"] == "LU"
        assert record["product_nc"] == "01012100"
        assert record["product_sitc"] == ""
        assert record["product_bec5"] == "....."
        assert record["value_eur"] == Decimal(value)
        assert record["quantity_kg"] is None
        assert connection.exec_driver_sql("SELECT rows_loaded FROM imported_files").scalar() == 1
        assert (
            connection.exec_driver_sql("SELECT source_url FROM imported_files")
            .scalar()
            .startswith("file:")
        )


@pytest.mark.parametrize("invalid", ["bad", "1.12345", "1234567890123456789012345.1234"])
def test_bad_measure_rolls_back_and_can_retry(config, engine, invalid):
    path = write_trade(
        config.download.directory / "full_200201.dat", [trade_row(), trade_row(value=invalid)]
    )
    with pytest.raises(DBAPIError):
        load.import_file(engine, path, [2002])
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM trade_data").scalar() == 0
        assert connection.exec_driver_sql("SELECT count(*) FROM imported_files").scalar() == 0
    write_trade(path, [trade_row()])
    assert load.import_file(engine, path, [2002]) == 1


def test_failure_after_tracking_insert_is_atomic(config, engine):
    path = write_trade(config.download.directory / "full_200201.dat", [trade_row()])

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO trade_data"):
            raise RuntimeError("simulated final bulk insert failure")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            load.import_file(engine, path, [2002])
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM imported_files").scalar() == 0
        assert connection.exec_driver_sql("SELECT count(*) FROM trade_data").scalar() == 0
    assert load.import_file(engine, path, [2002]) == 1


def test_history_midyear_changes_literal_quotes_empty_labels(config, engine):
    path = config.download.directory / "CN.txt"
    path.write_text(
        "01011010\t01/01/2002\t31/12/2011\tPure-bred breeding horses\n"
        '01011010\t01/01/2012\t30/06/2012\tOld "literal quotes"\n'
        "01011010\t01/07/2012\t31/12/2500\tNew description\n"
        "ZZZZZZZZ\t01/01/2000\t31/12/2500\t\n",
        encoding="utf-8",
    )
    assert load.import_file(engine, path, [2002, 2011, 2012]) == 6
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT year, description_en FROM dim_product_nc WHERE code='01011010' ORDER BY year"
        ).fetchall()
        assert rows == [
            (2002, "Pure-bred breeding horses"),
            (2011, "Pure-bred breeding horses"),
            (2012, "New description"),
        ]
        assert (
            connection.exec_driver_sql(
                "SELECT DISTINCT description_en FROM dim_product_nc WHERE code='ZZZZZZZZ'"
            ).scalar()
            == ""
        )
    partners = config.download.directory / "PARTNERS_ISO.txt"
    partners.write_text(
        "BE\t01/01/1976\t31/12/1998\tBelgium and Luxembourg\n"
        "BE\t01/01/1999\t31/12/2500\tBelgium\n"
        "QQ\t01/01/2000\t31/12/2500\tStores and provisions\n",
        encoding="utf-8",
    )
    assert load.import_file(engine, partners, [2002]) == 2
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT name_en FROM dim_partner WHERE code='BE'").scalar()
            == "Belgium"
        )
        assert connection.exec_driver_sql("SELECT count(*) FROM dim_partner").scalar() == 2


def test_metadata_failure_rolls_back_and_next_file_succeeds(config, engine):
    path = config.download.directory / "CN.txt"
    path.write_text("01\tinvalid\t31/12/2500\tAnimals\n", encoding="utf-8")
    with pytest.raises(DBAPIError):
        load.import_file(engine, path, [2002])
    path.write_text("01\t01/01/1988\t31/12/2500\tAnimals\n", encoding="utf-8")
    assert load.import_file(engine, path, [2002]) == 1


def test_archive_cleanup_and_duplicate_extractions(config, engine, monkeypatch):
    raw = config.download.directory
    old_extraction = raw / "full_v2_200201" / "full_200201.dat"
    write_trade(old_extraction, [trade_row()])
    path = raw / "full_v2_200201.7z"
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.write(old_extraction, "full_200201.dat")
    temporary_paths = []

    def temporary_directory(**kwargs):
        result = TemporaryDirectory(dir=raw, **kwargs)
        temporary_paths.append(Path(result.name))
        return result

    monkeypatch.setattr(load, "TemporaryDirectory", temporary_directory)
    assert load.local_files() == [path]
    assert load.classification_years([path]) == [2002, 2025]
    assert load.import_file(engine, path, [2002]) == 1
    assert path.exists() and old_extraction.exists()
    assert temporary_paths and all(not p.exists() for p in temporary_paths)


def test_unknown_trade_header_fails(config, engine):
    path = write_trade(config.download.directory / "unknown.csv", [], header=["REPORTER", "VALUE"])
    with pytest.raises(ValueError, match="Unsupported Comext header"):
        load.import_file(engine, path, [2002])


def test_load_continues_after_failure_and_skips_on_retry(config, capsys):
    write_trade(config.download.directory / "a.csv", [trade_row(value="bad")])
    write_trade(config.download.directory / "b.csv", [trade_row()])
    assert load.run_load() == 1
    assert "imported=1, skipped=0, failed=1, rows=1" in capsys.readouterr().out
    write_trade(config.download.directory / "a.csv", [trade_row()])
    assert load.run_load() == 0
    assert "imported=1, skipped=1, failed=0, rows=1" in capsys.readouterr().out


def test_listing_uses_real_links_and_sizes(config):
    parser = download.ListingParser(str(config.sources.products))
    parser.feed(
        '<tr><td><a href="?file=comext%2FCOMEXT_DATA%2FPRODUCTS%2Ffull_v2_202501.7z">'
        'full_v2_202501.7z</a></td><td title="45626163 bytes">43.51 MB</td>'
        '<td><a href="?downfile=something">Download</a></td></tr>'
        '<tr><td><a href="https://example.com/?file=bad.7z">bad</a></td></tr>'
    )
    assert len(parser.files) == 1
    assert parser.files[0].size == 45626163
    assert "file=comext%2FCOMEXT_DATA%2FPRODUCTS%2Ffull_v2_202501.7z" in parser.files[0].url


@pytest.mark.parametrize(
    "name,selected",
    [
        ("full_v2_202501.7z", True),
        ("full_v2_202512.7z", True),
        ("full_v2_202452.7z", False),
        ("full_v2_202552.7z", False),
        ("full_partxixu_v2_202501.7z", False),
        ("full_v2_202601.7z", False),
        ("full_v2_202513.7z", False),
    ],
)
def test_selection(config, name, selected):
    assert download.selected_trade(name) is selected


class Response:
    def __init__(self, content, length=None, interrupted=False):
        self.content = content
        self.headers = {"Content-Length": str(len(content) if length is None else length)}
        self.interrupted = interrupted

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.content
        if self.interrupted:
            raise OSError("connection lost")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_download_atomic_skip_corruption_and_retry(config):
    content = b"AD\t01/01/1976\t31/12/2500\tAndorra\n"
    remote = download.RemoteFile("PARTNERS_ISO.txt", "https://ec.europa.eu/verified", len(content))
    session = Session(Response(content))
    assert download.download_file(session, remote, "partner") == "downloaded"
    path = config.download.directory / "classifications" / remote.name
    assert path.read_bytes() == content
    assert download.read_receipt(path)["source_url"] == remote.url
    assert download.download_file(session, remote, "partner") == "skipped"
    assert session.calls == 1
    path.write_bytes(b"corrupt")
    assert download.download_file(session, remote, "partner") == "downloaded"
    assert session.calls == 2
    assert not list(config.download.directory.rglob("*.part"))


def test_legacy_download_keeps_complete_older_revision(config):
    path = config.download.directory / "PARTNERS_ISO.txt"
    content = b"AD\t01/01/1976\t31/12/2500\tAndorra\n"
    path.write_bytes(content)
    remote = download.RemoteFile(path.name, "https://ec.europa.eu/verified", len(content) + 100)
    session = Session(Response(b"unused"))
    assert download.download_file(session, remote, "partner") == "skipped"
    assert session.calls == 0
    assert path.read_bytes() == content


@pytest.mark.parametrize("interrupted", [False, True])
def test_incomplete_download_never_published(config, interrupted):
    content = b"AD\t01/01/1976\t31/12/2500\tAndorra\n"
    session = Session(Response(content, length=len(content) + 1, interrupted=interrupted))
    remote = download.RemoteFile("PARTNERS_ISO.txt", "https://ec.europa.eu/verified")
    with pytest.raises((OSError, ValueError)):
        download.download_file(session, remote, "partner")
    assert not list(config.download.directory.rglob("PARTNERS_ISO.txt*"))


def test_settings_env_dotenv_yaml_precedence_and_cache(config, tmp_path, monkeypatch):
    sample = tmp_path / ".env"
    sample.write_text("COMEXT_DATABASE__MEMORY_LIMIT=2GB\n", encoding="utf-8")
    monkeypatch.setenv("COMEXT_DATABASE__MEMORY_LIMIT", "3GB")
    assert settings.Settings(_env_file=sample).database.memory_limit == "3GB"
    monkeypatch.delenv("COMEXT_DATABASE__MEMORY_LIMIT")
    assert settings.Settings(_env_file=sample).database.memory_limit == "2GB"
    assert settings.get_settings() is config
    monkeypatch.setenv("COMEXT_IMPORT__REPORTER", "DE")
    with pytest.raises(ValidationError, match="LU"):
        settings.Settings(_env_file=None)
    with pytest.raises(ValidationError, match="start_date"):
        settings.DownloadConfig(
            start_date="2025-13", end_date="2025-12", include=["*"], directory="x"
        )
    with pytest.raises(ValidationError, match="start_date must"):
        settings.DownloadConfig(
            start_date="2026-01", end_date="2025-12", include=["*"], directory="x"
        )


def test_settings_missing_yaml_and_secrets_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Cannot read configuration"):
        settings.Settings(_env_file=None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/download.yaml").write_text("database:\n  password: unsafe\n")
    with pytest.raises(ValueError, match="environment/.env only"):
        settings.Settings(_env_file=None)
