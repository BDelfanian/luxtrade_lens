"""Scenario builder: a broad question answered by a chain of checked assistant runs.

Four parts, top to bottom: the question (or an example card); the proposed chain of questions
to review (tick, edit, reorder, delete or add questions; added and edited ones are checked for
answerability and fit); the run, step by step; and the result: the combined answer with its
supporting charts, every step of the chain with its own answer and trace, and how the scenario
was built (IDs, checks, LLM calls, re-verify, report). ``?scenario=ID`` opens one.
UI only: the work happens in agents/scenario.py (``ScenarioBuilder``).
"""

import json

import pandas as pd
import streamlit as st

from luxtrade.agents.llm import LLMError
from luxtrade.agents.scenario import (
    MAX_FOLLOW_UPS,
    PlanResult,
    StepCheck,
    StepInput,
    examples,
    to_markdown,
)
from luxtrade.agents.spec import QuerySpec
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
STEPS = (
    "Your question",
    "Proposed chain, you review it",
    "The assistant answers each step",
    "Follow-ups from the answers",
    "Combined, checked answer",
)
EXAMPLE_ICONS = (
    ":material/scatter_plot:",
    ":material/bolt:",
    ":material/public:",
    ":material/local_gas_station:",
)
# a row's state → (accent colour, badge)
ROW_LOOK = {
    "plan": ("#5B47D1", ":violet-badge[:material/verified: checked]"),
    "checked": ("#1BAF7A", ":green-badge[:material/check: your question · checked]"),
    "warned": ("#EDA100", ":orange-badge[:material/warning: your question · see the notes]"),
    "problem": ("#D33A36", ":red-badge[:material/block: cannot be answered as written]"),
    "unchecked": ("#EDA100", ":orange-badge[:material/edit: your question · not checked yet]"),
    "empty": ("#B5BCC8", ":gray-badge[empty]"),
}
st.html(
    """<style>
.scn-steps { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; margin: 2px 0 6px; }
.scn-chip { display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px 5px 5px;
  border-radius: 999px; background: #EEEBFB; border: 1px solid #D9D3F6; color: #2E2470;
  font-size: 0.9rem; font-weight: 500; }
.scn-chip b { width: 22px; height: 22px; border-radius: 50%; background: #5B47D1; color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 0.78rem; }
.scn-arrow { color: #8F84DE; font-weight: 700; }
[class*="st-key-scn-excard-"] { background: linear-gradient(135deg, rgba(98,80,214,.09),
  rgba(98,80,214,.03)); border-color: #D9D3F6 !important; }
[class*="st-key-scn-excard-"] button { justify-content: flex-start; }
.scn-head { display: grid; grid-template-columns: 0.55fr 5.2fr 4.2fr 0.9fr; gap: 1rem;
  background: #5B47D1; color: #fff; border-radius: 10px; padding: 9px 30px 9px 18px;
  font-weight: 600; font-size: 0.9rem; }
[class*="st-key-scn-row-"] { background: #FFFFFF; border: 1px solid #DDD8F5;
  border-left: 5px solid var(--scn-accent, #5B47D1); border-radius: 12px;
  padding: 10px 12px 6px; box-shadow: 0 1px 3px rgba(19,33,60,.07); }
[class*="st-key-scn-row-"] textarea { background: #FAF9FF; border-color: #E4E0F7;
  font-size: 0.95rem; line-height: 1.45; }
[class*="st-key-scn-row-skip-"] { opacity: 0.55; }
.scn-num { width: 30px; height: 30px; border-radius: 50%; background: #5B47D1; color: #fff;
  display: flex; align-items: center; justify-content: center; font-weight: 700;
  margin: 4px 0 6px; }
.scn-num.skip { background: #B5BCC8; font-size: 0.7rem; }
</style>"""
)


# --- the editable chain: one row per question, kept in session state -----------------------------
def _key(kind: str, rid: str) -> str:
    return f"scn-{kind}-{rid}"


def add_row(question: str = "", why: str = "", spec: dict | None = None) -> None:
    """Callback (and setup): append a row; a proposed row keeps its checked spec."""
    rid = f"r{ss.get('scn_next_row', 0)}"
    ss.scn_next_row = ss.get("scn_next_row", 0) + 1
    ss[_key("q", rid)], ss[_key("why", rid)], ss[_key("run", rid)] = question, why, True
    ss.scn_rows.append({"id": rid, "orig": question, "spec": spec, "check": None, "checked": ""})


def load_rows(plan: PlanResult) -> None:
    """Fill the editable chain from a checked plan."""
    ss.scn_rows = []
    for s in plan.steps:
        add_row(s.question, s.purpose, s.spec.model_dump(mode="json"))


