"""Scenario builder: a broad question answered by a chain of checked assistant runs.

Four parts, top to bottom: the question (or an example); the proposed chain of questions to
review (edit, drop or add questions); the run, step by step; and the result: the combined answer
with its supporting charts, every step of the chain with its own answer and trace, and how the
scenario was built (IDs, checks, LLM calls, re-verify, report). ``?scenario=ID`` opens one.
UI only: the work happens in agents/scenario.py (``ScenarioBuilder``).
"""

import json

import pandas as pd
import streamlit as st

from luxtrade.agents.llm import LLMError
from luxtrade.agents.scenario import EXAMPLES, MAX_FOLLOW_UPS, PlanResult, StepInput, to_markdown
from luxtrade.app.components import (
    ASK_PAGE,
    get_scenario_builder,
    render_chain_step,
    render_chart,
)
from luxtrade.runs.scenarios import ScenarioRecord

builder = get_scenario_builder()
ss = st.session_state
lang = ss.get("lang") or "en"
if "scenario" in st.query_params and ss.get("scn_id") != st.query_params["scenario"]:
    ss.scn_id, ss.scn_plan = st.query_params["scenario"], None

KIND = {"plan": "planned question", "own": "your question", "follow-up": "follow-up"}
EDITOR_COLUMNS = {
    "run": st.column_config.CheckboxColumn("Run", width="small", default=True),
    "question": st.column_config.TextColumn("Question", width="large", required=True),
    "why": st.column_config.TextColumn("Why this question", width="large"),
}


# --- actions: queued by buttons, run at the end of the page with live progress -----------------
def queue_plan(question: str, run_now: bool = False) -> None:
    """Callback: plan a question (and, with ``run_now``, run the chain straight away)."""
    ss.scn_q = question
    ss.scn_job = {"action": "plan", "question": question, "run_now": run_now}


def open_scenario(scenario_id: str) -> None:
    """Callback: show a stored scenario."""
    ss.scn_id, ss.scn_plan = scenario_id, None
    st.query_params["scenario"] = scenario_id


def new_scenario() -> None:
    """Callback: back to an empty question."""
    ss.scn_id = ss.scn_plan = None
    ss.scn_q = ""
    st.query_params.clear()


def steps_from_editor(plan: PlanResult, table: pd.DataFrame) -> list[StepInput]:
    """The ticked questions to run.

    Unchanged proposals keep their checked spec; edited or added questions are read by the
    assistant itself.
    """
    steps = []
    proposed = {s.question: s for s in plan.steps}
    for _, row in table.iterrows():
        question = str(row.get("question") or "").strip()
        if not row.get("run", True) or not question:
            continue
        why = str(row.get("why") or "").strip()
        if question in proposed:
            steps.append(
                StepInput(question=question, purpose=why, spec=proposed[question].spec, kind="plan")
            )
        else:
            steps.append(StepInput(question=question, purpose=why, kind="own"))
    return steps


def run_job() -> None:
    """Execute the queued plan or run with a progress line per step, then redraw the page."""
    job = ss.pop("scn_job", None)
    if not job:
        return
    with st.status("Working…", expanded=True) as status:
        try:
            if job["action"] == "plan":
                status.update(label="Proposing a chain of questions…")
                plan = builder.plan(job["question"], lang)
                ss.scn_plan, ss.scn_id = plan.model_dump(mode="json"), None
                if not job.get("run_now") or not plan.steps:
                    status.update(label="Chain proposed: review it below", state="complete")
                    st.rerun()
                job = {
                    "action": "run",
                    "steps": [
                        StepInput(question=s.question, purpose=s.purpose, spec=s.spec).model_dump(
                            mode="json"
                        )
                        for s in plan.steps
                    ],
                    "follow_ups": True,
                }
            plan = PlanResult.model_validate(ss.scn_plan)

            def step(label: str) -> None:
                status.update(label=label + "…")
                st.write(label)

            rec = builder.run(
                plan.question,
                [StepInput.model_validate(s) for s in job["steps"]],
                lang=lang,
                plan=plan,
                follow_ups=job["follow_ups"],
                on_progress=step,
            )
        except LLMError as exc:
            status.update(label=f"The language model failed: {exc}", state="error")
            return
        status.update(label=f"Done · scenario {rec.scenario_id}", state="complete")
    open_scenario(rec.scenario_id)
    st.rerun()


# --- the page ---------------------------------------------------------------------------------
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown("#### :violet[:material/route:] Scenario builder: answer a broad question")
    st.space("stretch")
    st.button("New scenario", icon=":material/add:", on_click=new_scenario, key="scn-new")
st.caption(
    "Some questions need several answers. The scenario builder proposes a chain of precise "
    "questions, the assistant answers each one from the data, follows up on what the answers "
    "reveal, and combines them into one checked answer. Every number traces back to a run."
)
st.markdown(
    ":gray-badge[1 · Your question] → :gray-badge[2 · Proposed chain, you review it] → "
    ":gray-badge[3 · The assistant answers each step] → "
    ":gray-badge[4 · Follow-ups from the answers] → :gray-badge[5 · Combined, checked answer]"
)

