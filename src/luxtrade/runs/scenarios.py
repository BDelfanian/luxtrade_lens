"""Scenario records: one JSON file per scenario, pointing to the run records of its steps.

A scenario answers a broad question with a chain of assistant runs (agents/scenario.py). Its
record keeps the plan, every step with its run ID, the combined answer and how it was checked,
so the answer can be reopened, re-verified step by step and shared. Own scenarios live in
``data/runs/scenarios/``; recorded examples in ``demo/runs/scenarios/`` (read-only fallback).

The history is the user's to curate: a scenario can be renamed, marked as a favourite and
deleted. Own scenarios are deleted for good; a recorded example is read-only, so deleting it
keeps a hidden copy among the own scenarios that takes it out of the history.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from luxtrade import config


class ScenarioStep(BaseModel):
    """One question of the chain, as it was run."""

    n: int
    kind: str  # "plan" (proposed and kept), "own" (written or edited by the user), "follow-up"
    question: str
    purpose: str = ""
    builds_on: list[int] = Field(default_factory=list)  # follow-ups: the steps that prompted it
    run_id: str = ""
    status: str = ""  # the run's status: answered | suggestions | blocked | no_data | error
    queried: str = ""  # what was queried, in words (from the resolved spec)
    note: str = ""  # what the step adds to the answer (from the combined answer)


class ScenarioRecord(BaseModel):
    """Everything needed to show, explain, re-verify and share one scenario."""

    scenario_id: str
    session_id: str  # the assistant session holding the steps' runs
    created_at: str
    question: str
    language: str = "en"
    title: str = ""  # the planner's name for the investigation
    name: str = ""  # the user's own name for it (rename); shown instead of the title
    favorite: bool = False
    hidden: bool = False  # a recorded example taken out of the history
    based_on: str = ""  # the scenario this one revises (its questions edited and run again)
    approach: str = ""
    out_of_scope: list[str] = Field(default_factory=list)
    steps: list[ScenarioStep] = Field(default_factory=list)
    headline: str = ""
    points: list[dict] = Field(default_factory=list)  # {"text": …, "steps": [n, …]}
    conclusion: str = ""
    charts: list[int] = Field(default_factory=list)  # steps whose charts support the answer
    figures: list[dict] = Field(default_factory=list)  # evidence charts and key figures (code)
    share: dict = Field(default_factory=dict)  # the share card's title and subtitle, checked
    answer_source: str = ""  # "llm" (passed the checks) or "template"
    caveats: list[dict] = Field(default_factory=list)  # {"id": …, "message": …} from the runs
    notes: list[str] = Field(default_factory=list)  # validation and check notes, in order
    llm_usage: list[dict] = Field(default_factory=list)  # plan, follow-up and answer calls
    vintage: str = ""
    code_version: str = ""
    status: str = "answered"  # answered | partial (some steps unanswered) | failed

    def step(self, n: int) -> ScenarioStep | None:
        """The step numbered ``n``."""
        return next((s for s in self.steps if s.n == n), None)

    @property
    def label(self) -> str:
        """The name to show: the user's, else the planner's title, else the question."""
        return self.name or self.title or self.question[:60]

    @property
    def created_local(self) -> str:
        """When it was created, in the local time zone: '2026-10-18 20:26'."""
        try:
            return f"{datetime.fromisoformat(self.created_at).astimezone():%Y-%m-%d %H:%M}"
        except ValueError:
            return self.created_at[:16].replace("T", " ")


class ScenarioStore:
    """Scenario files on disk, newest first; recorded examples as a read-only fallback."""

    def __init__(self, root: Path | None = None, demo_root: Path | None = None) -> None:
        self.root = Path(root or config.RUNS_DIR / "scenarios")
        self.demo_root = Path(demo_root or config.DEMO_RUNS_DIR / "scenarios")
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, record: ScenarioRecord) -> Path:
        """Write a scenario record."""
        path = self.root / f"{record.scenario_id}.json"
        path.write_text(record.model_dump_json(indent=1), encoding="utf-8")
        return path

    def load(self, scenario_id: str) -> ScenarioRecord | None:
        """A scenario by ID, own scenarios first, then the recorded examples."""
        scenario_id = scenario_id.strip().lower()
        for folder in (self.root, self.demo_root):
            path = folder / f"{scenario_id}.json"
            if path.exists():
                return ScenarioRecord.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def rename(self, scenario_id: str, name: str) -> ScenarioRecord | None:
        """Give a scenario the user's own name (empty: back to the planner's title)."""
        rec = self.load(scenario_id)
        if rec is not None:
            rec.name = " ".join(name.split())[:120]
            self.save(rec)
        return rec

    def set_favorite(self, scenario_id: str, favorite: bool) -> ScenarioRecord | None:
        """Mark a scenario as a favourite, or not."""
        rec = self.load(scenario_id)
        if rec is not None:
            rec.favorite = favorite
            self.save(rec)
        return rec

    def is_example(self, scenario_id: str) -> bool:
        """True for a recorded example (shipped read-only in ``demo/runs/scenarios``)."""
        return (self.demo_root / f"{scenario_id.strip().lower()}.json").exists()

    def delete(self, scenario_id: str) -> bool:
        """Take a scenario out of the history: delete its file, or hide a recorded example.

        The steps' runs stay in the assistant's history: other answers may cite them.
        """
        rec = self.load(scenario_id)
        if rec is None:
            return False
        if self.is_example(scenario_id):
            rec.hidden = True
            self.save(rec)
        else:
            (self.root / f"{rec.scenario_id}.json").unlink(missing_ok=True)
        return True

    def recent(self, limit: int = 20, demo: bool | None = None) -> list[ScenarioRecord]:
        """Scenarios, newest first: own and examples (``demo=None``), only one kind otherwise.

        Hidden (deleted) examples are left out.
        """
        folders = {None: (self.demo_root, self.root), True: (self.demo_root,), False: (self.root,)}
        found = {}
        for folder in folders[demo]:
            for path in folder.glob("*.json") if folder.exists() else ():
                try:  # a file deleted or half-written meanwhile is skipped, not fatal
                    rec = ScenarioRecord.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                found[rec.scenario_id] = rec
        shown = [r for r in found.values() if not r.hidden]
        return sorted(shown, key=lambda r: r.created_at, reverse=True)[:limit]
