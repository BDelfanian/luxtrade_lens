"""LuxTrade Lens: Luxembourg's trade in goods (EN · FR · DE).

Run with ``streamlit run src/luxtrade/app/Home.py``. Entry point: the app's name, one row of tabs
(Overview: the big picture · Assistant, with presets and sessions · Dashboard: mapped
SQL charts on the left; Data · How it works and the language switch on the right), and a footer
naming the team. UI only: every computation happens in the agents layer (GUIDELINES §1.1).
"""

import streamlit as st

from luxtrade.app.components import ASK_PAGE, CONTRIBUTORS, get_assistant
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
ask_page = st.Page(ASK_PAGE, title="Assistant", icon=":material/forum:", url_path="ask")
dashboard_page = st.Page(
    "app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", url_path="dashboard"
)
data_page = st.Page("app_pages/data.py", title="Data", icon=":material/database:", url_path="data")
method_page = st.Page(
    "app_pages/method.py",
    title="How it works",
    icon=":material/settings_suggest:",
    url_path="how-it-works",
)
MAIN_TABS = (overview_page, ask_page, dashboard_page)  # left of the top bar
INFO_TABS = (data_page, method_page)  # right of the top bar, before the language switch
# Streamlit's own navigation is hidden: the five pages are tabs in the top bar below, in one row
page = st.navigation([*MAIN_TABS, *INFO_TABS], position="hidden")
# larger tab labels (Streamlit has no size option for page links); the app's name sits close to
# the top edge, with only the room Streamlit's header needs
st.html(
    """<style>
    .st-key-top-tabs [data-testid="stPageLink"] p { font-size: 1.15rem; font-weight: 600; }
    [data-testid="stMainBlockContainer"] { padding-top: 3rem; }
    [data-testid="stHeader"] { background: transparent; }
    /* tables: let cell text use the whole column (Streamlit caps it at 400 px) */
    [data-testid="stTable"] td [data-testid="stMarkdownContainer"] { max-width: none; width: 100%; }
    .st-key-app-name h1 { padding: 0; }
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


# --- top bar, shared by all pages: the app's name, the page tabs and the language -----------
with st.container(key="app-name"):
    st.title("LuxTrade Lens", anchor=False)
with st.container(horizontal=True, vertical_alignment="center", key="top-tabs"):
    for p in MAIN_TABS:
        st.page_link(p, label=p.title, icon=p.icon)
    st.space("stretch")
    for p in INFO_TABS:
        st.page_link(p, label=p.title, icon=p.icon)
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
if not assistant.online:  # only worth saying when free questions are switched off
    st.caption("⚪ Offline: overview, presets and stored runs only (set OPENAI_API_KEY)")
if cov.is_placeholder:
    st.warning("**Placeholder data.** Synthetic figures for development, not Eurostat values.")

page.run()

# --- footer, on every page: the team and the status of the app ---------------------------------
with st.container(key="app-footer"):
    st.divider()
    st.caption(
        "**Proof of concept** built with vibe coding for the STATEC Hackathon 2026 · "
        "The Outliers: " + " · ".join(f"{name} ({org})" for name, org in CONTRIBUTORS)
    )
