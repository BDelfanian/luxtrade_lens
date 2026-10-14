"""Run records: one JSON file per answer, with IDs and hashes for recall and re-verification.

``run_id`` = first 10 hex chars of SHA-256 over {session, turn, normalised question, spec, SQL,
data vintage, code version}. ``result_hash`` = SHA-256 of the SQL result as canonical CSV, so
**Re-verify** can prove an answer still reproduces (SOLUTION_DESIGN §6).
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from luxtrade import config
from luxtrade.config import ROOT_DIR, STORED_ROWS_LIMIT
from luxtrade.semantic.lookup import normalise


class RunRecord(BaseModel):
    """Everything needed to show, explain, recall and re-verify one answer."""

    run_id: str
    session_id: str
    turn: int
    created_at: str
    origin: str
    status: str  # answered | suggestions | blocked | no_data | error
    question: str
    language: str = "en"
    followup_of: str | None = None
    inherited: list[str] = Field(default_factory=list)
    parent_run_id: str | None = None
    interpretation: dict | None = None
    spec: dict | None = None
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[dict] = Field(default_factory=list)
    suggestions: list[dict] = Field(default_factory=list)
    missing_hint: str = ""
    sql: str | None = None
    custom_sql: bool = False
    result_hash: str | None = None
    row_count: int = 0
    view_kind: str = "table"
    title: str = ""
    frames: dict[str, list[dict]] = Field(default_factory=dict)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    insight: list[str] = Field(default_factory=list)
    insight_source: str = ""
    facts: list[dict] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    trace: list[dict] = Field(default_factory=list)
    llm_usage: list[dict] = Field(default_factory=list)
    code_version: str = ""
    error: str | None = None

    def frame(self, name: str = "main") -> pd.DataFrame:
        """A stored frame as a DataFrame (ISO dates parsed back)."""
        df = pd.DataFrame(self.frames.get(name, []))
        if (
            "period" in df.columns
            and df["period"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}").all()
        ):
            df["period"] = pd.to_datetime(df["period"])
        return df


@cache
def code_version() -> str:
    """Short git commit of the running code ('unknown' outside a checkout)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def make_run_id(
    *, session_id: str, turn: int, question: str, spec: dict | None, sql: str | None, vintage: str
) -> str:
    """Content-addressed run ID (10 hex characters)."""
    payload = _canonical(
        {
            "session": session_id,
            "turn": turn,
            "question": " ".join(normalise(question).split()),
            "spec": spec,
            "sql": sql,
            "vintage": vintage,
            "code": code_version(),
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def result_hash(df: pd.DataFrame | None) -> str | None:
    """SHA-256 of a result table: columns and rows sorted, floats rounded to 6 decimals."""
    if df is None:
        return None
    canon = df.copy()
    canon = canon[sorted(canon.columns)]
    for col in canon.columns:
        if pd.api.types.is_float_dtype(canon[col]):
            canon[col] = canon[col].round(6)
    canon = canon.astype(str).sort_values(list(canon.columns)).reset_index(drop=True)
    return hashlib.sha256(canon.to_csv(index=False).encode("utf-8")).hexdigest()


def frame_records(df: pd.DataFrame | None, limit: int = STORED_ROWS_LIMIT) -> list[dict]:
    """JSON-safe rows for storage (dates as ISO strings, NaN as null)."""
    if df is None or df.empty:
        return []
    out = df.head(limit).copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
        elif out[col].dtype == object:
            out[col] = out[col].map(lambda v: v.isoformat() if hasattr(v, "isoformat") else v)
    return json.loads(out.to_json(orient="records", date_format="iso"))


def now_iso() -> str:
    """UTC timestamp for records."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunStore:
    """Run records on disk (``data/runs/``), read-only fallback to recorded demo runs."""

    def __init__(self, root: Path | None = None, demo_root: Path | None = None) -> None:
        self.root = Path(root or config.RUNS_DIR)
        self.demo_root = Path(demo_root or config.DEMO_RUNS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, record: RunRecord) -> Path:
        """Write a run record (run records are never edited afterwards)."""
        path = self.root / f"{record.run_id}.json"
        path.write_text(record.model_dump_json(indent=1), encoding="utf-8")
        return path

    def load(self, run_id: str) -> RunRecord | None:
        """Load a run by ID from the run store or the demo runs."""
        run_id = run_id.strip().lower()
        for folder in (self.root, self.demo_root):
            path = folder / f"{run_id}.json"
            if path.exists():
                return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        return None