with st.container(border=True):
    st.text_area(
        "Your question",
        key="scn_q",
        height=80,
        placeholder="e.g. Has Luxembourg spread its risk, across the goods it sells and the "
        "countries it buys from?",
        disabled=not builder.online,
    )
    with st.container(horizontal=True):
        question = (ss.get("scn_q") or "").strip()
        st.button(
            "Propose a chain of questions",
            type="primary",
            icon=":material/account_tree:",
            disabled=not (builder.online and question),
            on_click=queue_plan,
            args=(question,),
            key="scn-plan",
            help="You review and edit the questions before they are run",
        )
        st.button(
            "Plan and run",
            icon=":material/bolt:",
            disabled=not (builder.online and question),
            on_click=queue_plan,
            args=(question, True),
            key="scn-plan-run",
            help="Run the proposed chain straight away, with follow-ups",
        )
    st.caption("Examples:")
    with st.container(horizontal=True):
        for i, example in enumerate(EXAMPLES.get(lang, EXAMPLES["en"])):
            st.button(
                example,
                key=f"scn-ex-{i}",
                type="tertiary",
                icon=":material/arrow_forward:",
                disabled=not builder.online,
                on_click=queue_plan,
                args=(example,),
            )
    if not builder.online:
        st.info(
            "Planning new scenarios needs the language model (set `OPENAI_API_KEY`). The recorded "
            "scenarios below can be opened without it."
        )


def render_plan(plan: PlanResult) -> None:
    """The proposed chain, editable: tick, edit, delete or add questions, then run."""
    with st.container(border=True):
        st.markdown(f"#### :material/account_tree: Proposed chain · {plan.title}")
        if plan.approach:
            st.markdown(plan.approach)
        if plan.out_of_scope:
            st.warning("**Not answerable with this data:** " + "; ".join(plan.out_of_scope))
        if not plan.steps:
            st.error(
                "No proposed question passed the checks. Try naming the flow, the period or the "
                "partners and products you are interested in."
            )
        st.caption(
            "Every proposed question passed the assistant's checks (known codes, data limits, "
            "SQL compiles and passes the guard). Untick a question to skip it, edit its text or "
            "add your own row: edited and added questions are read by the assistant itself."
        )
        table = st.data_editor(
            pd.DataFrame(
                {
                    "run": [True] * len(plan.steps),
                    "question": [s.question for s in plan.steps],
                    "why": [s.purpose for s in plan.steps],
                }
            ),
            column_config=EDITOR_COLUMNS,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            key=f"scn-editor-{hash(plan.question + plan.title)}",
        )
        if plan.notes:
            with st.expander(f"Questions the checks dropped ({len(plan.notes)})"):
                st.markdown("\n".join(f"- {n}" for n in plan.notes))
        follow = st.toggle(
            f"Let the assistant add follow-up questions from the answers (up to {MAX_FOLLOW_UPS})",
            value=True,
            key="scn-follow",
        )
        steps = steps_from_editor(plan, table)
        if st.button(
            f"Run the chain ({len(steps)} questions)",
            type="primary",
            icon=":material/play_arrow:",
            disabled=not steps,
            key="scn-run",
        ):
            ss.scn_job = {
                "action": "run",
                "steps": [s.model_dump(mode="json") for s in steps],
                "follow_ups": follow,
            }


def step_badges(numbers: list[int]) -> str:
    """':blue-badge[step 2] :blue-badge[step 4]'."""
    return " ".join(f":blue-badge[step {n}]" for n in numbers)


