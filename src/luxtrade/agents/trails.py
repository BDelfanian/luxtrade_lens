"""Investigation trails: the chain of real assistant runs behind each Overview finding.

One question rarely answers a concern. For each finding, ``trails.yaml`` lists the questions
we asked the assistant, in order and in one session (so follow-ups keep their context), why we
asked each one and what we took from it. ``build`` asks them again, live, through the same
``Assistant`` the app uses, and saves the run records as demo runs (``demo/runs``, one index
file per trail in ``demo/runs/trails/``): the "To know more" dialog shows them, and each
session opens in the assistant.

Each step names the numbers its answer must contain (``expect``); the build checks them in the
answer's facts and insight, so a trail that no longer supports its panel is reported, not hidden.

Run with ``python -m luxtrade.agents.trails`` (needs an LLM key; ``--only shocks`` for one,
``--check`` to re-check the stored runs without asking again).
"""

import argparse
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from luxtrade.config import DEMO_RUNS_DIR
from luxtrade.runs.store import RunRecord, RunStore, code_version, now_iso
from luxtrade.viz.format import fmt_pct

TRAILS_FILE = Path(__file__).with_name("trails.yaml")
INDEX_DIR = DEMO_RUNS_DIR / "trails"  # one file per trail: trails build in parallel


class Step(BaseModel):
    """One question in a trail: why we asked it and what its answer told us."""

    question: str
    why: str
    learnt: str
    expect: list[str] = Field(default_factory=list)  # numbers the answer must contain


class Trail(BaseModel):
    """The questions behind one finding, and how their answers combine."""

    key: str  # the finding's key (findings.Finding.key)
    goal: str
    steps: list[Step]
    synthesis: str
    beyond: str = ""  # what the assistant did not do: computed or read outside the runs


class BuiltStep(BaseModel):
    """A step as it was run: its run ID and which expected numbers were found."""

    run_id: str
    status: str
    checks: dict[str, bool] = Field(default_factory=dict)


class BuiltTrail(BaseModel):
    """A trail as it was run: one assistant session."""

    session_id: str
    built_at: str
    code_version: str
    steps: list[BuiltStep]


class TrailView(BaseModel):
    """What the app shows: the definition, the session and each step with its run record."""

    trail: Trail
    session_id: str
    built_at: str
    steps: list[tuple[Step, BuiltStep, RunRecord]]


def definitions(path: Path = TRAILS_FILE) -> dict[str, Trail]:
    """The trails by finding key, from ``trails.yaml``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {t["key"]: Trail.model_validate(t) for t in raw["trails"]}


def answer_text(rec: RunRecord) -> str:
    """The text an expected number is looked for in: the facts, the insight and the title."""
    rows = [  # ranked rows beyond the top 5 the facts name: "China: 3.0 %"
        f"{r['label']}: {fmt_pct(r['share'])}"
        for r in rec.frames.get("main", [])
        if r.get("label") and isinstance(r.get("share"), int | float)
    ]
    return " ".join([rec.title, *(f["text"] for f in rec.facts), *rec.insight, *rows])


def check(rec: RunRecord, expect: list[str]) -> dict[str, bool]:
    """Which expected numbers appear in the answer (spaces and minus signs normalised)."""

    def norm(s: str) -> str:
        return s.replace("−", "-").replace(" ", " ").replace(" ", " ")

    text = norm(answer_text(rec))
    return {e: norm(e) in text for e in expect}


def _built(key: str, folder: Path = INDEX_DIR) -> BuiltTrail | None:
    path = folder / f"{key}.json"
    if not path.exists():
        return None
    return BuiltTrail.model_validate_json(path.read_text(encoding="utf-8"))


def load(key: str, runs: RunStore) -> TrailView | None:
    """The trail behind a finding, with its stored run records; None if it was never built."""
    trail = definitions().get(key)
    built = _built(key, INDEX_DIR)
    if trail is None or built is None or len(built.steps) != len(trail.steps):
        return None
    steps = []
    for step, done in zip(trail.steps, built.steps, strict=True):
        rec = runs.load(done.run_id)
        if rec is None:
            return None
        steps.append((step, done, rec))
    return TrailView(trail=trail, session_id=built.session_id, built_at=built.built_at, steps=steps)


def _forget(built: BuiltTrail, root: Path) -> None:
    """Delete the run and session files of an earlier build of a trail."""
    for step in built.steps:
        (root / f"{step.run_id}.json").unlink(missing_ok=True)
    (root / "sessions" / f"{built.session_id}.json").unlink(missing_ok=True)


def build(only: list[str] | None = None, root: Path = DEMO_RUNS_DIR) -> dict[str, BuiltTrail]:
    """Ask every trail's questions live, one session per trail; save the runs and the index."""
    from luxtrade.agents.service import Assistant  # the LLM stack: only needed to build
    from luxtrade.runs.sessions import SessionStore

    runs = RunStore(root=root, demo_root=root)
    assistant = Assistant(runs=runs, sessions=SessionStore(runs, demo_root=root / "sessions"))
    if not assistant.online:
        raise SystemExit("No LLM configured: set OPENAI_API_KEY (or the Anthropic key).")
    folder = root / "trails"
    folder.mkdir(parents=True, exist_ok=True)
    done = {}
    for key, trail in definitions().items():
        if only and key not in only:
            continue
        if (old := _built(key, folder)) is not None:
            _forget(old, root)
        session_id, steps = None, []
        for step in trail.steps:
            rec = assistant.ask(step.question, session_id=session_id)
            session_id = rec.session_id
            steps.append(
                BuiltStep(run_id=rec.run_id, status=rec.status, checks=check(rec, step.expect))
            )
        done[key] = BuiltTrail(
            session_id=session_id or "",
            built_at=now_iso(),
            code_version=code_version(),
            steps=steps,
        )
        (folder / f"{key}.json").write_text(done[key].model_dump_json(indent=1), encoding="utf-8")
        report(key, trail, done[key])
    return done


def recheck(root: Path = DEMO_RUNS_DIR) -> None:
    """Check the stored runs against the expected numbers again, without asking anything."""
    runs, folder = RunStore(root=root, demo_root=root), root / "trails"
    for key, trail in definitions().items():
        built = _built(key, folder)
        if built is None or len(built.steps) != len(trail.steps):
            print(f"{key}: not built (or its steps changed): rebuild it")
            continue
        for step, done in zip(trail.steps, built.steps, strict=True):
            rec = runs.load(done.run_id)
            done.checks = check(rec, step.expect) if rec else {e: False for e in step.expect}
        (folder / f"{key}.json").write_text(built.model_dump_json(indent=1), encoding="utf-8")
        report(key, trail, built)


def report(key: str, trail: Trail, built: BuiltTrail) -> None:
    """One line per step: status, run ID and any expected number that was not found."""
    print(f"\n{key} · session {built.session_id}")
    for n, (step, done) in enumerate(zip(trail.steps, built.steps, strict=True), start=1):
        missing = [e for e, ok in done.checks.items() if not ok]
        flag = "ok" if done.status == "answered" and not missing else "CHECK"
        print(f"  {n}. [{flag}] {done.run_id} {done.status} · {step.question}")
        if missing:
            print(f"     not found: {missing}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="finding keys to rebuild (default: all)")
    parser.add_argument("--check", action="store_true", help="re-check stored runs, no LLM")
    args = parser.parse_args()
    recheck() if args.check else build(args.only)
