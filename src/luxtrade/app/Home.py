"""LuxTrade Lens: Luxembourg's trade in goods (EN · FR · DE).

Run with ``streamlit run src/luxtrade/app/Home.py``. Entry point: shared top bar (provenance,
language) and navigation between the Overview (landing page, the big picture) and Ask (the
assistant, for specific questions, with presets and sessions). UI only: every computation
happens in the agents layer (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.app.components import ASK_PAGE, get_assistant
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
page = st.navigation([overview_page, ask_page], position="top")
# larger top tabs: Streamlit has no size option for the top navigation
st.html(
    """<style>
    [data-testid="stTopNavLink"] { padding: 0.5rem 1.1rem; }
    [data-testid="stTopNavLink"] * { font-size: 1.2rem !important; font-weight: 600; }
    </style>"""
)

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


# --- top bar, shared by both pages: data provenance and language ----------------------------
with st.container(horizontal=True, vertical_alignment="center"):
    status = (
        "🟢 Free questions enabled"
        if assistant.online
        else "⚪ Offline: overview, presets and stored runs only (set OPENAI_API_KEY)"
    )
    st.caption(
        f"**LuxTrade Lens** · Eurostat Comext DS-045409 · data {cov.first_period:%b %Y} → "
        f"{cov.latest_complete_period:%b %Y} (complete) · vintage {cov.extraction_date} · "
        f"{status}"
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
        label_visibility="collapsed",
    )
    if choice:
        ss.lang = choice
if cov.is_placeholder:
    st.warning("**Placeholder data.** Synthetic figures for development, not Eurostat values.")

page.run()