def render_result(rec: ScenarioRecord) -> None:
    """The combined answer, its charts and caveats, the chain, and how it was built."""
    runs = builder.records(rec)
    with st.container(border=True, key="scn-answer"):
        st.caption(
            f":violet[:material/route: Scenario · {rec.title}] · {len(rec.steps)} steps · "
            f"scenario `{rec.scenario_id}`"
        )
        st.markdown(f"**Question:** {rec.question}")
        st.markdown(f"### {rec.headline}")
        if rec.approach:
            st.caption(f"Approach: {rec.approach}")
        st.markdown(
            "\n".join(f"- {p['text']} {step_badges(p.get('steps', []))}" for p in rec.points)
        )
        st.markdown(rec.conclusion)
        if rec.answer_source == "template":
            st.caption(
                ":material/warning: The combined summary failed the number check twice, so each "
                "step's own checked headline is shown instead."
            )
        else:
            st.caption(
                ":material/verified: Every number above was found in the facts of the steps it "
                "cites, every country in their results, and a separate check confirmed that each "
                "claim follows from those facts. Removed claims are listed under *How this "
                "scenario was built*."
            )
    if rec.out_of_scope or rec.caveats:
        with st.container(border=True):
            if rec.out_of_scope:
                st.markdown(
                    ":material/block: **Not answerable with this data:** "
                    + "; ".join(rec.out_of_scope)
                )
            if rec.caveats:
                st.markdown("**Data limits that apply**")
                st.markdown("\n".join(f"- **{c['id']}**: {c['message']}" for c in rec.caveats))
    charts = [n for n in rec.charts if n in runs]
    if charts:
        st.markdown("#### Supporting charts")
        for col, n in zip(st.columns(len(charts)), charts, strict=True):
            with col:
                st.caption(f"**Step {n}** · {runs[n].question}")
                render_chart(runs[n], key="scn-support")
    st.markdown("#### The chain of questions")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "step": s.n,
                    "kind": KIND.get(s.kind, s.kind),
                    "question": s.question,
                    "queried": s.queried,
                    "status": s.status,
                    "run": s.run_id,
                }
                for s in rec.steps
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    for s in rec.steps:
        if s.n not in runs:
            st.warning(f"Step {s.n}: run `{s.run_id}` was not found.")
            continue
        meta = KIND.get(s.kind, s.kind)
        if s.builds_on:
            meta += ", prompted by the answer to " + ", ".join(f"step {n}" for n in s.builds_on)
        render_chain_step(
            s.n,
            runs[s.n],
            why=s.purpose,
            meta=meta,
            queried=s.queried,
            takeaway=s.note,
            takeaway_label="What it adds",
            key=f"scn-{rec.scenario_id}",
        )
    render_built(rec, runs)


def render_built(rec: ScenarioRecord, runs: dict) -> None:
    """IDs, checks, LLM calls, re-verify, the assistant session and the report."""
    with st.expander("How this scenario was built", icon=":material/fact_check:"):
        st.markdown(
            f"Scenario `{rec.scenario_id}` · assistant session `{rec.session_id}` · data vintage "
            f"{rec.vintage} · code `{rec.code_version}` · created {rec.created_at} · answer: "
            f"{'checked LLM text' if rec.answer_source == 'llm' else 'template'}"
        )
        st.markdown(
            "**Who did what.** The language model proposed the questions, the follow-ups and "
            "the wording of the answer. The assistant's code checked every question before it "
            "ran, computed every number with guarded SQL, and checked the answer against the "
            "steps' facts."
        )
        if rec.notes:
            st.markdown("**Checks, in order**")
            st.markdown("\n".join(f"- {n}" for n in rec.notes))
        if rec.llm_usage:
            st.markdown("**Language model calls of the scenario** (each step's run lists its own)")
            st.dataframe(pd.DataFrame(rec.llm_usage), hide_index=True, width="stretch")
        with st.container(horizontal=True):
            if st.button("Re-verify every step", icon=":material/replay:", key="scn-verify"):
                ss.scn_verified = {rec.scenario_id: builder.verify(rec)}
            if st.button(
                "Continue in the assistant",
                icon=":material/forum:",
                key="scn-session",
                help="Opens the session holding the steps' runs: ask your own follow-up",
            ):
                ss.session_id = rec.session_id
                st.switch_page(ASK_PAGE)
            st.download_button(
                "Download report (Markdown)",
                to_markdown(rec, runs).encode("utf-8"),
                file_name=f"luxtrade_scenario_{rec.scenario_id}.md",
                mime="text/markdown",
                icon=":material/description:",
                key="scn-md",
            )
            st.download_button(
                "Download record (JSON)",
                json.dumps(rec.model_dump(), indent=1, ensure_ascii=False).encode("utf-8"),
                file_name=f"luxtrade_scenario_{rec.scenario_id}.json",
                mime="application/json",
                icon=":material/data_object:",
                key="scn-json",
            )
        verified = ss.get("scn_verified", {}).get(rec.scenario_id)
        if verified:
            st.markdown("\n".join(f"- Step {n}: {msg}" for n, msg in verified.items()))


shown = builder.store.load(ss.scn_id) if ss.get("scn_id") else None
if ss.get("scn_id") and shown is None:
    st.warning(f"Scenario `{ss.scn_id}` was not found.")
if shown is not None:
    render_result(shown)
elif ss.get("scn_plan"):
    render_plan(PlanResult.model_validate(ss.scn_plan))

with st.expander("Previous scenarios", icon=":material/history:", expanded=shown is None):
    previous = builder.store.recent(limit=30)
    examples = {r.scenario_id for r in builder.store.recent(limit=100, demo=True)}
    for r in previous:
        tag = ":violet-badge[example]" if r.scenario_id in examples else ""
        st.button(
            f"{r.title or r.question[:60]} :gray[· {len(r.steps)} steps · {r.created_at[:10]} · "
            f"{r.scenario_id}] {tag}",
            key=f"scn-open-{r.scenario_id}",
            help=r.question,
            type="tertiary",
            icon=":material/route:",
            disabled=r.scenario_id == ss.get("scn_id"),
            on_click=open_scenario,
            args=(r.scenario_id,),
        )
    if not previous:
        st.caption("No scenarios yet.")

run_job()
