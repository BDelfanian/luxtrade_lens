"""The agent graph (LangGraph): nodes, supervisor edges and per-node tracing (SOLUTION_DESIGN §3).

START ─▶ interpret ─▶ guard_pre ─▶ query ─▶ guard_post ─▶ analyse ─▶ insight ─▶ END
            │  ▲          │          │  ▲
            └──┘ retry    │          └──┘ retry (LLM SQL)
            ▼             ▼          ▼
         optimise ◀───────┴──────────┘  (vague / blocked / failed / empty) ─▶ END
"""

import json
import logging
import operator
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, TypedDict

import pandas as pd
from langgraph.graph import START, StateGraph

from luxtrade.agents import guard, supervisor
from luxtrade.agents.analyse import Analysis, analyse
from luxtrade.agents.compile_sql import SpecError, compile_spec
from luxtrade.agents.context import SessionContext
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.facts import Fact, FactSheet, build_fact_sheet
from luxtrade.agents.insight import write_insight
from luxtrade.agents.interpret import coverage_text, interpret, prompt
from luxtrade.agents.llm import LLMError, StructuredLLM
from luxtrade.agents.optimise import optimise
from luxtrade.agents.spec import (
    CustomSQL,
    Interpretation,
    Limitation,
    QuerySpec,
    Suggestion,
    TraceEvent,
)
from luxtrade.agents.sql_guard import SQLRejectedError, check_sql
from luxtrade.semantic.catalog import catalog_text
from luxtrade.semantic.layer import QueryError, SemanticLayer
from luxtrade.semantic.lookup import EntityIndex
from luxtrade.viz.selector import choose_view

logger = logging.getLogger(__name__)


class RunState(TypedDict, total=False):
    """Shared state of one run through the graph."""

    question: str
    origin: str
    session_id: str
    turn: int
    force_optimise: bool
    context: SessionContext
    interpretation: Interpretation | None
    spec: QuerySpec | None
    limitations: list[Limitation]
    sql: str | None
    stats_sql: str | None
    custom_sql: bool
    custom_explanation: str
    sql_error: str | None
    result: pd.DataFrame | None
    stats: guard.ScopeStats | None
    analysis: Analysis | None
    view_kind: str
    sheet: FactSheet | None
    insight: list[str]
    insight_source: str
    suggestions: list[Suggestion]
    missing_hint: str
    status: str
    error: str | None
    retries: dict[str, int]
    trace: Annotated[list[TraceEvent], operator.add]


@dataclass
class Deps:
    """What the nodes need: the LLM (None = offline), the semantic layer and the entity index."""

    llm: StructuredLLM | None
    sem: SemanticLayer
    index: EntityIndex


def _traced(name: str, fn: Callable[[RunState], dict]) -> Callable[[RunState], dict]:
    def node(state: RunState) -> dict:
        t0 = time.perf_counter()
        try:
            update = fn(state)
        except Exception as exc:  # a node failure becomes a friendly error, never a stack trace
            logger.exception("node %s failed", name)
            update = {"status": "error", "error": f"{name}: {exc}", "_outcome": "error"}
        outcome = update.pop("_outcome", "ok")
        detail = update.pop("_detail", "")
        ms = int(1000 * (time.perf_counter() - t0))
        logger.info("run %s | node %s | %d ms | %s", state.get("session_id"), name, ms, outcome)
        update["trace"] = [TraceEvent(node=name, ms=ms, outcome=outcome, detail=detail)]
        return update

    return node


def _bump(state: RunState, node: str) -> dict[str, int]:
    retries = dict(state.get("retries", {}))
    retries[node] = retries.get(node, 0) + 1
    return retries


