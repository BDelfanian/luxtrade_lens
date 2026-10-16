"""Assistant service: run the graph for a question or a spec and save the run record.

The app, the evaluator and the tests all go through ``Assistant``.
"""

from collections.abc import Callable
from pathlib import Path

from luxtrade.agents.context import build_context
from luxtrade.agents.graph import Deps, RunState, build_graph
from luxtrade.agents.llm import StructuredLLM, default_llm
from luxtrade.agents.overview import Overview, build_overview
from luxtrade.agents.spec import QuerySpec
from luxtrade.config import DATASET_ID, RAW_DIR
from luxtrade.runs.sessions import SessionStore, new_session_id
from luxtrade.runs.store import (
    RunRecord,
    RunStore,
    code_version,
    frame_records,
    make_run_id,
    now_iso,
    result_hash,
)
from luxtrade.semantic.layer import QueryError, SemanticLayer
from luxtrade.semantic.lookup import EntityIndex

STEP_LABELS = {
    "interpret": "Understanding the question",
    "guard_pre": "Checking data limits",
    "query": "Querying the data",
    "guard_post": "Checking confidential and undisclosed shares",
    "analyse": "Analysing and choosing the view",
    "insight": "Writing the insight",
    "optimise": "Suggesting answerable questions",
}
_DEFAULT = object()


