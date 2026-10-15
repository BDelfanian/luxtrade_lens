"""Discover real Eurostat links and download files atomically."""

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import py7zr
import requests

from .settings import get_settings


@dataclass(frozen=True)
class RemoteFile:
    """A file discovered in an official listing, never a generated filename."""

    name: str
    url: str
    size: int | None = None


class ListingParser(HTMLParser):
    """Parse file links and exact byte sizes from Eurostat's HTML table."""

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.files = []
        self.directories = set()
        self.pending = None
        self.size = None

    def handle_starttag(self, tag, attrs):
        """Collect links and sizes from a table row."""
        attrs = dict(attrs)
        if tag == "tr":
            self.pending, self.size = None, None
        if tag == "td":
            match = re.fullmatch(r"(\d+) bytes", attrs.get("title", ""))
            if match:
                self.size = int(match[1])
        if tag == "a" and "href" in attrs:
            url = urljoin(self.url, attrs["href"])
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname != "ec.europa.eu":
                return
            query = parse_qs(parts.query)
            if "file" in query:
                self.pending = (PurePosixPath(query["file"][0]).name, url)
            elif "dir" in query:
                parent = parse_qs(urlsplit(self.url).query).get("dir", [""])[0]
                if query["dir"][0].startswith(parent.rstrip("/") + "/"):
                    self.directories.add(url)

    def handle_endtag(self, tag):
        """Finish a discovered file's table row."""
        if tag == "tr" and self.pending:
            self.files.append(RemoteFile(*self.pending, self.size))
            self.pending = None


def listing(session, url):
    """Request HTML explicitly, following the API's documented listing format."""
    parts = urlsplit(str(url))
    query = parse_qs(parts.query)
    query["format"] = ["html"]
    url = urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
    response = session.get(url, timeout=get_settings().download.timeout_seconds)
    response.raise_for_status()
    parser = ListingParser(response.url)
    parser.feed(response.text)
    if not parser.files and not parser.directories:
        raise ValueError(f"No Eurostat file/directory links found in {url}")
    return parser


def selected_trade(name):
    """Apply patterns and reference periods to discovered names, including annual 52."""
    config = get_settings().download
    if not any(fnmatch.fnmatchcase(name, p) for p in config.include):
        return False
    if any(fnmatch.fnmatchcase(name, p) for p in config.exclude):
        return False
    match = re.search(r"(\d{4})(\d{2})\.7z$", name)
    if not match:
        return False
    year, month = match.groups()
    if month == "52":
        return config.start_date[:4] <= year <= config.end_date[:4]
    return "01" <= month <= "12" and config.start_date <= f"{year}-{month}" <= config.end_date


def metadata_files(session):
    """Follow listed classification folders; CN.txt contains historical validity intervals."""
    start = str(get_settings().sources.metadata)
    queue, visited, found = [start], set(), {}
    while queue:
        url = queue.pop(0)
        directory = parse_qs(urlsplit(url).query).get("dir", [""])[0]
        if directory in visited:
            continue
        visited.add(directory)
        page = listing(session, url)
        for remote in page.files:
            if remote.name in {"CN.txt", "PARTNERS_ISO.txt"}:
                found[remote.name] = remote
        for child in sorted(page.directories):
            name = PurePosixPath(parse_qs(urlsplit(child).query)["dir"][0]).name
            if name in {"CLASSIFICATIONS_AND_RELATIONS", "CLASSIFICATIONS", "ENGLISH"}:
                queue.append(child)
    missing = {"CN.txt", "PARTNERS_ISO.txt"} - found.keys()
    if missing:
        raise ValueError(
            f"Official English metadata missing from directory listing: {sorted(missing)}"
        )
    return [found[name] for name in sorted(found)]


