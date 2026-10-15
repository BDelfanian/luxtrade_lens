"""Download the Comext bulk files for DS-045409 and reduce them to small LU extracts.

For each month ``full_v2_YYYYMM.7z`` (~25–45 MB) the script:

1. downloads it to ``data/raw/bulk/``, **resuming** a partial ``.part`` file with HTTP Range,
   retrying with back-off, and checking the size announced by the Eurostat listing;
2. reduces it right away to ``data/interim/`` (all LU rows + EU HS2 summaries, ``reduce.py``);
3. deletes the archive (unless ``--keep-archives``) so disk use stays ~1 GB instead of ~11 GB;
4. records URL, server date, size, SHA-256, row counts and git commit in ``data/raw/manifest.json``.

Re-running only fetches months that are missing or that Eurostat has republished (new server
date), so an interrupted run simply continues. The EN/FR/DE code lists (CN, partners) are
fetched too, into ``data/raw/codelists/``.

Usage::

    python -m luxtrade.ingest.download                    # everything, 2002-01 → latest
    python -m luxtrade.ingest.download --from 2024-01     # quick real-data subset (~5 min)
    python -m luxtrade.ingest.download --dry-run          # list what would be fetched
    python -m luxtrade.ingest.download --offline          # only reduce .7z files already in
                                                          # data/raw/bulk/ (e.g. browser download)
"""

import argparse
import logging
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

from luxtrade.config import (
    BULK_CODELIST_DIR,
    BULK_DATA_DIR,
    BULK_FILES_URL,
    CODELIST_FILES,
    CODELIST_LANGUAGES,
    INTERIM_DIR,
    MANIFEST_FILE,
    RAW_DIR,
    SERIES_FIRST_YEAR,
)
from luxtrade.ingest.manifest import Manifest, sha256_of, utc_now
from luxtrade.ingest.reduce import interim_paths, reduce_archive
from luxtrade.logging_setup import setup_logging, timed

logger = logging.getLogger(__name__)

MONTHLY_RE = re.compile(r"^full_v2_(\d{4})(\d{2})\.7z$")  # excludes annual YYYY52 files
_ROW_RE = re.compile(
    r'>(?P<name>[^<>]+\.(?:7z|txt))</a>.*?title="(?P<size>\d+) bytes".*?'
    r"(?P<date>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})",
    re.DOTALL,
)
_TIMEOUT = (20, 120)  # connect, read (seconds)
_CHUNK = 1 << 20
USER_AGENT = "luxtrade/0.1 (STATEC Hackathon 2026, The Outliers)"


@dataclass(frozen=True)
class RemoteFile:
    """One file of the Eurostat bulk listing."""

    folder: str
    name: str
    size: int | None
    server_date: str | None

    @property
    def url(self) -> str:
        """Direct download URL."""
        return file_url(self.folder, self.name)


def file_url(folder: str, name: str) -> str:
    """Build the bulk download URL of ``name`` in ``folder``."""
    return f"{BULK_FILES_URL}?sort=1&downfile={quote(f'{folder}/{name}', safe='')}"


def listing_url(folder: str) -> str:
    """Build the URL of the HTML listing of a bulk folder."""
    return f"{BULK_FILES_URL}?sort=1&dir={quote(folder, safe='')}"


def parse_listing(html: str, folder: str) -> list[RemoteFile]:
    """Parse the Eurostat bulk HTML listing into files with size and server date."""
    files = []
    for row in html.split("<tr>"):
        if m := _ROW_RE.search(row):
            files.append(RemoteFile(folder, m["name"].strip(), int(m["size"]), m["date"]))
    return files


def period_of(name: str) -> str | None:
    """Return ``YYYYMM`` for a monthly bulk file name, else None (annual, partxixu, notes)."""
    m = MONTHLY_RE.match(name)
    if m and 1 <= int(m[2]) <= 12:
        return m[1] + m[2]
    return None


def select_months(files: list[RemoteFile], first: str, last: str | None) -> list[RemoteFile]:
    """Keep monthly files with ``first <= YYYYMM <= last`` (``last`` None = no upper bound)."""
    out = []
    for f in files:
        p = period_of(f.name)
        if p and p >= first and (last is None or p <= last):
            out.append(f)
    return sorted(out, key=lambda f: f.name)


