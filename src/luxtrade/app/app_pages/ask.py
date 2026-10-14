"""Ask: the assistant. Questions, follow-ups, presets and overview explorations land here.

UI only: renders run records and queues actions (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.agents.spec import QuerySpec
from luxtrade.app.components import get_assistant, queue, render_answer

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


st.markdown(f"#### Ask about Luxembourg's trade in goods · session `{ss.session_id}`")
records = assistant.sessions.records(ss.session_id)
if not records:
    st.markdown(
        "Ask in English, French or German, for example *“Who are Luxembourg's main export "
        "partners?”*, *“Quels produits importons-nous de Chine ?”* or *“Wie entwickeln sich "
        "die Exporte von Maschinen?”* — or pick a preset on the left. New here? The "
        "**Overview** page gives the big picture first."
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