def text(row: dict) -> str:
    """The row's question as typed."""
    return (ss.get(_key("q", row["id"])) or "").strip()


def ticked(row: dict) -> bool:
    """True if the row is ticked and has a question: it is a step of the chain."""
    return bool(ss.get(_key("run", row["id"]), True)) and bool(text(row))


def state(row: dict) -> str:
    """Plan · checked · warned · problem · unchecked · empty."""
    q = text(row)
    if not q:
        return "empty"
    if row["spec"] is not None and q == row["orig"]:
        return "plan"
    if row["check"] is None or row["checked"] != q:
        return "unchecked"
    check = StepCheck.model_validate(row["check"])
    if not check.ok:
        return "problem"
    return "warned" if check.warnings else "checked"


def spec_of(row: dict) -> QuerySpec | None:
    """The checked reading a row runs with: the plan's, or its own check's; None otherwise."""
    st_ = state(row)
    if st_ == "plan":
        return QuerySpec.model_validate(row["spec"])
    if st_ in ("checked", "warned") and row["check"].get("spec"):
        return QuerySpec.model_validate(row["check"]["spec"])
    return None


def chain() -> list[dict]:
    """The ticked, non-empty rows, in order: the steps that will run."""
    return [r for r in ss.scn_rows if ticked(r)]


def move_row(i: int, step: int) -> None:
    """Callback: move row ``i`` up (-1) or down (+1)."""
    j = i + step
    if 0 <= j < len(ss.scn_rows):
        ss.scn_rows[i], ss.scn_rows[j] = ss.scn_rows[j], ss.scn_rows[i]


def move_to_step(rid: str, position: int) -> None:
    """Callback: move a row to the place of the ``position``-th step of the chain."""
    rows = ss.scn_rows
    row = next(r for r in rows if r["id"] == rid)
    target = chain()[position - 1]["id"]
    rows.remove(row)
    rows.insert(next(i for i, r in enumerate(rows) if r["id"] == target) + (position > 1), row)
    row["check"] = None  # its place changed: check the fit again


def delete_row(i: int) -> None:
    """Callback: remove row ``i`` and its widget state."""
    row = ss.scn_rows.pop(i)
    for kind in ("q", "why", "run"):
        ss.pop(_key(kind, row["id"]), None)


def queue_check(rids: list[str]) -> None:
    """Callback: check added or edited rows (answerable? fits the chain?).

    The check runs inside each row's card, under a spinner, as the chain is drawn.
    """
    ss.scn_checking = list(rids)


def use_alternative(rid: str, k: int) -> None:
    """Callback: replace a failing question by the ``k``-th checked rewrite."""
    row = next(r for r in ss.scn_rows if r["id"] == rid)
    alt = row["check"]["alternatives"][k]
    ss[_key("q", rid)] = alt["question"]
    note = "a rewrite proposed and checked by the assistant"
    row["check"] = StepCheck(
        ok=True, spec=alt["spec"], queried=alt["queried"], notes=[note]
    ).model_dump(mode="json")
    row["checked"] = alt["question"]


def queue_run(force: bool = False) -> None:
    """Callback: run the chain; unchecked rows are checked first, warnings stop the run once."""
    ss.scn_job = {"action": "run", "follow_ups": ss.get("scn-follow", True), "force": force}


def check_rows(rids: list[str], status: object | None = None) -> None:
    """Check the given rows against the main question and their place in the chain."""
    plan = PlanResult.model_validate(ss.scn_plan)
    steps = chain()
    pairs = [(text(r), (ss.get(_key("why", r["id"])) or "").strip()) for r in steps]
    others = [spec_of(r) for r in steps]
    for rid in rids:
        row = next((r for r in steps if r["id"] == rid), None)
        if row is None:
            continue
        n = steps.index(row) + 1
        if status is not None:
            status.update(label=f"Checking step {n}: {text(row)}…")
        found = builder.check_step(plan.question, pairs, n, lang, others)
        row["check"], row["checked"] = found.model_dump(mode="json"), text(row)
        others[n - 1] = found.spec


def steps_to_run() -> list[StepInput]:
    """The chain as the builder runs it: checked readings run as is, the rest are interpreted."""
    out = []
    for r in chain():
        why = (ss.get(_key("why", r["id"])) or "").strip()
        kind = "plan" if state(r) == "plan" else "own"
        out.append(StepInput(question=text(r), purpose=why, spec=spec_of(r), kind=kind))
    return out


