"""LuxTrade Lens: ask about Luxembourg's trade in goods (EN · FR · DE).

Run with ``streamlit run src/luxtrade/app/Home.py``. UI only: every computation happens in the
agent graph; this file renders run records and queues actions (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.agents.presets import PRESETS
from luxtrade.agents.service import Assistant
from luxtrade.agents.spec import QuerySpec
from luxtrade.app.components import queue, render_answer
from luxtrade.runs.sessions import new_session_id

st.set_page_config(page_title="LuxTrade Lens", page_icon="📦", layout="wide")


@st.cache_resource(show_spinner="Loading the data…")
def get_assistant() -> Assistant:
    """One assistant per server process (read-only data, stateless graph)."""
    return Assistant()


try:
    assistant = get_assistant()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

cov = assistant.sem.coverage
ss = st.session_state
params = st.query_params

# --- session selection: ?session=…, ?run=…, or a new session ------------------------------
if "session_id" not in ss:
    ss.session_id = new_session_id()
    if "run" in params and (rec := assistant.runs.load(params["run"])):
        ss.session_id, ss.focus_run = rec.session_id, rec.run_id
    elif "session" in params and assistant.sessions.get(params["session"]):
        ss.session_id = params["session"].strip().lower()


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


# --- sidebar --------------------------------------------------------------------------------
with st.sidebar:
    st.title("LuxTrade Lens")
    st.caption("Luxembourg's trade in goods · Eurostat Comext DS-045409")
    if cov.is_placeholder:
        st.warning("**Placeholder data.** Synthetic figures for development, not Eurostat values.")
    st.caption(
        f"Data {cov.first_period:%b %Y} → {cov.latest_complete_period:%b %Y} (complete) · "
        f"vintage {cov.extraction_date}"
    )
    st.caption(
        "🟢 Free questions enabled"
        if assistant.online
        else "⚪ Offline: presets and stored runs only (set ANTHROPIC_API_KEY)"
    )

    st.subheader("Presets")
    lang = st.radio(
        "Language",
        ["en", "fr", "de"],
        horizontal=True,
        label_visibility="collapsed",
        format_func=str.upper,
    )
    for p in PRESETS:
        q, spec = p.for_language(lang)
        if st.button(f"{p.id} · {p.label[lang]}", key=f"preset-{p.id}", help=q, width="stretch"):
            queue("spec", spec=spec.model_dump(), question=q, origin="preset")

    st.subheader("Sessions")
    if st.button("➕ New session", width="stretch"):
        ss.session_id = new_session_id()
        st.query_params.clear()
        st.rerun()
    search = st.text_input("Search text, run or session ID", key="search")
    sessions = assistant.sessions.search(search) if search else assistant.sessions.recent(15)
    for s in sessions:
        current = "● " if s.session_id == ss.session_id else ""
        if st.button(
            f"{current}{s.session_id} · {s.title[:38]}",
            key=f"open-{s.session_id}",
            help=f"{len(s.runs)} turn(s) · {s.created_at[:16]}",
            width="stretch",
        ):
            ss.session_id = s.session_id
            st.query_params["session"] = s.session_id
            st.rerun()

# --- conversation thread --------------------------------------------------------------------
st.markdown(f"#### Ask about Luxembourg's trade in goods · session `{ss.session_id}`")
records = assistant.sessions.records(ss.session_id)
if not records:
    st.markdown(
        "Ask in English, French or German, for example *“Who are Luxembourg's main export "
        "partners?”*, *“Quels produits importons-nous de Chine ?”* or *“Wie entwickeln sich "
        "die Exporte von Maschinen?”* — or pick a preset on the left."
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