def sha256(path):
    """Hash a file in bounded memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def receipt_path(path):
    """Return the per-file provenance/completion sidecar path."""
    return path.with_name(path.name + ".download.json")


def read_receipt(path):
    """Read download provenance, which is data rather than application configuration."""
    sidecar = receipt_path(path)
    return json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else None


def write_receipt(path, remote, file_type):
    """Write a completion receipt only for a verified complete file."""
    record = {
        "source_url": remote.url,
        "sha256": sha256(path),
        "size": path.stat().st_size,
        "file_type": file_type,
    }
    target = receipt_path(path)
    temporary = target.with_name(target.name + ".part")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def validate_payload(path, file_type):
    """Reject HTML error bodies and malformed archives/metadata before publishing them."""
    if file_type == "trade":
        with py7zr.SevenZipFile(path) as archive:
            if not archive.getnames() or archive.test() is False:
                raise ValueError("invalid 7z archive/packed CRC")
    else:
        with path.open(encoding="utf-8-sig") as stream:
            rows = 0
            for line in stream:
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) != 4 or any(
                    not re.fullmatch(r"\d{2}/\d{2}/\d{4}", field) for field in fields[1:3]
                ):
                    raise ValueError("expected official four-column tab-separated classification")
                rows += 1
        if not rows:
            raise ValueError("empty classification file")


def download_file(session, remote, file_type):
    """Skip complete files; stream to .part and rename after size/format validation."""
    root = get_settings().download.directory
    folder = root / ("monthly_trade" if file_type == "trade" else "classifications")
    folder.mkdir(parents=True, exist_ok=True)
    candidates = list(root.rglob(remote.name))
    for path in candidates:
        try:
            receipt = read_receipt(path)
            if receipt:
                complete = (
                    path.stat().st_size == receipt["size"] and sha256(path) == receipt["sha256"]
                )
            else:
                # Adopt complete legacy downloads without silently replacing an older
                # revision just because today's directory lists a different size.
                complete = path.stat().st_size > 0
            if complete:
                validate_payload(path, file_type)
        except (OSError, ValueError, KeyError, py7zr.Bad7zFile):
            complete = False
        if complete:
            if not receipt:
                write_receipt(path, remote, file_type)
            print(f"skipped {path.name}", flush=True)
            return "skipped"
    path = folder / remote.name
    temporary = path.with_name(path.name + ".part")
    try:
        with session.get(
            remote.url,
            stream=True,
            timeout=get_settings().download.timeout_seconds,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            response.raise_for_status()
            expected = response.headers.get("Content-Length")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
            actual = temporary.stat().st_size
            if actual == 0 or (expected is not None and actual != int(expected)):
                raise ValueError("incomplete HTTP response")
            if remote.size is not None and actual != remote.size:
                raise ValueError("download size differs from directory listing; retry discovery")
        validate_payload(temporary, file_type)
        temporary.replace(path)
        write_receipt(path, remote, file_type)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"downloaded {path.name}", flush=True)
    return "downloaded"


def run_download():
    """Download selected archives and their official classification metadata."""
    settings = get_settings()
    counts = dict.fromkeys(("downloaded", "skipped", "failed"), 0)
    with requests.Session() as session:
        trades = [
            r for r in listing(session, settings.sources.products).files if selected_trade(r.name)
        ]
        if not trades:
            raise ValueError("No available trade archives match configured dates and patterns")
        metadata = metadata_files(session)
        print(f"selected {len(trades)} trade archives, {len(metadata)} metadata files", flush=True)
        work = [(r, "trade") for r in trades] + [
            (r, "cn" if r.name == "CN.txt" else "partner") for r in metadata
        ]
        for remote, file_type in work:
            try:
                counts[download_file(session, remote, file_type)] += 1
            except Exception as exc:
                counts["failed"] += 1
                print(f"failed {remote.name}: {exc}", flush=True)
    # TODO: incremental downloads and explicit policies for revised Eurostat archives/metadata.
    print("download: " + ", ".join(f"{k}={v}" for k, v in counts.items()), flush=True)
    return counts["failed"]
