"""Ask: the assistant. Questions, follow-ups, presets and overview explorations land here.

UI only: renders run records and queues actions (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.agents.presets import PRESETS
from luxtrade.agents.spec import QuerySpec
from luxtrade.app.components import get_assistant, queue, render_answer
from luxtrade.runs.sessions import new_session_id

assistant = get_assistant()
cov = assistant.sem.coverage
ss = st.session_state


def run_pending() -> None:
    """Execute a queued action with live step progress, then rerun."""
    job = ss.pop("pending", None)
    if not job:
        return
    if job["action"] == "verify":
        rec = assistant.runs.load(job["run_id"])
        st.toast(assistant.verify(rec) if rec else "Run not found")
        return
    with st.status("Working…", expanded=False) as status:

        def step(label: str) -> None:
            status.update(label=label + "…")

        if job["action"] == "ask":
            rec = assistant.ask(
                job["question"], ss.session_id, fresh=job.get("fresh", False), on_step=step
            )
        elif job["action"] == "suggest":
            rec = assistant.suggest(job["question"], ss.session_id, on_step=step)
        else:
            rec = assistant.run_spec(
                QuerySpec.model_validate(job["spec"]),
                question=job["question"],
                origin=job["origin"],
                session_id=ss.session_id,
                parent_run_id=job.get("parent"),
                on_step=step,
            )
        status.update(label=f"Done · run {rec.run_id}", state="complete")
    st.query_params["session"] = ss.session_id
    st.rerun()


def open_session(session_id: str) -> None:
    """Callback: switch the conversation shown on this page (before the page redraws)."""
    ss.session_id = session_id
    st.query_params.clear()
    st.query_params["session"] = session_id


def start_session() -> None:
    """Callback: an empty conversation."""
    ss.session_id = new_session_id()
    st.query_params.clear()


records = assistant.sessions.records(ss.session_id)
lang = ss.get("lang") or "en"

with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(f"#### Ask about Luxembourg's trade in goods · session `{ss.session_id}`")
    st.button("New session", key="new-session", icon=":material/add:", on_click=start_session)

# presets open by default only on an empty conversation, so they don't push answers down
with (
    st.expander("Preset questions", icon=":material/bolt:", expanded=not records),
    st.container(horizontal=True),
):
    for p in PRESETS:
        q, spec = p.for_language(lang)
        if st.button(f"{p.id} · {p.label[lang]}", key=f"preset-{p.id}", help=q):
            queue("spec", spec=spec.model_dump(), question=q, origin="preset")

with st.expander("Previous sessions", icon=":material/history:"):
    search = st.text_input("Search text, run or session ID", key="search")
    sessions = assistant.sessions.search(search) if search else assistant.sessions.recent(15)
    for s in sessions:
        current = s.session_id == ss.session_id
        st.button(
            f"{s.session_id} · {s.title[:80]}",
            key=f"open-{s.session_id}",
            help=f"{len(s.runs)} turn(s) · {s.created_at[:16]}",
            icon=":material/radio_button_checked:" if current else ":material/chat:",
            type="tertiary",
            disabled=current,
            on_click=open_session,
            args=(s.session_id,),
        )
    if not sessions:
        st.caption("No sessions found.")

if not records:
    st.markdown(
        "Ask in English, French or German, for example:\n\n"
        "- *“Who are Luxembourg's main export partners?”*\n"
        "- *“Quels produits importons-nous de Chine ?”*\n"
        "- *“Wie entwickeln sich die Exporte von Maschinen?”*\n\n"
        "Or pick a preset above. New here? The **Overview** page gives the big picture "
        "first."
    )
for rec in records:
    with st.chat_message("user"):
        st.markdown(rec.question)
    with st.chat_message("assistant"):
        render_answer(rec, cov.latest_complete_year)

optimise_first = st.toggle(
    "✨ Optimise my question before running it",
    value=False,
    help="Get three precise, validated versions of your question first.",
    disabled=not assistant.online,
)
question = st.chat_input("Ask a follow-up or a new question…", disabled=not assistant.online)
if question:
    queue("suggest" if optimise_first else "ask", question=question)

run_pending()
