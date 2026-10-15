import pytest

from luxtrade.config import BULK_DATA_DIR
from luxtrade.ingest import download as dl
from luxtrade.ingest.manifest import Manifest

LISTING = """<table><tr><th>Name</th></tr>
<tr><td> &nbsp;<a href="">full_partxixu_v2_202101.7z</a></td><td title="1846088 bytes">1.76 MB</td>
<td class="center">7z</td><td> &nbsp;16/07/2026 09:50:18</td></tr>
<tr><td> &nbsp;<a href="">full_v2_200201.7z</a></td><td title="25611111 bytes">24 MB</td>
<td class="center">7z</td><td> &nbsp;16/07/2026 09:50:18</td></tr>
<tr><td> &nbsp;<a href="">full_v2_200252.7z</a></td><td title="99 bytes">1 MB</td>
<td class="center">7z</td><td> &nbsp;16/07/2026 09:50:18</td></tr>
<tr><td> &nbsp;<a href="">full_v2_202512.7z</a></td><td title="45738408 bytes">44 MB</td>
<td class="center">7z</td><td> &nbsp;14/10/2026 11:00:00</td></tr>
<tr><td> &nbsp;<a href="">Important note.txt</a></td><td title="10 bytes">1 KB</td>
<td class="center">txt</td><td> &nbsp;06/01/2026 10:00:00</td></tr>
</table>"""


def test_parse_listing_reads_name_size_and_server_date():
    files = dl.parse_listing(LISTING, BULK_DATA_DIR)
    assert [f.name for f in files][:2] == ["full_partxixu_v2_202101.7z", "full_v2_200201.7z"]
    dec = next(f for f in files if f.name == "full_v2_202512.7z")
    assert dec.size == 45738408 and dec.server_date == "14/10/2026 11:00:00"


def test_select_months_keeps_monthly_files_in_range_only():
    files = dl.parse_listing(LISTING, BULK_DATA_DIR)
    assert [f.name for f in dl.select_months(files, "200201", None)] == [
        "full_v2_200201.7z",
        "full_v2_202512.7z",
    ]
    assert [f.name for f in dl.select_months(files, "200301", "202512")] == ["full_v2_202512.7z"]


def test_file_url_encodes_the_folder():
    url = dl.file_url(BULK_DATA_DIR, "full_v2_202512.7z")
    assert url.endswith("downfile=comext%2FCOMEXT_DATA%2FPRODUCTS%2Ffull_v2_202512.7z")


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise dl.requests.HTTPError(str(self.status_code))

    def iter_content(self, _chunk):
        yield self.body


class FakeSession:
    """Serves ``content``; honours Range unless ``ignore_range``; can fail the first call."""

    def __init__(self, content, ignore_range=False, fail_first=False):
        self.content, self.ignore_range, self.fail_first = content, ignore_range, fail_first
        self.ranges = []

    def get(self, url, headers=None, stream=False, timeout=None):
        rng = (headers or {}).get("Range")
        self.ranges.append(rng)
        if self.fail_first:
            self.fail_first = False
            raise dl.requests.ConnectionError("network down")
        if rng and not self.ignore_range:
            start = int(rng.split("=")[1].rstrip("-"))
            return FakeResponse(206, self.content[start:])
        return FakeResponse(200, self.content)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(dl.time, "sleep", lambda _s: None)


def test_download_resumes_a_partial_file(tmp_path):
    content = b"0123456789" * 10
    dest = tmp_path / "f.7z"
    (tmp_path / "f.7z.part").write_bytes(content[:40])
    session = FakeSession(content)
    assert dl.download_file(session, "u", dest, len(content)) == 206
    assert dest.read_bytes() == content and session.ranges == ["bytes=40-"]


def test_download_restarts_when_server_ignores_range(tmp_path):
    content = b"abcdef" * 5
    dest = tmp_path / "f.7z"
    (tmp_path / "f.7z.part").write_bytes(b"garbage")
    assert dl.download_file(FakeSession(content, ignore_range=True), "u", dest, len(content)) == 200
    assert dest.read_bytes() == content


def test_download_retries_after_a_network_error(tmp_path):
    content = b"x" * 50
    session = FakeSession(content, fail_first=True)
    dl.download_file(session, "u", tmp_path / "f.7z", len(content))
    assert (tmp_path / "f.7z").read_bytes() == content and len(session.ranges) == 2


def test_download_fails_loudly_on_wrong_size(tmp_path):
    with pytest.raises(RuntimeError, match="download failed"):
        dl.download_file(FakeSession(b"short"), "u", tmp_path / "f.7z", 999, retries=2)


def test_manifest_round_trip_and_currency_check(tmp_path):
    interim = tmp_path / "interim"
    for sub, name in (("lu", "lu_202512"), ("eu_hs2", "eu_hs2_202512")):
        (interim / sub).mkdir(parents=True)
        (interim / sub / f"{name}.parquet").write_bytes(b"x")
    remote = dl.RemoteFile(BULK_DATA_DIR, "full_v2_202512.7z", 10, "14/10/2026 11:00:00")
    m = Manifest(tmp_path / "manifest.json")
    m.record("files", remote.name, {"status": "ok", "size": 10, "server_date": remote.server_date})
    entry = Manifest(tmp_path / "manifest.json").get("files", remote.name)
    assert dl.is_current(entry, remote, interim)
    republished = dl.RemoteFile(BULK_DATA_DIR, remote.name, 10, "15/10/2026 08:00:00")
    assert not dl.is_current(entry, republished, interim)


def test_offline_run_reduces_local_archives_and_keeps_them(bulk_raw, tmp_path):
    interim = tmp_path / "interim"
    assert dl.run("202512", None, bulk_raw, interim, workers=2, offline=True) == 0
    assert (interim / "lu" / "lu_202512.parquet").exists()
    assert (interim / "lu" / "lu_202601.parquet").exists()
    assert (bulk_raw / "bulk" / "full_v2_202512.7z").exists()  # only copy: never deleted
    manifest = Manifest(bulk_raw / "manifest.json")
    assert manifest.get("files", "full_v2_202512.7z")["rows_lu"] == 7
    assert len(manifest.get("files", "full_v2_202512.7z")["sha256"]) == 64
