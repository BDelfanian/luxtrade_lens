"""Answer card and its parts (SOLUTION_DESIGN §8). UI only: renders run records, queues actions."""

import json

import pandas as pd
import streamlit as st

from luxtrade.agents.overview import Overview
from luxtrade.agents.scenario import ScenarioBuilder
from luxtrade.agents.service import Assistant
from luxtrade.agents.spec import QuerySpec
from luxtrade.config import ATTRIBUTION, SERIES_FIRST_YEAR
from luxtrade.runs.store import RunRecord
from luxtrade.viz.charts import build_figures
from luxtrade.viz.format import flow_label, fmt_eur

ORIGIN_LABEL = {
    "ask": "question",
    "followup": "follow-up",
    "optimiser": "optimised question",
    "refine": "refined",
    "preset": "preset",
    "projection": "projection",
    "overview": "from the overview",
    "scenario": "scenario step",
}
ASK_PAGE = "app_pages/ask.py"  # relative to the entry point, Home.py

# The team and the status of the app, shown under every page and on "How it works"
CONTRIBUTORS = (
    ("Mina Naseh", "PwC"),
    ("Behrouz Delfanian", "ArcelorMittal"),
    ("Kasra Eskandarizanjani", "Amfie"),
)
POC_NOTE = (
    "**Proof of concept.** LuxTrade Lens was built with vibe coding (AI-assisted "
    "development) for the STATEC Hackathon 2026 by *The Outliers*. It is not an official "
    "STATEC or Eurostat product."
)


# The LuxTrade Lens logo: the top bar of every page and the slides' header share it
LOGO_TEXT = "LuxTrade <span>Lens</span>"


def brand_css() -> str:
    """The logo's typeface and colours (navy on a light theme, the theme's text on a dark one).

    One brand for the app's top bar and the presentation slides.
    """
    ink = "inherit" if st.context.theme.type == "dark" else "#13213C"
    font = "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,800"
    return f"""<style>
@import url("{font}&display=swap");
.lt-head {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding-bottom: 0.9rem; border-bottom: 1px solid rgba(19,33,60,.14); }}
.lt-logo {{ font-family: "Bricolage Grotesque", "Arial Black", sans-serif; font-weight: 800;
  font-size: 2.1rem; line-height: 1; letter-spacing: -0.035em; color: {ink}; }}
.lt-logo.lt-big {{ font-size: 6rem; margin-bottom: 1rem; }}
.lt-logo.lt-app {{ font-size: 2.9rem; padding: 0.15rem 0 0.35rem; }}
.lt-logo span {{ color: #0B7DB8; }}
.lt-event {{ background: #C62F35; color: #FFFFFF; font-size: 0.95rem; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase; padding: 0.4rem 0.95rem;
  border-radius: 999px; white-space: nowrap; }}
.lt-foot {{ display: flex; justify-content: space-between; gap: 1rem; padding-top: 0.7rem;
  border-top: 1px solid rgba(19,33,60,.14); font-size: 1rem; opacity: 0.7; }}
</style>"""


@st.cache_resource(show_spinner="Loading the data…")
def get_assistant() -> Assistant:
    """One assistant per server process (read-only data, stateless graph)."""
    return Assistant()


@st.cache_resource(show_spinner=False)
def get_scenario_builder() -> ScenarioBuilder:
    """The scenario builder on the shared assistant."""
    return ScenarioBuilder(get_assistant())


@st.cache_data(show_spinner="Building the overview…", max_entries=12)
def load_overview(lang: str, vintage: str) -> Overview:
    """Overview per language and data vintage (deterministic, so safe to cache)."""
    return get_assistant().overview(lang)


def queue(action: str, **kwargs: object) -> None:
    """Queue an action for the main loop (runs after the thread is drawn, then reruns)."""
    st.session_state["pending"] = {"action": action, **kwargs}


def _spec(rec: RunRecord) -> QuerySpec | None:
    return QuerySpec.model_validate(rec.spec) if rec.spec else None


def render_suggestions(rec: RunRecord) -> None:
    """Three validated rewrites as buttons, plus 'ask more specifically'."""
    if rec.status == "blocked":
        st.error("This question can't be answered with this data:")
        for lim in rec.limitations:
            if lim["severity"] == "block":
                st.markdown(f"- **{lim['id']}** — {lim['message']}")
    elif rec.status == "no_data":
        st.info("No trade is recorded for this selection.")
    else:
        st.info("This question can't be answered precisely as written. Pick a version that can:")
    # one row per suggestion so each full question is readable
    for i, s in enumerate(rec.suggestions):
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(
                s["question"],
                key=f"sug-{rec.run_id}-{i}",
                help=s["note"],
                icon=":material/arrow_forward:",
                width="content",
            ):
                queue(
                    "spec",
                    spec=s["spec"],
                    question=s["question"],
                    origin="optimiser",
                    parent=rec.run_id,
                )
            st.caption(s["note"])
    with st.form(key=f"specific-{rec.run_id}", border=False):
        text = st.text_input("Ask more specifically", value=rec.question, help=rec.missing_hint)
        st.caption(rec.missing_hint)
        if st.form_submit_button("Ask"):
            queue("ask", question=text)


