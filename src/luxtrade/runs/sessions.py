"""Sessions: ordered turns of one conversation, resumable by ID (SOLUTION_DESIGN §5.9)."""

import secrets
from pathlib import Path

from pydantic import BaseModel, Field

from luxtrade import config
from luxtrade.runs.store import RunRecord, RunStore, now_iso

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_session_id() -> str:
    """A short random session ID such as 'k7p2qx'."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


class Session(BaseModel):
    """A session file: its run IDs in order, with what helps find it again."""

    session_id: str
    created_at: str
    updated_at: str = ""  # time of the last question (files before 15 Oct 2026: empty)
    language: str = ""  # language of the first question
    title: str = ""
    runs: list[str] = Field(default_factory=list)

    @property
    def last_active(self) -> str:
        """ISO time of the last question, or of the start for older files."""
        return self.updated_at or self.created_at


class SessionStore:
    """Session files in ``data/runs/sessions/`` (demo sessions in ``demo/runs/sessions/``)."""

    def __init__(
        self, runs: RunStore | None = None, root: Path | None = None, demo_root: Path | None = None
    ) -> None:
        self.runs = runs or RunStore()
        self.root = Path(root or self.runs.root / "sessions")
        self.demo_root = Path(demo_root or config.DEMO_RUNS_DIR / "sessions")
        self.root.mkdir(parents=True, exist_ok=True)
        self._meta: dict[tuple[str, str, str], tuple[str, str]] = {}  # see _complete

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def get(self, session_id: str) -> Session | None:
        """Load a session by ID (own sessions first, then demo sessions)."""
        session_id = session_id.strip().lower()
        for folder in (self.root, self.demo_root):
            path = folder / f"{session_id}.json"
            if path.exists():
                return Session.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def append(self, record: RunRecord) -> Session:
        """Add a run to its session, creating the session file on the first turn."""
        session = self.get(record.session_id) or Session(
            session_id=record.session_id,
            created_at=record.created_at or now_iso(),
            title=record.question[:80],
        )
        if record.run_id not in session.runs:
            session.runs.append(record.run_id)
        session.updated_at = record.created_at or now_iso()
        session.language = session.language or record.language
        self._path(session.session_id).write_text(
            session.model_dump_json(indent=1), encoding="utf-8"
        )
        return session

    def retitle(self, session_id: str, title: str) -> None:
        """Rename a session (e.g. after the scenario its runs belong to)."""
        session = self.get(session_id)
        if session is not None:
            session.title = title[:80]
            self._path(session_id).write_text(session.model_dump_json(indent=1), encoding="utf-8")

    def records(self, session_id: str) -> list[RunRecord]:
        """The session's run records, in turn order."""
        session = self.get(session_id)
        if session is None:
            return []
        recs = [self.runs.load(rid) for rid in session.runs]
        return [r for r in recs if r is not None]

    def next_turn(self, session_id: str) -> int:
        """Turn number for the next question in this session."""
        session = self.get(session_id)
        return len(session.runs) + 1 if session else 1

    def _complete(self, s: Session) -> Session:
        """Fill the metadata older session files lack, from their first and last runs.

        Kept in memory, not written back: the files stay as they were shared.
        """
        if s.runs and not (s.updated_at and s.language):
            cache_key = (s.session_id, s.runs[0], s.runs[-1])
            if cache_key not in self._meta:
                first, last = self.runs.load(s.runs[0]), self.runs.load(s.runs[-1])
                self._meta[cache_key] = (
                    first.language if first else "",
                    last.created_at if last else "",
                )
            language, updated_at = self._meta[cache_key]
            s.language = s.language or language
            s.updated_at = s.updated_at or updated_at
        return s

    def recent(self, limit: int = 30) -> list[Session]:
        """Sessions, most recently active first (own and demo)."""
        found = {}
        for folder in (self.demo_root, self.root):
            if folder.exists():
                for path in folder.glob("*.json"):
                    s = Session.model_validate_json(path.read_text(encoding="utf-8"))
                    found[s.session_id] = s
        sessions = [self._complete(s) for s in found.values()]
        return sorted(sessions, key=lambda s: s.last_active, reverse=True)[:limit]

    def search(self, text: str) -> list[Session]:
        """Sessions whose ID, a run ID, a question or a date (YYYY-MM-DD) contains ``text``."""
        text = text.strip().lower()
        hits = []
        for s in self.recent(limit=500):
            if (
                text in s.session_id
                or any(text in r for r in s.runs)
                or text in s.title.lower()
                or text in s.created_at[:10]
                or text in s.last_active[:10]
            ):
                hits.append(s)
                continue
            if any(text in rec.question.lower() for rec in self.records(s.session_id)):
                hits.append(s)
        return hits
