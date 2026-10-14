"""Download manifest: what was fetched, from where, when, and its checksum (GUIDELINES §4).

The manifest is rewritten atomically after every file, so an interrupted run keeps its progress
and the next run only fetches what is missing or was republished by Eurostat.
"""

import hashlib
import json
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from luxtrade.config import DATASET_ID, ROOT_DIR


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    """Return the hex SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str | None:
    """Return the current git commit of the code, or None outside a repository."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Manifest:
    """Thread-safe JSON manifest with one entry per downloaded file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        if path.exists():
            self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"dataset": DATASET_ID, "files": {}, "codelists": {}}
        self.data.setdefault("files", {})
        self.data.setdefault("codelists", {})

    def get(self, section: str, name: str) -> dict[str, Any] | None:
        """Return the entry for ``name`` in ``section`` ('files' or 'codelists')."""
        return self.data[section].get(name)

    def record(self, section: str, name: str, entry: dict[str, Any]) -> None:
        """Store an entry and write the manifest to disk."""
        with self._lock:
            self.data[section][name] = entry
            self.data["git_commit"] = git_commit()
            self.data["updated_at"] = utc_now()
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