def render_chart(rec: RunRecord, key: str = "fig") -> None:
    """The data product chosen for this answer (``key`` keeps two drawings of a run apart)."""
    main = rec.frame("main")
    spec = _spec(rec)
    lang = rec.language
    if rec.view_kind == "kpi":
        cols = st.columns(max(1, main["flow"].nunique()))
        for col, (flow, g) in zip(cols, main.groupby("flow"), strict=False):
            g = g.sort_values("period")
            cur = g.iloc[-1]["value"]
            delta = None
            if len(g) > 1 and g.iloc[-2]["value"]:
                delta = (
                    f"{100 * (cur / g.iloc[-2]['value'] - 1):+.1f} % vs {int(g.iloc[-2]['period'])}"
                )
            col.metric(
                f"{flow_label(flow, lang)} {int(g.iloc[-1]['period'])}", fmt_eur(cur, lang), delta
            )
        return
    if rec.view_kind == "pivot":
        render_pivot(rec, key=f"{key}-chart")
        return
    if rec.view_kind == "table":
        st.dataframe(main, width="stretch", hide_index=True)
        return
    figs = build_figures(
        rec.view_kind,
        main,
        rec.title or rec.question,
        lang=lang,
        measure=spec.measure if spec else "value_eur",
        monthly=bool(spec and spec.freq == "M"),
    )
    for i, fig in enumerate(figs):
        st.plotly_chart(
            fig, width="stretch", key=f"{key}-{rec.run_id}-{i}", config={"displaylogo": False}
        )


def render_pivot(rec: RunRecord, key: str = "pivot") -> None:
    """User-selected pivot over the answer's frame."""
    main = rec.frame("main")
    dims = [c for c in ("label", "period", "flow", "reporter", "kind") if c in main.columns]
    values = [c for c in ("value", "share", "index", "observed", "adjusted") if c in main.columns]
    if len(dims) < 2 or not values:
        st.caption("A pivot needs two dimensions; see the Table tab.")
        return
    c1, c2, c3 = st.columns(3)
    rows = c1.selectbox("Rows", dims, index=0, key=f"pr-{key}-{rec.run_id}")
    cols = c2.selectbox("Columns", [d for d in dims if d != rows], key=f"pc-{key}-{rec.run_id}")
    val = c3.selectbox("Value", values, key=f"pv-{key}-{rec.run_id}")
    table = main.pivot_table(index=rows, columns=cols, values=val, aggfunc="sum")
    fmt = "{:,.1f}" if val in ("share", "index") else "{:,.0f}"
    st.dataframe(table.style.format(fmt, na_rep="–"), width="stretch")


