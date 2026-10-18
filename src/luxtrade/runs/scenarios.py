"""Scenario records: one JSON file per scenario, pointing to the run records of its steps.

A scenario answers a broad question with a chain of assistant runs (agents/scenario.py). Its
record keeps the plan, every step with its run ID, the combined answer and how it was checked,
so the answer can be reopened, re-verified step by step and shared. Own scenarios live in
``data/runs/scenarios/``; recorded examples in ``demo/runs/scenarios/`` (read-only fallback).
"""

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
    title: str = ""
    based_on: str = ""  # the scenario this one revises (its questions edited and run again)
    approach: str = ""
    out_of_scope: list[str] = Field(default_factory=list)
    steps: list[ScenarioStep] = Field(default_factory=list)
    headline: str = ""
    points: list[dict] = Field(default_factory=list)  # {"text": …, "steps": [n, …]}
    conclusion: str = ""
    charts: list[int] = Field(default_factory=list)  # steps whose charts support the answer
    figures: list[dict] = Field(default_factory=list)  # evidence charts and key figures (code)
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

    def recent(self, limit: int = 20, demo: bool | None = None) -> list[ScenarioRecord]:
        """Scenarios, newest first: own and examples (``demo=None``), only one kind otherwise."""
        folders = {None: (self.demo_root, self.root), True: (self.demo_root,), False: (self.root,)}
        found = {}
        for folder in folders[demo]:
            for path in folder.glob("*.json") if folder.exists() else ():
                try:  # a file deleted or half-written meanwhile is skipped, not fatal
                    rec = ScenarioRecord.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                found[rec.scenario_id] = rec
        return sorted(found.values(), key=lambda r: r.created_at, reverse=True)[:limit]