# --- actions: queued by buttons, run at the end of the page with live progress -----------------
def queue_plan(question: str, run_now: bool = False) -> None:
    """Callback: plan a question (and, with ``run_now``, run the chain straight away)."""
    ss.scn_q = question
    ss.scn_job = {"action": "plan", "question": question, "run_now": run_now}


def open_scenario(scenario_id: str) -> None:
    """Callback: show a stored scenario."""
    ss.scn_id, ss.scn_plan, ss.scn_revise = scenario_id, None, None
    st.query_params["scenario"] = scenario_id


def revise(scenario_id: str) -> None:
    """Callback: reopen a scenario's questions, follow-ups included, to edit and run again.

    Steps that ran keep their checked reading (the run's spec) and run as before unless edited;
    the scenario itself stays as it is, and the new run records which one it revises.
    """
    rec = builder.store.load(scenario_id)
    runs = builder.records(rec)
    ss.scn_plan = PlanResult(
        question=rec.question,
        language=rec.language,
        title=rec.title,
        approach=rec.approach,
        out_of_scope=rec.out_of_scope,
    ).model_dump(mode="json")
    ss.scn_rows, ss.scn_revise, ss.scn_review = [], scenario_id, False
    for step in rec.steps:
        run = runs.get(step.n)
        reusable = run is not None and run.status == "answered" and run.spec and not run.custom_sql
        add_row(step.question, step.purpose, run.spec if reusable else None)


def new_scenario() -> None:
    """Callback: back to an empty question."""
    ss.scn_id = ss.scn_plan = ss.scn_revise = None
    ss.scn_q = ""
    st.query_params.clear()


