"""Ask: the assistant. Questions, follow-ups, presets and overview explorations land here.

UI only: renders run records and queues actions (GUIDELINES §1.1).
"""

from datetime import date, datetime, timedelta

import streamlit as st

from luxtrade.agents.presets import PRESETS
from luxtrade.agents.spec import QuerySpec
from luxtrade.app.components import get_assistant, queue, render_answer
from luxtrade.runs.sessions import new_session_id

assistant = get_assistant()
cov = assistant.sem.coverage
ss = st.session_state


def scroll_to(anchor: str) -> None:
    """Bring an anchor into view: the work and the new answer are drawn low on the page.

    The scroll is re-applied every 0.25 s for 2.5 s while the page finishes drawing: a chat
    page otherwise pins itself to the bottom once the last elements arrive.
    """
    st.html(
        f"""<script>
(function () {{
  const start = Date.now();
  const go = () => {{
    const el = document.getElementById("{anchor}");
    if (el && Math.abs(el.getBoundingClientRect().top) > 4) {{
      el.scrollIntoView({{block: "start"}});
    }}
    if (Date.now() - start < 2500) setTimeout(go, 250);
  }};
  go();
}})();
</script>""",
        unsafe_allow_javascript=True,
    )


def run_pending() -> None:
    """Execute a queued action with live step progress, then rerun."""
    job = ss.pop("pending", None)
    if not job:
        return
    st.html('<div id="lt-working"></div>')
    scroll_to("lt-working")
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
    ss.scroll_to = rec.run_id  # after the rerun, show the start of the new answer
    st.query_params["session"] = ss.session_id
    st.rerun()


def open_session(session_id: str) -> None:
    """Callback: switch the conversation shown on this page (before the page redraws)."""
    ss.session_id = session_id
    st.query_params.clear()
    st.query_params["session"] = session_id


def local_time(iso: str) -> datetime:
    """A stored UTC timestamp in the server's local time (Luxembourg)."""
    return datetime.fromisoformat(iso).astimezone()


def day_label(day: date) -> str:
    """'Today', 'Yesterday' or 'Thu 15 Oct 2026': the heading of a group of sessions."""
    today = date.today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%a %d %b %Y}"


TOP_LINK = (
    '<a class="lt-top-link" href="#lt-top" title="Back to the top of the page" '
    "onclick=\"event.preventDefault(); document.getElementById('lt-top')"
    ".scrollIntoView({behavior: 'smooth', block: 'start'});\">↑ Top</a>"
)


def start_session() -> None:
    """Callback: an empty conversation."""
    ss.session_id = new_session_id()
    st.query_params.clear()


records = assistant.sessions.records(ss.session_id)
lang = ss.get("lang") or "en"

# where the Top links scroll back to; the links scroll in the browser (no rerun, which would
# let Streamlit restore the old scroll position)
st.html(
    """<div id="lt-top"></div>
<style>
.lt-top-link { font-size: 0.875rem; color: inherit; opacity: 0.65; text-decoration: none; }
.lt-top-link:hover { opacity: 1; text-decoration: underline; }
</style>"""
)
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(f"#### Ask about Luxembourg's trade in goods · session `{ss.session_id}`")
    st.button("New session", key="new-session", icon=":material/add:", on_click=start_session)

# presets open by default only on an empty conversation, so they don't push answers down;
# the full question on each button, two per row (stacked on a phone), read from the left
# (Streamlit centres button text and has no option for it, hence the scoped style)
st.html(
    """<style>
    [class*="st-key-preset-"] button { justify-content: flex-start; text-align: left; }
    [class*="st-key-preset-"] button div,
    [class*="st-key-preset-"] button p { justify-content: flex-start; text-align: left; }
    </style>"""
)
with st.expander("Preset questions", icon=":material/bolt:", expanded=not records):
    cols = st.columns(2)
    for i, p in enumerate(PRESETS):
        q, spec = p.for_language(lang)
        if cols[i % 2].button(
            f"**{p.id}** · {q}",
            key=f"preset-{p.id}",
            help=p.label[lang],
            width="stretch",
            wrap=True,  # the full question, never cut with an ellipsis
        ):
            queue("spec", spec=spec.model_dump(), question=q, origin="preset")

with st.expander("Previous sessions", icon=":material/history:"):
    search = st.text_input(
        "Search text, run or session ID, or a date",
        key="search",
        placeholder="e.g. vehicles · k7p2qx · 2026-10-15",
    )
    sessions = assistant.sessions.search(search) if search else assistant.sessions.recent(15)
    shown_day = None
    for s in sessions:
        current = s.session_id == ss.session_id
        last, started = local_time(s.last_active), local_time(s.created_at)
        if last.date() != shown_day:  # one heading per day, newest first
            shown_day = last.date()
            st.caption(f"**{day_label(shown_day)}**")
        n = len(s.runs)
        meta = [f"{last:%H:%M}", f"{n} question{'s' if n != 1 else ''}"]
        if s.language:
            meta.append(s.language.upper())
        meta.append(s.session_id)
        st.button(
            f"{s.title[:80]} :gray[· {' · '.join(meta)}]",
            key=f"open-{s.session_id}",
            help=f"Started {started:%d %b %Y, %H:%M} · last question {last:%d %b %Y, %H:%M}"
            f" · runs {', '.join(s.runs)}",
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
target = ss.pop("scroll_to", None)  # once: later reruns keep the reader's position
for rec in records:
    if rec.run_id == target:
        st.html(f'<div id="run-{rec.run_id}"></div>')
        scroll_to(f"run-{rec.run_id}")
    with st.chat_message("user"):
        st.markdown(rec.question)
    with st.chat_message("assistant"):
        render_answer(rec, cov.latest_complete_year)
        st.html(TOP_LINK, unsafe_allow_javascript=True)

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