def build_graph(deps: Deps):  # noqa: ANN201 - compiled LangGraph type
    """Compile the agent graph with its dependencies bound."""
    sem, llm, index = deps.sem, deps.llm, deps.index

    def interpret_node(state: RunState) -> dict:
        retries = _bump(state, "interpret")
        if llm is None:
            return {
                "status": "error",
                "retries": retries,
                "_outcome": "error",
                "error": "Free questions need an LLM (ANTHROPIC_API_KEY). "
                "Presets and stored runs work offline.",
            }
        previous = state.get("interpretation")
        wide = previous is not None
        extra = previous.unresolved if previous else []
        try:
            interp = interpret(
                state["question"],
                llm=llm,
                sem=sem,
                index=index,
                context=state["context"],
                wide=wide,
                extra_terms=extra,
            )
        except LLMError as exc:
            return {"status": "error", "error": str(exc), "retries": retries, "_outcome": "error"}
        spec = interp.spec
        if interp.view_only:
            prev = state["context"].get(interp.followup_of)
            if prev and prev.spec:
                spec = prev.spec.model_copy(
                    update={
                        "view": interp.spec.view,
                        "language": interp.spec.language,
                        "assumptions": [],
                    }
                )
        detail = f"intent={spec.intent} breakdown={spec.breakdown}"
        if interp.followup_of:
            inherited = ", ".join(interp.inherited) or "—"
            detail += f" · follow-up of {interp.followup_of} (inherited: {inherited})"
        if interp.unresolved:
            detail += f" · unresolved: {interp.unresolved}"
        return {
            "interpretation": interp,
            "spec": None if interp.unresolved else spec,
            "retries": retries,
            "_outcome": "retry" if wide else "ok",
            "_detail": detail,
        }

    def guard_pre_node(state: RunState) -> dict:
        interp = state.get("interpretation")
        spec = state.get("spec") or (interp.spec if interp else None)
        resolved = apply_defaults(spec, sem.coverage)
        lims = guard.merge(
            guard.check_question(
                state.get("question", "") if state.get("origin") == "ask" else "",
                interp.out_of_scope if interp else [],
            ),
            guard.check_spec(resolved, sem.coverage),
        )
        blocked = guard.is_blocked(lims)
        update = {
            "spec": resolved,
            "limitations": lims,
            "_detail": ", ".join(f"{lim.id}:{lim.severity}" for lim in lims) or "none",
        }
        if blocked:
            update.update(status="blocked", _outcome="blocked")
        return update

    def query_node(state: RunState) -> dict:
        spec = state["spec"]
        interp = state.get("interpretation")
        custom = bool(interp and interp.needs_custom_sql)
        retries = _bump(state, "query")
        explanation = ""
        sql: str | None = None
        try:
            if custom:
                if llm is None:
                    raise LLMError("custom SQL needs the LLM")
                user = (
                    f"QUESTION: {state['question']}\n\n{coverage_text(sem)}"
                    f"\n\nCATALOG:\n{catalog_text()}"
                )
                if state.get("sql_error"):
                    user += (
                        f"\n\nERROR from your previous SQL:\n{state['sql_error']}"
                        f"\n{state.get('sql')}"
                    )
                out = llm.parse(
                    step="custom_sql",
                    system=prompt("custom_sql"),
                    user=user,
                    schema=CustomSQL,
                    effort="medium",
                )
                sql, stats_sql, explanation = out.sql, None, out.explanation
                sql = check_sql(sql)
            else:
                compiled = compile_spec(spec)
                sql = check_sql(compiled.sql)
                stats_sql = check_sql(compiled.stats_sql) if compiled.stats_sql else None
            df = sem.query(sql)
            stats = None
            if stats_sql:
                row = sem.query(stats_sql).fillna(0.0).iloc[0]
                stats = guard.ScopeStats(
                    float(row["total"]), float(row["confidential"]), float(row["special"])
                )
        except (SpecError, SQLRejectedError, QueryError, LLMError) as exc:
            return {
                "sql_error": str(exc),
                "retries": retries,
                "custom_sql": custom,
                "sql": sql,
                "_outcome": "retry",
                "_detail": str(exc),
            }
        update = {
            "sql": sql,
            "stats_sql": stats_sql,
            "result": df,
            "stats": stats,
            "custom_sql": custom,
            "custom_explanation": explanation,
            "sql_error": None,
            "retries": retries,
            "_detail": f"{len(df)} rows" + (" · LLM-written SQL" if custom else ""),
        }
        if df.empty:
            update.update(status="no_data", _outcome="routed")
        return update

    def guard_post_node(state: RunState) -> dict:
        lims = guard.merge(
            state.get("limitations", []), guard.check_result(state["spec"], state.get("stats"))
        )
        return {"limitations": lims, "_detail": ", ".join(lim.id for lim in lims)}

    def analyse_node(state: RunState) -> dict:
        spec, df = state["spec"], state["result"]
        if state.get("custom_sql"):
            a = Analysis(main=df, methods=["LLM-written SQL, checked by the SQL guard"])
            kind = "line" if {"period", "value_eur"} <= set(df.columns) else "table"
            if kind == "line":
                a.main = df.rename(columns={"value_eur": "value"}).assign(
                    flow=df.get("flow", "total")
                )
            return {"analysis": a, "view_kind": kind, "_detail": kind}
        a = analyse(spec, df, sem)
        stats = state.get("stats")
        iso3 = int(a.main["iso3"].notna().sum()) if "iso3" in a.main.columns else 0
        special_pct = stats.pct(stats.special) if stats else 0.0
        kind = choose_view(spec, a.main, iso3_count=iso3, undisclosed_pct=special_pct)
        return {
            "analysis": a,
            "view_kind": kind,
            "limitations": guard.merge(state.get("limitations", []), a.flags),
            "_detail": f"view={kind}; " + "; ".join(a.methods),
        }

    def insight_node(state: RunState) -> dict:
        spec, a = state["spec"], state.get("analysis")
        interp = state.get("interpretation")
        ctx = state["context"]
        prev = ctx.get(interp.followup_of) if interp else None
        lims = state.get("limitations", [])
        if state.get("custom_sql"):
            rows = a.main.head(12).to_dict(orient="records") if a is not None else []
            sheet = FactSheet(
                language=spec.language,
                question=state["question"],
                title=state.get("custom_explanation", "")[:90],
                facts=[
                    Fact(key=f"row{i}", text=json.dumps(r, default=str, ensure_ascii=False))
                    for i, r in enumerate(rows)
                ],
                limitations=[lim.message for lim in lims],
                template=[state.get("custom_explanation", "")],
            )
        else:
            sheet = build_fact_sheet(
                spec,
                a,
                lims,
                sem,
                question=state.get("question", ""),
                previous=prev.headline if prev else "",
            )
        if interp and interp.view_only:
            return {
                "sheet": sheet,
                "insight": sheet.template,
                "insight_source": "template",
                "status": "answered",
                "_detail": "view change only: template insight",
            }
        sentences, source, notes = write_insight(sheet, llm=llm, sem=sem)
        return {
            "sheet": sheet,
            "insight": sentences,
            "insight_source": source,
            "status": "answered",
            "_outcome": "ok" if source == "llm" or llm is None else "fallback",
            "_detail": "; ".join(notes) or source,
        }

    def optimise_node(state: RunState) -> dict:
        reason = supervisor.optimiser_reason(state)
        interp = state.get("interpretation")
        spec = state.get("spec") or (interp.spec if interp else None)
        lang = spec.language if spec else "en"
        suggestions, hint, notes = optimise(
            state.get("question", ""),
            reason,
            lang=lang,
            llm=llm,
            sem=sem,
            index=index,
            context=state["context"],
        )
        status = state.get("status")
        return {
            "suggestions": suggestions,
            "missing_hint": hint,
            "status": status if status in ("blocked", "no_data") else "suggestions",
            "_outcome": "routed",
            "_detail": f"{reason} · " + "; ".join(notes),
        }

    g = StateGraph(RunState)
    for name, fn in (
        ("interpret", interpret_node),
        ("guard_pre", guard_pre_node),
        ("query", query_node),
        ("guard_post", guard_post_node),
        ("analyse", analyse_node),
        ("insight", insight_node),
        ("optimise", optimise_node),
    ):
        g.add_node(name, _traced(name, fn))
    end = supervisor.END
    g.add_conditional_edges(START, supervisor.entry, ["interpret", "guard_pre", "optimise"])
    g.add_conditional_edges(
        "interpret", supervisor.after_interpret, ["interpret", "optimise", "guard_pre", end]
    )
    g.add_conditional_edges("guard_pre", supervisor.after_guard_pre, ["optimise", "query", end])
    g.add_conditional_edges(
        "query", supervisor.after_query, ["query", "optimise", "guard_post", end]
    )
    g.add_edge("guard_post", "analyse")
    g.add_edge("analyse", "insight")
    g.add_edge("insight", end)
    g.add_edge("optimise", end)
    return g.compile()