def run_job() -> None:
    """Execute the queued plan or run with live progress, then redraw the page."""
    job = ss.pop("scn_job", None)
    if not job:
        return
    with st.status("Working…", expanded=True) as status:
        try:
            if job["action"] == "plan":
                status.update(label="Proposing a chain of questions…")
                plan = builder.plan(job["question"], lang)
                ss.scn_plan, ss.scn_id, ss.scn_review = plan.model_dump(mode="json"), None, False
                load_rows(plan)
                if not job.get("run_now") or not plan.steps:
                    status.update(label="Chain proposed: review it below", state="complete")
                    st.rerun()
                job = {"action": "run", "follow_ups": True, "force": True}
            plan = PlanResult.model_validate(ss.scn_plan)
            todo = [r["id"] for r in chain() if state(r) == "unchecked"]
            if todo:
                check_rows(todo, status)
            flagged = [r for r in chain() if state(r) in ("warned", "problem")]
            if flagged and not job.get("force"):
                ss.scn_review = True
                status.update(
                    label=f"{len(flagged)} question(s) need a look before the run",
                    state="error",
                )
                st.rerun()

            def step(label: str) -> None:
                status.update(label=label + "…")
                st.write(label)

            rec = builder.run(
                plan.question,
                steps_to_run(),
                lang=lang,
                plan=plan,
                follow_ups=job["follow_ups"],
                on_progress=step,
                based_on=ss.get("scn_revise") or "",
            )
        except LLMError as exc:
            status.update(label=f"The language model failed: {exc}", state="error")
            return
        status.update(label=f"Done · scenario {rec.scenario_id}", state="complete")
    ss.scn_review = False
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
st.html(
    '<div class="scn-steps">'
    + '<span class="scn-arrow">→</span>'.join(
        f'<span class="scn-chip"><b>{n}</b>{label}</span>' for n, label in enumerate(STEPS, 1)
    )
    + "</div>"
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
    if not builder.online:
        st.info(
            "Planning new scenarios needs the language model (set `OPENAI_API_KEY`). The recorded "
            "scenarios below can be opened without it."
        )

with st.expander("Examples", icon=":material/lightbulb:", expanded=False):
    cards = examples(lang)
    for start in range(0, len(cards), 2):
        for col, (i, (title, example)) in zip(
            st.columns(2), list(enumerate(cards))[start : start + 2], strict=False
        ):
            with col, st.container(border=True, key=f"scn-excard-{i}", height="stretch"):
                st.markdown(f"**{EXAMPLE_ICONS[i % len(EXAMPLE_ICONS)]} {title}**")
                st.markdown(f"*{example}*")
                st.button(
                    "Propose a chain for this question",
                    key=f"scn-ex-{i}",
                    type="tertiary",
                    icon=":material/arrow_forward:",
                    disabled=not builder.online,
                    on_click=queue_plan,
                    args=(example,),
                )


def render_row(i: int, row: dict, number: int | None) -> None:
    """One question of the chain: number and Run tick, question, why, order buttons, notes.

    ``number`` is the step number, or None for a row that will not run (unticked or empty).
    """
    look = state(row)
    accent, badge = ROW_LOOK[look]
    skip = "skip-" if number is None and look != "empty" else ""
    with st.container(key=f"scn-row-{skip}{row['id']}"):
        st.html(f"<style>.st-key-scn-row-{skip}{row['id']} {{ --scn-accent: {accent}; }}</style>")
        num, q, why, order = st.columns([0.55, 5.2, 4.2, 0.9], vertical_alignment="top")
        with num:
            label = number if number is not None else ("new" if look == "empty" else "skip")
            st.html(f'<div class="scn-num{" skip" if number is None else ""}">{label}</div>')
            st.checkbox("Run", key=_key("run", row["id"]), label_visibility="collapsed")
        with q:
            st.text_area(
                "Question",
                key=_key("q", row["id"]),
                height="content",
                label_visibility="collapsed",
                placeholder="Write a precise question: flow, period, partners or products",
            )
            notes = [badge]
            if look == "plan":
                notes.append(":gray[unchanged: runs exactly as checked]")
            elif look in ("checked", "warned") and row["check"].get("queried"):
                notes.append(f":gray[:material/database: {row['check']['queried']}]")
            st.markdown(" ".join(notes))
            if look in ("checked", "warned"):
                for note in row["check"].get("notes", []):
                    st.caption(f":material/info: {note}")
        with why:
            st.text_area(
                "Why this question",
                key=_key("why", row["id"]),
                height="content",
                label_visibility="collapsed",
                placeholder="What this step adds to the answer",
            )
        with order, st.container(horizontal=True, gap="small"):
            st.button(
                "",
                icon=":material/arrow_upward:",
                key=f"scn-up-{row['id']}",
                help="Move up",
                disabled=i == 0,
                on_click=move_row,
                args=(i, -1),
                type="tertiary",
            )
            st.button(
                "",
                icon=":material/arrow_downward:",
                key=f"scn-down-{row['id']}",
                help="Move down",
                disabled=i == len(ss.scn_rows) - 1,
                on_click=move_row,
                args=(i, 1),
                type="tertiary",
            )
            st.button(
                "",
                icon=":material/delete:",
                key=f"scn-del-{row['id']}",
                help="Delete this question",
                on_click=delete_row,
                args=(i,),
                type="tertiary",
            )
        if look in ("warned", "problem"):
            check = StepCheck.model_validate(row["check"])
            for p in check.problems:
                st.markdown(f":red[:material/block: {p}]")
            for w in check.warnings:
                st.markdown(f":orange[:material/warning: {w}]")
            if check.position and number is not None and check.position != number:
                st.button(
                    f"Move it to step {check.position}",
                    key=f"scn-moveto-{row['id']}",
                    icon=":material/swap_vert:",
                    on_click=move_to_step,
                    args=(row["id"], check.position),
                )
            if look == "problem":
                render_fixes(row, check)
        if row["id"] in ss.get("scn_checking", []):
            with st.spinner(
                "Checking this question: can the data answer it, and does it fit the chain "
                "here? This takes a few seconds."
            ):
                try:
                    check_rows([row["id"]])
                except LLMError as exc:  # kept on the card after the redraw
                    failed = StepCheck(problems=[f"the check could not run: {exc}"])
                    row["check"], row["checked"] = failed.model_dump(mode="json"), text(row)
            ss.scn_checked_now = True
        elif look == "unchecked" and number is not None:
            st.button(
                "Check this question",
                key=f"scn-check-{row['id']}",
                icon=":material/fact_check:",
                type="tertiary",
                disabled=not builder.online,
                help="Can the data answer it, and does it fit the chain here?",
                on_click=queue_check,
                args=([row["id"]],),
            )


def render_fixes(row: dict, check: StepCheck) -> None:
    """For a question the data cannot answer: checked rewrites to pick, and how to fix it."""
    if check.alternatives:
        st.markdown("**Try one of these instead** (each one checked against the data):")
        for k, alt in enumerate(check.alternatives):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.button(
                    alt.question,
                    key=f"scn-alt-{row['id']}-{k}",
                    icon=":material/arrow_forward:",
                    help=alt.queried,
                    on_click=use_alternative,
                    args=(row["id"], k),
                )
                if alt.note:
                    st.caption(alt.note)
    hint = check.hint or "name the flow, the period, and the partners or products"
    st.markdown(f":blue[:material/lightbulb: **Or edit it yourself:** {hint}]")


def render_plan(plan: PlanResult, revising: ScenarioRecord | None = None) -> None:
    """The proposed chain, editable: tick, edit, reorder, delete or add questions, then run.

    With ``revising``, the chain is that scenario's questions, to change and run again.
    """
    if "scn_rows" not in ss:
        load_rows(plan)
    with st.container(border=True, key="scn-plan-box"):
        if revising is not None:
            st.markdown(
                f"#### :material/edit_note: Edit the questions and run again · {plan.title}"
            )
            st.caption(
                f"The questions of scenario `{revising.scenario_id}`, follow-ups included. "
                "Questions that ran keep their checked reading and run as before unless you "
                "edit them. The new run is saved as a new scenario; this one stays as it is."
            )
        else:
            st.markdown(f"#### :material/account_tree: Proposed chain · {plan.title}")
        if plan.approach:
            st.markdown(plan.approach)
        if plan.out_of_scope:
            st.warning("**Not answerable with this data:** " + "; ".join(plan.out_of_scope))
        if not plan.steps and revising is None:
            st.error(
                "No proposed question passed the checks. Try naming the flow, the period or the "
                "partners and products you are interested in."
            )
        if revising is None:
            st.caption(
                "Every proposed question passed the assistant's checks (known codes, data "
                "limits, SQL compiles and passes the guard). Untick the box under a step's number "
                "to skip it, edit it, reorder it or add your own: added and edited questions are "
                "checked for whether the data can answer them and whether they fit the chain "
                "where they stand."
            )
        st.html(
            '<div class="scn-head"><span>Step</span><span>Question</span>'
            "<span>Why this question</span><span>Order</span></div>"
        )
        number = 0
        for i, row in enumerate(list(ss.scn_rows)):
            in_chain = ticked(row)
            number += in_chain
            render_row(i, row, number if in_chain else None)
        if ss.pop("scn_checked_now", False):  # checks ran while drawing: redraw with results
            ss.scn_checking = []
            st.rerun()
        unchecked = [r["id"] for r in chain() if state(r) == "unchecked"]
        with st.container(horizontal=True):
            st.button("Add a question", icon=":material/add:", on_click=add_row, key="scn-add")
            if unchecked:
                st.button(
                    f"Check {len(unchecked)} new or edited question(s)",
                    icon=":material/fact_check:",
                    on_click=queue_check,
                    args=(unchecked,),
                    disabled=not builder.online,
                    key="scn-check-all",
                )
        if plan.notes:
            with st.expander(f"Questions the checks dropped ({len(plan.notes)})"):
                st.markdown("\n".join(f"- {n}" for n in plan.notes))
        st.toggle(
            f"Let the assistant add follow-up questions from the answers (up to {MAX_FOLLOW_UPS})",
            value=True,
            key="scn-follow",
        )
        steps = chain()
        flagged = [r for r in steps if state(r) in ("warned", "problem")]
        if ss.get("scn_review") and flagged:
            st.warning(
                f"{len(flagged)} question(s) have notes above. Fix, move or untick them, or run "
                "the chain as it is: questions that cannot be answered as written return the "
                "assistant's suggestions instead of an answer."
            )
        with st.container(horizontal=True):
            label = f"Run the chain ({len(steps)} questions)"
            if unchecked:
                label += f", after checking {len(unchecked)}"
            st.button(
                label,
                type="primary",
                icon=":material/play_arrow:",
                disabled=not steps,
                on_click=queue_run,
                key="scn-run",
            )
            if ss.get("scn_review") and flagged:
                st.button(
                    "Run anyway",
                    icon=":material/fast_forward:",
                    on_click=queue_run,
                    args=(True,),
                    key="scn-run-anyway",
                )


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
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button(
            "Edit the questions and run again",
            icon=":material/edit_note:",
            key="scn-revise",
            disabled=ss.get("scn_revise") == rec.scenario_id,
            on_click=revise,
            args=(rec.scenario_id,),
            help="Reopen this scenario's questions to change them and run a new scenario; "
            "this one is kept",
        )
        if rec.based_on:
            st.button(
                f"Open the version it revises ({rec.based_on})",
                icon=":material/history:",
                key="scn-based-on",
                type="tertiary",
                on_click=open_scenario,
                args=(rec.based_on,),
            )


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
    if ss.get("scn_revise") == shown.scenario_id and ss.get("scn_plan"):
        render_plan(PlanResult.model_validate(ss.scn_plan), revising=shown)
elif ss.get("scn_plan"):
    render_plan(PlanResult.model_validate(ss.scn_plan))

with st.expander("Previous scenarios", icon=":material/history:", expanded=False):
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