def render_trace(rec: RunRecord) -> None:
    """'How we got this': the full chain from question to data provenance (SOLUTION_DESIGN §6)."""
    st.markdown(
        f"**Question** ({rec.language}): {rec.question}  \n"
        f"Session `{rec.session_id}` · turn {rec.turn} · "
        f"origin: {ORIGIN_LABEL.get(rec.origin, rec.origin)}"
        + (f" · refined from `{rec.parent_run_id}`" if rec.parent_run_id else "")
    )
    if rec.followup_of:
        st.markdown(
            f"**Context:** follow-up of `{rec.followup_of}`; inherited: "
            f"{', '.join(rec.inherited) or '—'}"
        )
    elif rec.origin in ("ask", "followup"):
        st.markdown("**Context:** new topic (nothing inherited)")
    if rec.spec:
        st.markdown("**Interpretation** (QuerySpec, after defaults):")
        st.json({k: v for k, v in rec.spec.items() if v not in (None, [], "auto")}, expanded=False)
    if rec.interpretation and (
        rec.interpretation.get("ambiguities") or rec.interpretation.get("unresolved")
    ):
        st.markdown(
            f"Ambiguities: {rec.interpretation.get('ambiguities')} · "
            f"unresolved: {rec.interpretation.get('unresolved')}"
        )
    if rec.suggestions:
        st.markdown(
            "**Optimiser suggestions** (validated): "
            + " · ".join(f"“{s['question']}”" for s in rec.suggestions)
        )
    if rec.limitations:
        st.markdown(
            "**Limitations checked:** "
            + ", ".join(
                f"{lim['id']} ({lim['severity']}"
                + (f", {lim['value']:.1f} %" if lim.get("value") else "")
                + ")"
                for lim in rec.limitations
            )
        )
    if rec.sql:
        st.markdown(
            f"**SQL executed** · {rec.row_count} rows · "
            f"result hash `{(rec.result_hash or '')[:16]}…`"
        )
        st.code(rec.sql, language="sql")
    for sql in rec.support_sql:
        st.markdown("**Total for the shares** (the same scope without the shared filter):")
        st.code(sql, language="sql")
    if rec.methods:
        st.markdown("**Methods:**\n" + "\n".join(f"- {m}" for m in rec.methods))
    p = rec.provenance
    st.markdown(
        f"**Data provenance:** {p.get('dataset')} · {p.get('source')} · extracted "
        f"{p.get('extraction_date')} · latest complete month "
        f"{p.get('latest_complete_period', '')[:7]} "
        f"· manifest: {p.get('manifest')}"
    )
    if rec.trace:
        st.markdown("**Agent trace:**")
        st.dataframe(pd.DataFrame(rec.trace), hide_index=True, width="stretch")
    if rec.llm_usage:
        st.markdown("**LLM calls:**")
        st.dataframe(pd.DataFrame(rec.llm_usage), hide_index=True, width="stretch")
    st.caption(f"Code version `{rec.code_version}` · run `{rec.run_id}` · created {rec.created_at}")
    with st.expander("Raw run record (JSON)"):
        st.code(
            json.dumps(
                rec.model_dump(exclude={"frames"}), indent=1, ensure_ascii=False, default=str
            )[:20000],
            language="json",
        )


def render_chain_step(
    n: int,
    rec: RunRecord,
    *,
    why: str,
    meta: str = "",
    queried: str = "",
    takeaway: str = "",
    takeaway_label: str = "What we took from it",
    badges: list[str] = (),
    key: str = "chain",
) -> None:
    """One question of a chain (an investigation trail or a scenario step).

    Shows why it was asked, the assistant's stored answer with its chart and trace, and what it
    adds. ``meta`` follows the step number (e.g. "follow-up of step 2"); ``badges`` are numbers that
    were found in the answer; ``key`` keeps the step's charts apart from other drawings.
    """
    with st.container(border=True):
        st.caption(f"**Step {n}** · run `{rec.run_id}`" + (f" · {meta}" if meta else ""))
        st.markdown(f"**:material/person: Asked:** *{rec.question}*")
        if why:
            st.caption(f"Why: {why}")
        if queried:
            st.caption(f":material/database: Queried: {queried}")
        answer, chart, how = st.tabs(["Answer", "Chart", "How the assistant got this"])
        with answer:
            if rec.status == "answered":
                st.markdown(" ".join(rec.insight))
                if rec.facts:
                    st.markdown("\n".join(f"- {x['text']}" for x in rec.facts[:6]))
            elif rec.status == "error":
                st.error(rec.error or "Something went wrong.")
            else:
                st.markdown(
                    "The assistant did not answer this one as written. It explained why and "
                    "offered answerable versions:"
                )
                st.markdown("\n".join(f"- *{s['question']}*" for s in rec.suggestions))
        with chart:
            if rec.status == "answered":
                render_chart(rec, key=f"{key}-{n}")
            else:
                st.caption("No chart: no query was run.")
        with how:
            render_trace(rec)
        if takeaway:
            st.markdown(f"**:material/lightbulb: {takeaway_label}:** {takeaway}")
        if badges:
            ticks = " ".join(f":green-badge[:material/check: {b}]" for b in badges)
            st.markdown(f"In the answer: {ticks}")


def refined_question(spec: QuerySpec) -> str:
    """What a refined run asks, from its spec alone, e.g. 'Refined: trade balance, 2014–2018'.

    The original wording is left out: its year or flow may no longer apply, and the paragraph
    is written from this question.
    """
    period = (
        spec.period_start
        if spec.period_start == spec.period_end
        else f"{spec.period_start}–{spec.period_end}"
    )
    parts = [flow_label(spec.flow or "both", "en")]
    if spec.breakdown not in (None, "none"):
        parts[0] += f" by {spec.breakdown.replace('_', ' ')}"
    parts.append(period)
    if spec.top_n and spec.breakdown not in (None, "none"):
        parts.append(f"top {spec.top_n}")
    return "Refined: " + ", ".join(parts)