def make_session() -> requests.Session:
    """HTTP session; uses the OS certificate store when available (corporate proxies)."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:  # pragma: no cover - optional
        pass
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def fetch_listing(session: requests.Session, folder: str) -> list[RemoteFile]:
    """Download and parse the listing of a bulk folder."""
    resp = session.get(listing_url(folder), timeout=_TIMEOUT)
    resp.raise_for_status()
    files = parse_listing(resp.text, folder)
    if not files:
        raise RuntimeError(f"empty or unreadable Eurostat listing for {folder}")
    return files


def download_file(
    session: requests.Session,
    url: str,
    dest: Path,
    expected_size: int | None = None,
    retries: int = 6,
) -> int:
    """Download ``url`` to ``dest``, resuming ``dest.part`` across retries; return HTTP status.

    Raises:
        RuntimeError: if the file still fails (or has the wrong size) after ``retries`` attempts.

    """
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if expected_size is not None and have > expected_size:
            part.unlink()
            have = 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with session.get(url, headers=headers, stream=True, timeout=_TIMEOUT) as resp:
                if resp.status_code == 416 and have == expected_size:
                    status = 206  # already complete
                elif resp.status_code == 416:
                    part.unlink()  # unusable partial file: start again
                    raise OSError("range not satisfiable")
                else:
                    resp.raise_for_status()
                    status = resp.status_code
                    mode = "ab" if status == 206 else "wb"  # 200 = server ignored Range
                    with part.open(mode) as fh:
                        for block in resp.iter_content(_CHUNK):
                            fh.write(block)
            size = part.stat().st_size
            if expected_size is not None and size != expected_size:
                raise OSError(f"size {size} != expected {expected_size}")
            part.replace(dest)
            return status
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            wait = min(60, 2**attempt)
            logger.warning(
                "%s: attempt %d/%d failed (%s); retry in %ds",
                dest.name,
                attempt,
                retries,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"{dest.name}: download failed after {retries} attempts: {last_error}")


def is_current(entry: dict | None, remote: RemoteFile, interim_dir: Path) -> bool:
    """True if a manifest entry matches the remote file and its extracts exist."""
    if not entry or entry.get("status") != "ok":
        return False
    if remote.server_date and entry.get("server_date") != remote.server_date:
        return False  # republished by Eurostat (revision)
    if remote.size and entry.get("size") != remote.size:
        return False
    period = period_of(remote.name)
    return period is not None and all(p.exists() for p in interim_paths(interim_dir, period))


def process_month(
    session: requests.Session | None,
    remote: RemoteFile,
    raw_dir: Path,
    interim_dir: Path,
    manifest: Manifest,
    keep_archives: bool,
) -> None:
    """Download (unless offline) and reduce one monthly archive, then record it."""
    period = period_of(remote.name)
    archive = raw_dir / "bulk" / remote.name
    t0 = time.perf_counter()
    status = None
    if session is not None and not (archive.exists() and archive.stat().st_size == remote.size):
        status = download_file(session, remote.url, archive, remote.size)
    t1 = time.perf_counter()
    size = archive.stat().st_size
    sha = sha256_of(archive)
    result = reduce_archive(archive, period, interim_dir, raw_dir / "tmp")
    t2 = time.perf_counter()
    if not keep_archives:
        archive.unlink()
    manifest.record(
        "files",
        remote.name,
        {
            "status": "ok",
            "period": period,
            "url": remote.url,
            "server_date": remote.server_date,
            "size": size,
            "sha256": sha,
            "http_status": status,
            "downloaded_at": utc_now(),
            "rows_total": result.rows_total,
            "rows_lu": result.rows_lu,
            "rows_eu_hs2": result.rows_eu_hs2,
            "archive_kept": keep_archives,
        },
    )
    logger.info(
        "%s: %.1f MB, download %.1fs, reduce %.1fs, %d LU rows",
        remote.name,
        size / 1e6,
        t1 - t0,
        t2 - t1,
        result.rows_lu,
    )


@timed
def download_codelists(session: requests.Session, raw_dir: Path, manifest: Manifest) -> None:
    """Fetch the CN and partner code lists in EN, FR and DE (skip unchanged files)."""
    for lang, folder_name in CODELIST_LANGUAGES.items():
        folder = f"{BULK_CODELIST_DIR}/{folder_name}"
        remote = {f.name: f for f in fetch_listing(session, folder)}
        for name in CODELIST_FILES:
            f = remote.get(name)
            if f is None:
                raise RuntimeError(f"code list {name} not found in {folder}")
            dest = raw_dir / "codelists" / lang / name
            key = f"{lang}/{name}"
            entry = manifest.get("codelists", key)
            if entry and entry.get("server_date") == f.server_date and dest.exists():
                continue
            status = download_file(session, f.url, dest, f.size)
            manifest.record(
                "codelists",
                key,
                {
                    "url": f.url,
                    "server_date": f.server_date,
                    "size": dest.stat().st_size,
                    "sha256": sha256_of(dest),
                    "http_status": status,
                    "downloaded_at": utc_now(),
                },
            )
            logger.info("code list %s downloaded", key)


def local_months(raw_dir: Path, first: str, last: str | None) -> list[RemoteFile]:
    """Monthly archives already present in ``raw_dir/bulk`` (offline mode)."""
    files = [
        RemoteFile(BULK_DATA_DIR, p.name, p.stat().st_size, None)
        for p in (raw_dir / "bulk").glob("full_v2_*.7z")
    ]
    return select_months(files, first, last)


@timed
def run(
    first: str,
    last: str | None,
    raw_dir: Path = RAW_DIR,
    interim_dir: Path = INTERIM_DIR,
    workers: int = 3,
    keep_archives: bool = False,
    offline: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """Download and reduce all months in ``[first, last]``; return the number of failures."""
    manifest = Manifest(raw_dir / MANIFEST_FILE)
    session = None if offline else make_session()
    if session is None:
        months = local_months(raw_dir, first, last)
        keep_archives = True  # never delete the only copy
    else:
        months = select_months(fetch_listing(session, BULK_DATA_DIR), first, last)
    todo = [
        m for m in months if force or not is_current(manifest.get("files", m.name), m, interim_dir)
    ]
    size_gb = sum(m.size or 0 for m in todo) / 1e9
    logger.info("%d monthly files in range, %d to fetch (%.2f GB)", len(months), len(todo), size_gb)
    if dry_run:
        for m in todo:
            logger.info("would fetch %s (%s, %s bytes)", m.name, m.server_date, m.size)
        return 0
    if session is not None:
        download_codelists(session, raw_dir, manifest)
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(process_month, session, m, raw_dir, interim_dir, manifest, keep_archives): m
            for m in todo
        }
        for i, fut in enumerate(as_completed(futures), start=1):
            m = futures[fut]
            try:
                fut.result()
            except Exception:
                failures += 1
                logger.exception("%s failed (re-run the command to retry)", m.name)
            if i % 10 == 0 or i == len(todo):
                logger.info("progress: %d/%d files (%d failed)", i, len(todo), failures)
    shutil.rmtree(raw_dir / "tmp", ignore_errors=True)
    return failures


def _month(value: str) -> str:
    """Parse ``YYYY-MM`` or ``YYYYMM`` into ``YYYYMM``."""
    digits = value.replace("-", "")
    if not re.fullmatch(r"\d{4}(0[1-9]|1[0-2])", digits):
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}")
    return digits


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="first", type=_month, default=f"{SERIES_FIRST_YEAR}01")
    parser.add_argument("--to", dest="last", type=_month, default=None, help="default: latest")
    parser.add_argument("--workers", type=int, default=3, help="parallel downloads (default 3)")
    parser.add_argument("--keep-archives", action="store_true", help="keep the .7z files")
    parser.add_argument("--offline", action="store_true", help="reduce local .7z files only")
    parser.add_argument("--dry-run", action="store_true", help="list files, download nothing")
    parser.add_argument("--force", action="store_true", help="re-fetch even if up to date")
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--interim", type=Path, default=INTERIM_DIR)
    args = parser.parse_args()
    setup_logging()
    failures = run(
        args.first,
        args.last,
        args.raw,
        args.interim,
        args.workers,
        args.keep_archives,
        args.offline,
        args.dry_run,
        args.force,
    )
    if failures:
        raise SystemExit(f"{failures} file(s) failed; re-run the same command to retry them")


if __name__ == "__main__":
    main()