class Assistant:
    """LuxTrade Lens assistant: questions, follow-ups, presets, Refine, optimiser, re-verify."""

    def __init__(
        self,
        sem: SemanticLayer | None = None,
        llm: StructuredLLM | None | object = _DEFAULT,
        runs: RunStore | None = None,
        sessions: SessionStore | None = None,
    ) -> None:
        self.sem = sem or SemanticLayer()
        self.index = EntityIndex(self.sem)
        self.llm = default_llm() if llm is _DEFAULT else llm
        self.runs = runs or RunStore()
        self.sessions = sessions or SessionStore(self.runs)
        self.graph = build_graph(Deps(llm=self.llm, sem=self.sem, index=self.index))

    @property
    def online(self) -> bool:
        """True when free questions can be interpreted (an LLM is configured)."""
        return self.llm is not None

    def ask(
        self,
        question: str,
        session_id: str | None = None,
        fresh: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> RunRecord:
        """Answer a free question (or follow-up) in a session; ``fresh`` ignores earlier turns."""
        return self._run(
            {"question": question.strip(), "origin": "ask"}, session_id, on_step, fresh=fresh
        )

    def run_spec(
        self,
        spec: QuerySpec,
        *,
        question: str,
        origin: str,
        session_id: str | None = None,
        parent_run_id: str | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> RunRecord:
        """Answer from a spec (preset, Refine, suggestion, projection) without interpretation."""
        state = {"question": question, "origin": origin, "spec": spec}
        return self._run(state, session_id, on_step, parent_run_id=parent_run_id)

    def suggest(
        self,
        question: str,
        session_id: str | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> RunRecord:
        """On-demand optimiser: three validated rewrites before running the question."""
        return self._run(
            {"question": question.strip(), "origin": "ask", "force_optimise": True},
            session_id,
            on_step,
        )

    def _run(
        self,
        initial: dict,
        session_id: str | None,
        on_step: Callable[[str], None] | None,
        parent_run_id: str | None = None,
        fresh: bool = False,
    ) -> RunRecord:
        session_id = session_id or new_session_id()
        context = build_context(session_id, [] if fresh else self.sessions.records(session_id))
        turn = self.sessions.next_turn(session_id)
        state: RunState = {
            "session_id": session_id,
            "turn": turn,
            "context": context,
            "retries": {},
            "trace": [],
            "limitations": [],
            **initial,
        }
        usage_start = len(self.llm.usage) if self.llm is not None else 0
        final: dict = dict(state)
        for mode, chunk in self.graph.stream(state, stream_mode=["updates", "values"]):
            if mode == "updates" and on_step:
                for node in chunk:
                    on_step(STEP_LABELS.get(node, node))
            elif mode == "values":
                final = chunk
        usage = self.llm.usage[usage_start:] if self.llm is not None else []
        record = self._record(final, usage, parent_run_id)
        self.runs.save(record)
        self.sessions.append(record)
        return record

    def _record(self, s: dict, usage: list, parent_run_id: str | None) -> RunRecord:
        cov = self.sem.coverage
        spec = s.get("spec")
        interp = s.get("interpretation")
        analysis = s.get("analysis")
        sheet = s.get("sheet")
        spec_dump = spec.model_dump(mode="json") if spec else None
        origin = s.get("origin", "ask")
        if origin == "ask" and interp and interp.followup_of:
            origin = "followup"
        run_id = make_run_id(
            session_id=s["session_id"],
            turn=s["turn"],
            question=s.get("question", ""),
            spec=spec_dump,
            sql=s.get("sql"),
            vintage=cov.vintage,
        )
        frames = {}
        if analysis is not None:
            frames["main"] = frame_records(analysis.main)
            frames.update({k: frame_records(v) for k, v in analysis.extra.items()})
        manifest = RAW_DIR / "manifest.json"
        methods = list(analysis.methods) if analysis else []
        if s.get("sql"):
            methods.insert(
                0,
                "LLM-written SQL, checked by the SQL guard"
                if s.get("custom_sql")
                else "SQL compiled from the QuerySpec template, checked by the SQL guard",
            )
        return RunRecord(
            run_id=run_id,
            session_id=s["session_id"],
            turn=s["turn"],
            created_at=now_iso(),
            origin=origin,
            status=s.get("status", "error"),
            question=s.get("question", ""),
            language=spec.language if spec else (interp.spec.language if interp else "en"),
            followup_of=interp.followup_of if interp else None,
            inherited=interp.inherited if interp else [],
            parent_run_id=parent_run_id,
            interpretation=interp.model_dump(mode="json") if interp else None,
            spec=spec_dump,
            assumptions=spec.assumptions if spec else [],
            limitations=[lim.model_dump() for lim in s.get("limitations", [])],
            suggestions=[x.model_dump(mode="json") for x in s.get("suggestions", [])],
            missing_hint=s.get("missing_hint", ""),
            sql=s.get("sql"),
            support_sql=[s["total_sql"]] if s.get("total_sql") else [],
            custom_sql=bool(s.get("custom_sql")),
            result_hash=result_hash(s.get("result")),
            row_count=0 if s.get("result") is None else len(s["result"]),
            view_kind=s.get("view_kind", "table"),
            title=sheet.title if sheet else "",
            frames=frames,
            entities=analysis.entities if analysis else {},
            insight=s.get("insight", []),
            insight_source=s.get("insight_source", ""),
            facts=[f.model_dump() for f in sheet.facts] if sheet else [],
            methods=methods,
            provenance={
                "dataset": DATASET_ID,
                "source": cov.source,
                "extraction_date": cov.extraction_date,
                "is_placeholder": cov.is_placeholder,
                "vintage": cov.vintage,
                "first_period": str(cov.first_period),
                "latest_complete_period": str(cov.latest_complete_period),
                "manifest": str(manifest.relative_to(manifest.parents[2]))
                if manifest.exists()
                else "none (placeholder data)",
                "database": Path(self.sem.db_path).name,
            },
            trace=[t.model_dump() for t in s.get("trace", [])],
            llm_usage=[u.__dict__ for u in usage],
            code_version=code_version(),
            error=s.get("error"),
        )

    def overview(self, lang: str = "en") -> Overview:
        """The landing page's five business questions, answered without the LLM."""
        return build_overview(self.sem, lang)

    def verify(self, record: RunRecord) -> str:
        """Re-execute the stored SQL and compare result hashes."""
        if not record.sql:
            return "nothing to verify (no query was run)"
        try:
            df = self.sem.query(record.sql)
        except QueryError as exc:
            return f"⚠️ the query no longer runs: {exc}"
        if result_hash(df) == record.result_hash:
            return "✅ reproduces exactly (same result hash)"
        return "⚠️ the data has changed since this answer (result hash differs, e.g. a new vintage)"