def render_refine(rec: RunRecord, latest_year: int) -> None:
    """Refine controls generated from the spec: re-run without the LLM (SOLUTION_DESIGN §5.6)."""
    spec = _spec(rec)
    if spec is None or rec.custom_sql:
        return
    with st.expander("Refine"), st.form(key=f"refine-{rec.run_id}", border=False):
        c1, c2, c3 = st.columns([2, 2, 1])
        start = int((spec.period_start or str(SERIES_FIRST_YEAR))[:4])
        end = int((spec.period_end or str(latest_year))[:4])
        years = c1.slider(
            "Period",
            SERIES_FIRST_YEAR,
            latest_year,
            (min(start, end), min(end, latest_year)),
            key=f"rf-y-{rec.run_id}",
        )
        flows = ["export", "import", "both", "balance"]
        flow = c2.radio(
            "Flow",
            flows,
            index=flows.index(spec.flow or "both"),
            horizontal=True,
            format_func=lambda f: flow_label(f, "en"),
            key=f"rf-f-{rec.run_id}",
        )
        top_n = c3.number_input("Top N", 3, 30, spec.top_n or 10, key=f"rf-n-{rec.run_id}")
        views = [
            "auto",
            "table",
            "bar",
            "line",
            "area",
            "stacked",
            "heatmap",
            "map",
            "treemap",
            "pivot",
        ]
        view = st.selectbox(
            "View",
            views,
            index=views.index(spec.view) if spec.view in views else 0,
            key=f"rf-v-{rec.run_id}",
        )
        if st.form_submit_button("Apply (no LLM needed)"):
            new = spec.model_copy(
                update={
                    "period_start": str(years[0]),
                    "period_end": str(years[1]),
                    "flow": flow,
                    "top_n": int(top_n),
                    "view": view,
                    "freq": None if spec.intent == "time_series" else spec.freq,
                    "assumptions": [],
                }
            )
            queue(
                "spec",
                spec=new.model_dump(),
                question=refined_question(new),
                origin="refine",
                parent=rec.run_id,
            )


def render_answer(rec: RunRecord, latest_year: int) -> None:
    """The full answer card for one run record."""
    if rec.status == "error":
        st.error(rec.error or "Something went wrong.")
        return
    meta = f"run `{rec.run_id}` · {ORIGIN_LABEL.get(rec.origin, rec.origin)}"
    if rec.assumptions:
        meta += " · Assumed: " + "; ".join(rec.assumptions)
    st.caption(meta)
    if rec.followup_of and rec.inherited:
        c1, c2 = st.columns([5, 1])
        c1.caption(f"↪ Kept from your previous question: {', '.join(rec.inherited)}")
        if c2.button("Start fresh", key=f"fresh-{rec.run_id}"):
            queue("ask", question=rec.question, fresh=True)
    if rec.status in ("suggestions", "blocked", "no_data"):
        render_suggestions(rec)
        return

    if rec.insight:
        st.markdown(" ".join(rec.insight))
        if rec.insight_source == "template":
            st.caption(
                "Insight written from a fixed template "
                "(no LLM, or the LLM text failed the number check)."
            )
    warns = [lim for lim in rec.limitations if lim["severity"] == "warn"]
    if warns:
        with st.container(border=True):
            st.markdown("**Data limits that apply**")
            for lim in warns:
                st.markdown(f"- **{lim['id']}** — {lim['message']}")

    tabs = st.tabs(["Chart", "Table", "Pivot", "How we got this"])
    with tabs[0]:
        render_chart(rec)
        st.caption(
            ATTRIBUTION.format(date=rec.provenance.get("extraction_date", "?"))
            + (
                " **PLACEHOLDER DATA — not real figures.**"
                if rec.provenance.get("is_placeholder")
                else ""
            )
        )
    with tabs[1]:
        main = rec.frame("main")
        st.dataframe(main, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV",
            main.to_csv(index=False).encode("utf-8"),
            file_name=f"luxtrade_{rec.run_id}.csv",
            mime="text/csv",
            key=f"csv-{rec.run_id}",
        )
    with tabs[2]:
        render_pivot(rec)
    with tabs[3]:
        render_trace(rec)

    render_refine(rec, latest_year)
    spec = _spec(rec)
    projectable = spec and spec.intent in ("time_series", "seasonality") and not rec.custom_sql
    if projectable and st.button("Show projection", key=f"proj-{rec.run_id}"):
        new = spec.model_copy(
            update={
                "intent": "forecast",
                "freq": "M",
                "breakdown": "none",
                "period_start": None,
                "period_end": None,
                "assumptions": [],
                "flow": spec.flow if spec.flow in ("export", "import") else "export",
            }
        )
        queue(
            "spec",
            spec=new.model_dump(),
            question=f"{rec.question} — projection",
            origin="projection",
            parent=rec.run_id,
        )
