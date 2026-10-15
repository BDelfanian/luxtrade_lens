"""LuxTrade Lens: Luxembourg's trade in goods (EN · FR · DE).

Run with ``streamlit run src/luxtrade/app/Home.py``. Entry point: shared sidebar and navigation
between Overview (the big picture), Ask (the assistant), and Dashboard (mapped SQL charts).
UI only: every computation happens in the agents layer (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.agents.presets import PRESETS
from luxtrade.app.components import ASK_PAGE, get_assistant, queue
from luxtrade.runs.sessions import new_session_id

st.set_page_config(page_title="LuxTrade Lens", page_icon="📦", layout="wide")

try:
    assistant = get_assistant()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

overview_page = st.Page(
    "app_pages/overview.py", title="Overview", icon=":material/insights:", default=True
)
ask_page = st.Page(ASK_PAGE, title="Ask", icon=":material/forum:", url_path="ask")
dashboard_page = st.Page(
    "app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", url_path="dashboard"
)
page = st.navigation([overview_page, ask_page, dashboard_page], position="top")

cov = assistant.sem.coverage
ss = st.session_state
params = st.query_params

# --- session selection: ?session=…, ?run=…, or a new session ------------------------------
if "session_id" not in ss:
    ss.session_id = new_session_id()
    deep_link = False
    if "run" in params and (rec := assistant.runs.load(params["run"])):
        ss.session_id, ss.focus_run = rec.session_id, rec.run_id
        deep_link = True
    elif "session" in params and assistant.sessions.get(params["session"]):
        ss.session_id = params["session"].strip().lower()
        deep_link = True
    if deep_link and page.url_path != ask_page.url_path:
        st.switch_page(ask_page, query_params=params.to_dict())


def open_ask() -> None:
    """Go to the assistant (the queued action runs there)."""
    st.switch_page(ask_page)


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
        else "⚪ Offline: overview, presets and stored runs only (set OPENAI_API_KEY)"
    )

    # the choice lives in ss.lang: widget state alone doesn't survive a page switch
    ss.setdefault("lang", "en")
    choice = st.segmented_control(
        "Language",
        ["en", "fr", "de"],
        default=ss.lang,
        format_func=str.upper,
        key="lang_choice",
        help="Language of the overview texts and of the preset questions.",
    )
    if choice:
        ss.lang = choice
    lang = ss.lang

    st.subheader("Presets")
    for p in PRESETS:
        q, spec = p.for_language(lang)
        if st.button(f"{p.id} · {p.label[lang]}", key=f"preset-{p.id}", help=q, width="stretch"):
            queue("spec", spec=spec.model_dump(), question=q, origin="preset")
            open_ask()

    st.subheader("Sessions")
    if st.button("New session", icon=":material/add:", width="stretch"):
        ss.session_id = new_session_id()
        st.query_params.clear()
        open_ask()
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
            st.switch_page(ask_page, query_params={"session": s.session_id})

page.run()
