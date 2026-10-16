"""Overview: Luxembourg's trade in goods at a glance, the landing page (SOLUTION_DESIGN §8a).

Three tabs. **The challenge** states the problem the page answers. **Key findings** tells the
story for decision-makers, ready to present: one line, the story in four numbers, a chapter per
finding (headline, evidence, chart) and three things to watch; "To know more" opens a finding's
charts, queries and method in a dialog. **More evidence** covers the sample questions of
the hackathon brief and one of our own. Presentation mode shows the challenge and the key
findings as full-screen slides. Each finding and question opens in the assistant for details;
the data itself is described on the Data page.
UI only: the content comes from ``Assistant.overview`` (agents/overview.py, agents/findings.py).
"""

import pandas as pd
import streamlit as st

from luxtrade.agents import trails
from luxtrade.agents.findings import Finding
from luxtrade.agents.pitch import numbers_kicker, tool_pitch
from luxtrade.app.components import (
    ASK_PAGE,
    CONTRIBUTORS,
    POC_NOTE,
    get_assistant,
    load_overview,
    queue,
    render_chart,
    render_trace,
)
from luxtrade.runs.store import RunRecord
from luxtrade.viz.charts import finding_figures, hero_figure, overview_figures

assistant = get_assistant()
cov = assistant.sem.coverage
lang = st.session_state.get("lang") or "en"
ov = load_overview(lang, cov.vintage)
chart_config = {"displaylogo": False}
hero_config = {"displayModeBar": False}  # the card charts: a picture, not a tool


def explore_button(key: str, question: str, spec: object) -> None:
    """Open the same question in the assistant, with filters, tables and a full trace."""
    if st.button(
        "Explore in the assistant",
        key=f"explore-{key}",
        icon=":material/arrow_forward:",
        help=question,
    ):
        queue("spec", spec=spec.model_dump(), question=question, origin="overview")
        st.switch_page(ASK_PAGE)


def evidence(key: str, sql: list[str], main: pd.DataFrame, methods: list[str]) -> None:
    """Queries, data and method behind a finding or a question."""
    with st.expander("Evidence: queries, data and method", icon=":material/fact_check:"):
        for n, query in enumerate(sql, start=1):
            st.caption(f"Query {n} of {len(sql)} (checked by the SQL guard)")
            st.code(query, language="sql")
        st.dataframe(main, hide_index=True, width="stretch")
        st.download_button(
            "Download CSV",
            main.to_csv(index=False).encode("utf-8"),
            file_name=f"luxtrade_overview_{key}_{ov.year}.csv",
            mime="text/csv",
            key=f"csv-ov-{key}",
        )
        st.markdown("**Method**\n" + "\n".join(f"- {m}" for m in methods))


def trail_step(
    n: int, step: trails.Step, done: trails.BuiltStep, rec: RunRecord, numbers: dict[str, int]
) -> None:
    """One question of the trail: why we asked, what the assistant answered, what we took.

    ``numbers`` maps the trail's run IDs to step numbers, to say which step a follow-up builds on.
    """
    with st.container(border=True):
        meta = f"**Step {n}** · run `{rec.run_id}`"
        if rec.followup_of:
            meta += f" · follow-up of step {numbers.get(rec.followup_of, '?')}"
            if rec.inherited:
                meta += f", kept: {', '.join(rec.inherited)}"
        else:
            meta += " · new question"
        st.caption(meta)
        st.markdown(f"**:material/person: We asked:** *{rec.question}*")
        st.caption(f"Why: {step.why}")
        answer, chart, how = st.tabs(["Answer", "Chart", "How the assistant got this"])
        with answer:
            if rec.status == "answered":
                st.markdown(" ".join(rec.insight))
                if rec.facts:
                    st.markdown("\n".join(f"- {x['text']}" for x in rec.facts[:6]))
            else:
                st.markdown(
                    "The assistant did not answer this one as written. It explained why and "
                    "offered answerable versions:"
                )
                st.markdown("\n".join(f"- *{s['question']}*" for s in rec.suggestions))
        with chart:
            if rec.status == "answered":
                render_chart(rec)
            else:
                st.caption("No chart: no query was run.")
        with how:
            render_trace(rec)
        found = [e for e, ok in done.checks.items() if ok]
        ticks = " ".join(f":green-badge[:material/check: {e}]" for e in found)
        st.markdown(f"**:material/lightbulb: What we took from it:** {step.learnt}")
        if ticks:
            st.markdown(f"In the answer: {ticks}")


def render_trail(f: Finding) -> None:
    """The chain of real assistant runs that leads to the finding."""
    view = trails.load(f.key, assistant.runs)
    if view is None:
        st.info(
            "The investigation for this finding has not been recorded yet "
            "(run `python -m luxtrade.agents.trails`)."
        )
        return
    t = view.trail
    st.markdown(f"**The concern:** {t.goal}")
    st.caption(
        f"One question rarely settles a concern. These are the {len(view.steps)} questions we "
        f"asked the assistant, in order, in one session (`{view.session_id}`, recorded "
        f"{view.built_at[:10]}). Each answer is the stored run, unedited."
    )
    numbers = {rec.run_id: n for n, (_, _, rec) in enumerate(view.steps, start=1)}
    for n, (step, done, rec) in enumerate(view.steps, start=1):
        trail_step(n, step, done, rec, numbers)
    with st.container(border=True, key=f"trail-sum-{f.key}"):
        st.markdown(f"**:material/merge: Putting it together.** {t.synthesis}")
        if t.beyond:
            st.caption(f":material/info: Not from the assistant: {t.beyond}")
    if st.button(
        "Continue this investigation in the assistant",
        key=f"trail-open-{f.key}",
        icon=":material/forum:",
        help="Opens this session in the assistant: ask your own follow-up",
    ):
        st.session_state.session_id = view.session_id
        st.switch_page(ASK_PAGE)


def finding_detail(f: Finding) -> None:
    """Body of the 'To know more' dialog: the assistant's trail, then charts and evidence."""
    st.markdown(f"### {f.headline}")
    trail_tab, evidence_tab = st.tabs(["How the assistant got here", "Charts, queries and method"])
    with trail_tab:
        render_trail(f)
    with evidence_tab:
        finding_evidence(f)


def finding_evidence(f: Finding) -> None:
    """The finding's facts, charts, caveats and the panel's own queries."""
    st.markdown(f"**{f.title}**")
    st.markdown(f.summary)
    st.markdown("\n".join(f"- {fact}" for fact in f.facts))
    for j, fig in enumerate(finding_figures(f.key, f.frames, f.chart_titles, lang)):
        st.plotly_chart(fig, key=f"fd-{f.key}-{j}", config=chart_config, alt=f.chart_titles[j])
    if f.key == "conclusion":
        st.table(f.frames["main"], hide_index=True, alt=f.name)
    if f.note:
        st.caption(f":material/lightbulb: {f.note}")
    for lim in f.limits:
        st.caption(f":material/info: {lim}")
    if f.sql:
        evidence(f.key, f.sql, f.frames["main"], f.methods)
    if f.explore_spec is not None and f.explore_question:
        explore_button(f"finding-{f.key}", f.explore_question, f.explore_spec)


def more_button(f: Finding) -> None:
    """'To know more': the finding's charts, queries and method in a dialog."""
    if st.button(
        "To know more",
        key=f"more-{f.key}",
        icon=":material/open_in_full:",
    ):
        st.dialog(f.name, width="large")(finding_detail)(f)


# icon and colour of each chapter; the conclusion's three things to watch (and their chapters)
CHAPTER = {
    "diversification": (":material/category:", "blue"),
    "shocks": (":material/bolt:", "red"),
    "europe": (":material/public:", "green"),
    "prices": (":material/scale:", "orange"),
    "composition": (":material/stacked_bar_chart:", "violet"),
    "conclusion": (":material/flag:", "gray"),
}
# which sample question of the hackathon brief each 'More evidence' panel covers
BRIEF = {"partners": "Q1", "products": "Q2", "peers": "Q5", "season": "Q6"}
WIDE = {"composition"}  # findings whose chart takes the card's full width
WATCH = (
    (":material/factory:", "shocks"),
    (":material/local_shipping:", "diversification"),
    (":material/local_gas_station:", "prices"),
)
# Soft two-tone tints per chapter (translucent, so they read in light and dark themes), and a
# print layout: landscape pages, panels kept whole, charts scaled to the printed column.
TINTS = {  # pale blue, rose, pale green, sand, light sky blue: one family per chapter
    "diversification": "rgba(42,120,214,.24), rgba(42,120,214,.10)",
    "shocks": "rgba(227,73,72,.13), rgba(235,104,52,.05)",
    "europe": "rgba(27,175,122,.17), rgba(27,175,122,.05)",
    "prices": "rgba(237,161,0,.18), rgba(237,161,0,.05)",
    "composition": "rgba(98,80,214,.14), rgba(98,80,214,.04)",
    "conclusion": "rgba(64,160,235,.16), rgba(64,160,235,.04)",
}
_tint_css = "\n".join(
    f".st-key-card-{k}, .st-key-tile-{k}, .st-key-watch-{k}, .st-key-ctx-{k} "
    f"{{ background: linear-gradient(135deg, {v}); border-color: transparent !important; }}"
    for k, v in TINTS.items()
)
# The tiles' numbers in a colour that says which way they went: green for a rise, red for a fall
# (and for a count of falls); a ratio or a level keeps the text colour. The delta pill follows.
TONES = {"up": ("#0E8A45", "rgba(14,138,69,.13)"), "down": ("#D33A36", "rgba(211,58,54,.12)")}
_tone_css = "\n".join(
    f".st-key-tile-{f.key} [data-testid='stMetricValue'], "
    f".st-key-dtile-{f.key} [data-testid='stMetricValue'] {{ color: {ink}; }}\n"
    f".st-key-tile-{f.key} [data-testid='stMetricDelta'], "
    f".st-key-dtile-{f.key} [data-testid='stMetricDelta'] {{ color: {ink} !important; "
    f"background: {wash} !important; }}"
    for f in ov.findings
    if f.tone in TONES
    for ink, wash in [TONES[f.tone]]
)
st.html(
    f"""<style>
{_tint_css}
{_tone_css}
[class*="st-key-card-"] {{ padding: 1.5rem 1.75rem !important; }}
[class*="st-key-tile-"] [data-testid="stMetricLabel"] {{
  min-height: 2.9rem; align-items: flex-start; }}
[class*="st-key-tile-"] [data-testid="stMetricLabel"] * {{
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
[class*="st-key-ctx-"], .st-key-task {{
  border-radius: 0.75rem; padding: 1.25rem 1.5rem !important; }}
.st-key-task {{ background: linear-gradient(135deg, {TINTS["conclusion"]}); }}
.st-key-present-start {{
  margin-bottom: -3.4rem; position: relative; z-index: 2; pointer-events: none; }}
.st-key-present-start button {{ pointer-events: auto; }}
@media print {{
  @page {{ size: A4 landscape; margin: 8mm; }}
  [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
  [data-testid="stSidebar"], [data-testid="stBottom"], [role="tablist"], .stButton,
  [data-testid="stExpander"], [data-testid="stButtonGroup"] {{ display: none !important; }}
  [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"],
  [data-testid="stMainBlockContainer"] {{
    overflow: visible !important; height: auto !important; position: static !important; }}
  [data-testid="stMainBlockContainer"] {{
    padding: 0 !important; max-width: 100% !important; zoom: 0.85; }}
  .st-key-next-step, .st-key-present-start, [data-testid="stHeading"]:has(h1) {{
    display: none !important; }}
  [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; }}
  [data-testid="stColumn"] {{ min-width: 0 !important; }}
  [data-testid="stMetricLabel"] * {{
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
  [class*="st-key-card-"], [class*="st-key-tile-"] {{
    break-inside: avoid; page-break-inside: avoid; }}
  [class*="st-key-card-"] {{ margin-bottom: 3mm; }}
  /* charts: every wrapper fills the column; the plot layer sets the height, the label
     layer (annotations, legend) lies on top of it, both scaled by their viewBox */
  .stPlotlyChart, .stPlotlyChart div {{
    width: 100% !important; max-width: 100% !important; height: auto !important; }}
  .stPlotlyChart .svg-container {{ position: relative !important; }}
  .stPlotlyChart .main-svg {{ width: 100% !important; height: auto !important; }}
  .stPlotlyChart .main-svg:first-of-type {{ position: relative !important; }}
  .stPlotlyChart .main-svg ~ .main-svg {{ position: absolute !important; top: 0; left: 0; }}
  .stPlotlyChart .modebar-container {{ display: none !important; }}
  * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
}}
</style>
<script>
// Before printing, give each chart a viewBox so it scales to the printed column.
window.addEventListener("beforeprint", () => {{
  document.querySelectorAll(".stPlotlyChart .main-svg").forEach((svg) => {{
    const w = svg.getAttribute("width"), h = svg.getAttribute("height");
    if (w && h) {{
      svg.setAttribute("viewBox", `0 0 ${{w}} ${{h}}`);
      svg.setAttribute("preserveAspectRatio", "xMinYMin meet");
    }}
  }});
}});
</script>""",
    unsafe_allow_javascript=True,
)


def chapter_label(number: str, f: Finding) -> None:
    """The chapter's name, large and in its colour: '1 · Diversification'."""
    icon, color = CHAPTER[f.key]
    st.markdown(f"#### :{color}[{icon} {number}{f.name}]")


def render_challenge(slide: bool = False) -> None:
    """The problem the page answers: the question, three facts of context, the task, our approach.

    On a slide, the approach is left out so the question and the context fill the screen.
    """
    c = ov.challenge
    if c is None:
        return
    st.markdown(f"#### :blue[:material/flag_circle: {c.kicker}]")
    st.markdown(f"# {c.statement}" if slide else f"## {c.statement}")
    for col, (tint, title, text) in zip(st.columns(len(c.context)), c.context, strict=True):
        key = f"dctx-{tint}" if slide else f"ctx-{tint}"
        with col, st.container(key=key, height="stretch"):
            st.markdown(f"#### {title}")
            st.markdown(text)
    with st.container(key="dtask" if slide else "task"):
        st.markdown(c.task)
    if slide:
        return
    st.markdown(f"### {c.approach_title}")
    for col, (icon, title, text) in zip(st.columns(len(c.approach)), c.approach, strict=True):
        with col, st.container(border=True, height="stretch"):
            st.markdown(f"**{icon} {title}**")
            st.markdown(text)


def render_tool() -> None:
    """The assistant on one slide: the promise, who it is for, four features, how it works."""
    t = tool_pitch(lang)
    st.markdown(f"#### :violet[:material/smart_toy: {t.kicker}]")
    st.markdown(f"# {t.headline}")
    st.markdown(t.audience)
    for col, (tint, icon, title, text) in zip(st.columns(len(t.features)), t.features, strict=True):
        with col, st.container(key=f"dfeat-{tint}", height="stretch"):
            st.markdown(f"#### {icon} {title}")
            st.markdown(text)
    with st.container(key="dflow"):
        st.markdown("  →  ".join(t.flow))
    st.caption(t.bridge)


# --- presentation mode: the Key findings as full-screen slides -----------------------------------
ss = st.session_state
SLIDE_TINTS = {  # slide background: the chapter's tint; extra slides get their own
    "challenge": "rgba(82,81,78,.06), rgba(64,160,235,.06)",
    "tool": "rgba(98,80,214,.12), rgba(42,120,214,.10)",
    "title": "rgba(42,120,214,.12), rgba(27,175,122,.08)",
    "options": TINTS["conclusion"],
    "team": "rgba(82,81,78,.10), rgba(64,160,235,.08)",
    **TINTS,
}
CHART_HEIGHT = 560  # charts on a slide: taller than on the page


def start_presentation() -> None:
    """Callback: open the slides at the first one."""
    ss.deck_on, ss.deck_slide = True, 0


def stop_presentation() -> None:
    """Callback: back to the Overview page."""
    ss.deck_on = ss.deck_print = False


def move(step: int, last: int) -> None:
    """Callback: go ``step`` slides forward (or back), staying within the deck."""
    ss.deck_slide = min(max(ss.get("deck_slide", 0) + step, 0), last)


def deck_css(slides: list[str]) -> str:
    """Hide the app's frame; make each slide fill the screen with larger type."""
    deck = ", ".join(f".st-key-deck-{k}" for k in slides)
    centred = ", ".join(f".st-key-dbody-{k}" for k in CENTRED)
    ground = "#0E1117" if st.context.theme.type == "dark" else "#FFFFFF"  # behind the controls
    tints = "\n".join(
        f".st-key-deck-{k}, .st-key-dtile-{k}, .st-key-dwatch-{k}, .st-key-dctx-{k}, "
        f".st-key-dfeat-{k} "
        f"{{ background: linear-gradient(135deg, {v}); }}"
        for k, v in SLIDE_TINTS.items()
    )
    return f"""<style>
[data-testid="stHeader"], .st-key-app-name, .st-key-top-tabs, .st-key-app-footer,
.st-key-deckkeys {{ display: none !important; }}
[data-testid="stMainBlockContainer"] {{
  padding: 1.25rem 2.5rem 0.75rem !important; max-width: 100% !important; }}
{deck} {{ min-height: 84vh; padding: 1.4rem 3.25rem 1rem !important; border-radius: 1rem;
  justify-content: flex-start; }}
:is({deck}) > div:has(> [class*="st-key-dbody-"]) {{
  flex-grow: 1; display: flex; flex-direction: column; }}
[class*="st-key-dbody-"] {{ flex-grow: 1; justify-content: flex-start; padding-top: 1rem; }}
{centred} {{ justify-content: center; padding-top: 0; }}
.st-key-dtask {{ background: linear-gradient(135deg, {TINTS["conclusion"]}); }}
[class*="st-key-dtile-"], [class*="st-key-dwatch-"], [class*="st-key-dctx-"], .st-key-dtask,
[class*="st-key-dfeat-"] {{
  border-radius: 0.75rem; padding: 1.25rem 1.5rem !important; }}
{tints}
.st-key-deck-title h1 {{ font-size: 3.4rem !important; line-height: 1.15; }}
.st-key-deck-challenge h1 {{ font-size: 2.9rem !important; line-height: 1.2; }}
.st-key-deck-tool h1 {{ font-size: 2.3rem !important; line-height: 1.2; padding: 0.4rem 0; }}
.st-key-deck-tool p {{ font-size: 1.12rem !important; line-height: 1.42; }}
.st-key-deck-tool h4 {{ font-size: 1.35rem !important; padding: 0.25rem 0 0.75rem; }}
.st-key-deck-tool [class*="st-key-dfeat-"] {{ padding: 0.9rem 1.2rem !important; gap: 0.75rem; }}
.st-key-dflow {{ border-radius: 0.75rem; padding: 0.6rem 1.5rem !important;
  background: rgba(98,80,214,.10); }}
.st-key-dflow p {{ font-size: 1.25rem !important; font-weight: 600; text-align: center; }}
:is({deck}) h1 {{ text-wrap: balance; }}
/* the controls stay at the bottom of the screen, even when a slide is taller than it */
div:has(> .st-key-decknav) {{ position: sticky; bottom: 0; z-index: 5; padding: 0.5rem 0;
  background: {ground}; }}
:is({deck}) [data-testid="stHeaderActionElements"] {{ display: none !important; }}
:is({deck}) h2 {{ font-size: 2.6rem !important; line-height: 1.2; }}
:is({deck}) h4 {{ font-size: 1.6rem !important; }}
:is({deck}) p, :is({deck}) li, :is({deck}) td, :is({deck}) th {{
  font-size: 1.3rem !important; line-height: 1.55; }}
:is({deck}) [data-testid="stMetricValue"], :is({deck}) [data-testid="stMetricValue"] * {{
  font-size: 3.6rem !important; line-height: 1.2; }}
[class*="st-key-dtile-"] [data-testid="stMetricLabel"] {{
  min-height: 5.4rem; align-items: flex-start; }}
:is({deck}) [data-testid="stMetricLabel"] * {{ font-size: 1.15rem !important;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
</style>"""


def deck_chart(f: Finding, height: int = CHART_HEIGHT) -> None:
    """The finding's chart, sized for a screen at the back of a room."""
    fig = hero_figure(f.key, f.frames, lang)
    if fig is None:
        return
    fig.update_layout(height=height, font={"size": 17}, legend={"font": {"size": 16}})
    fig.update_xaxes(tickfont={"size": 16}, title_font={"size": 16})
    fig.update_yaxes(tickfont={"size": 16}, title_font={"size": 16})
    fig.update_annotations(font_size=16)
    fig.update_traces(textfont_size=16, selector={"type": "bar"})
    st.plotly_chart(fig, key=f"dchart-{f.key}", config={"displayModeBar": False}, alt=f.headline)


def deck_slides() -> list[str]:
    """The slide order: challenge, tool, title, findings, conclusion, options, team.

    The tool comes before the results: the findings show what it can do.
    """
    story = ov.findings[:-1]
    keys = [f.key for f in story]
    return ["challenge", "tool", "title", *keys, "conclusion", "options", "team"]


# The slide template: the LuxTrade Lens logo top left, the event top right, and a footer
# with the source and the slide number (also in the PDF, where the controls are not shown).
# Title slides are centred; on the others the title sits under the header, always in one place.
CENTRED = ("challenge", "tool", "title", "team")
EVENT = "STATEC Hackathon 2026"
REPO_URL = "https://github.com/mina-naseh/statec-hackathon-outliers"
LOGO_TEXT = "LuxTrade <span>Lens</span>"


def brand_css() -> str:
    """The logo's typeface and colours (navy on a light theme, the theme's text on a dark one)."""
    ink = "inherit" if st.context.theme.type == "dark" else "#13213C"
    font = "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,800"
    return f"""<style>
@import url("{font}&display=swap");
.lt-head {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding-bottom: 0.9rem; border-bottom: 1px solid rgba(19,33,60,.14); }}
.lt-logo {{ font-family: "Bricolage Grotesque", "Arial Black", sans-serif; font-weight: 800;
  font-size: 2.1rem; line-height: 1; letter-spacing: -0.035em; color: {ink}; }}
.lt-logo.lt-big {{ font-size: 6rem; margin-bottom: 1rem; }}
.lt-logo span {{ color: #0B7DB8; }}
.lt-event {{ background: #C62F35; color: #FFFFFF; font-size: 0.95rem; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase; padding: 0.4rem 0.95rem;
  border-radius: 999px; white-space: nowrap; }}
.lt-foot {{ display: flex; justify-content: space-between; gap: 1rem; padding-top: 0.7rem;
  border-top: 1px solid rgba(19,33,60,.14); font-size: 1rem; opacity: 0.7; }}
</style>"""


def render_slide(kind: str, number: int, total: int) -> None:
    """One slide in its own full-screen container: header, content, footer."""
    with st.container(key=f"deck-{kind}"):
        st.html(
            f'<div class="lt-head"><span class="lt-logo">{LOGO_TEXT}</span>'
            f'<span class="lt-event">{EVENT}</span></div>'
        )
        with st.container(key=f"dbody-{kind}"):
            slide_body(kind)
        st.html(
            '<div class="lt-foot"><span>The Outliers · Source: Eurostat Comext DS-045409</span>'
            f"<span>{number} / {total}</span></div>"
        )


def slide_body(kind: str) -> None:
    """One slide's content."""
    story, end = ov.findings[:-1], ov.findings[-1]
    if kind == "challenge":
        render_challenge(slide=True)
    elif kind == "tool":
        render_tool()
    elif kind == "title":
        st.markdown(f"#### :blue[:material/insights: {numbers_kicker(lang)}]")
        st.markdown(f"# {ov.findings_hero}")
        question = ov.findings_intro.split("**")[1] if "**" in ov.findings_intro else ""
        st.markdown(f"#### {question}")
        tiles = [f for f in story if f.metric_value]
        for col, f in zip(st.columns(len(tiles)), tiles, strict=True):
            with col, st.container(key=f"dtile-{f.key}", height="stretch"):
                st.metric(
                    f.metric_label,
                    f.metric_value,
                    f.metric_delta,
                    delta_color=f.delta_color,
                    delta_arrow=f.delta_arrow,
                )
    elif kind in {f.key for f in story}:
        i = [f.key for f in story].index(kind)
        f = story[i]
        if f.key in WIDE:  # two panels: text on top, the chart across the slide
            chapter_label(f"{i + 1} · ", f)
            st.markdown(f"## {f.headline}")
            deck_chart(f, height=480)
            st.caption(f.summary)
        else:
            text, chart = st.columns([2, 3], gap="large", vertical_alignment="center")
            with text:
                chapter_label(f"{i + 1} · ", f)
                st.markdown(f"## {f.headline}")
                st.markdown(f.title)
                if f.analysis:
                    st.markdown(f.analysis)
            with chart:
                deck_chart(f)
    elif kind == "conclusion":
        chapter_label("", end)
        st.markdown(f"## {end.headline}")
        st.markdown(end.summary)
        for col, (title, body), (tile_icon, chapter) in zip(
            st.columns(len(end.tiles)), end.tiles, WATCH, strict=False
        ):
            with col, st.container(key=f"dwatch-{chapter}", height="stretch"):
                st.markdown(f"#### {tile_icon} {title}")
                st.markdown(body)
    elif kind == "options":
        heading, _, rest = end.note.partition(":")
        chapter_label("", end)
        st.markdown(f"## {heading}")
        st.table(end.frames["main"], hide_index=True, alt=heading)
        note = rest.strip()
        st.caption(note[:1].upper() + note[1:])
    else:  # team: the closing slide
        st.html(f'<div class="lt-logo lt-big">{LOGO_TEXT}</div>')
        st.markdown("## Thank you. Questions?")
        st.markdown("\n".join(f"- **{name}**, {org}" for name, org in CONTRIBUTORS))
        st.markdown(f":material/code: [{REPO_URL.removeprefix('https://')}]({REPO_URL})")
        st.caption(POC_NOTE)


def start_print() -> None:
    """Callback: lay out every slide for the browser's print dialog."""
    ss.deck_print = True


def stop_print() -> None:
    """Callback: back to presenting one slide at a time."""
    ss.deck_print = False


# Printing the deck: one slide per landscape A4 page. The screen layout is scaled down
# (zoom) so a slide drawn for a wide screen fits a page; heights are in page millimetres
# divided by that zoom.
DECK_PRINT_ZOOM = 0.6


def deck_print_css(slides: list[str]) -> str:
    """Print rules: each slide fills one page; the controls are not printed."""
    deck = ", ".join(f".st-key-deck-{k}" for k in slides)
    page_mm = 210 / DECK_PRINT_ZOOM - 24  # one A4 landscape page, room for the gaps around
    return f"""<style>
@media print {{
  @page {{ size: A4 landscape; margin: 0; }}
  [data-testid="stMainBlockContainer"] {{
    zoom: {DECK_PRINT_ZOOM} !important; padding: 0 !important; }}
  .st-key-deckprintbar {{ display: none !important; }}
  :is({deck}) {{ min-height: {page_mm:.0f}mm !important; height: {page_mm:.0f}mm !important;
    overflow: hidden; box-sizing: border-box;
    margin: 0 !important; border-radius: 0 !important; break-inside: avoid; }}
  :is({deck}):not(.st-key-deck-{slides[0]}) {{ break-before: page; page-break-before: always; }}
}}
@media screen {{
  :is({deck}) {{ margin-bottom: 1.5rem; }}
}}
</style>"""


# Full screen is a browser button, not a Streamlit one: browsers allow it only from a click
# (or key press) in the page itself, never from a script run after a rerun. One listener on the
# page handles the button's clicks and the F key (inline onclick is stripped by st.html); the
# label follows the state. Looks like the Streamlit buttons beside it.
FULL_SCREEN = """<button type="button" class="lt-fs" title="Full screen (F)">
<span class="lt-fs-label">Full screen</span></button>
<style>
.lt-fs { display: inline-flex; align-items: center; gap: 0.5rem; height: 2.5rem;
  padding: 0 0.75rem; border-radius: 0.5rem; border: 1px solid rgba(49,51,63,.2);
  background: transparent; color: inherit; font: inherit; font-size: 0.875rem; cursor: pointer; }
.lt-fs:hover { border-color: #ff4b4b; color: #ff4b4b; }
.lt-fs::before { content: ""; width: 18px; height: 18px; background: currentColor;
  -webkit-mask: ICON; mask: ICON; }
.st-key-decknav [data-testid="stElementContainer"]:has(.lt-fs),
.st-key-decknav [data-testid="stHtml"]:has(.lt-fs) { flex: 0 0 auto !important; width: auto; }
</style>
<script>
(function () {
  const label = () => document.querySelectorAll(".lt-fs-label").forEach((el) => {
    el.textContent = document.fullscreenElement ? "Exit full screen" : "Full screen"; });
  label();
  if (window.ltFullScreenKeys) return;  // once per page, however often the slide redraws
  window.ltFullScreenKeys = true;
  const toggle = () => document.fullscreenElement ? document.exitFullscreen()
                                                  : document.documentElement.requestFullscreen();
  document.addEventListener("fullscreenchange", label);
  document.addEventListener("click", (e) => { if (e.target.closest(".lt-fs")) toggle(); });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey
        && !e.target.closest("input, textarea, [contenteditable]")
        && document.querySelector(".st-key-decknav")) toggle();
  });
})();
</script>"""
FULL_SCREEN_ICON = (  # the 'expand' corners, drawn in the text colour through a CSS mask
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
    "fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Cpath "
    "d='M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5'/%3E%3C/svg%3E\") center / contain no-repeat"
)
FULL_SCREEN = FULL_SCREEN.replace("ICON", FULL_SCREEN_ICON)
# leaving the slides also leaves full screen (allowed without a click)
EXIT_FULL_SCREEN = "<script>if (document.fullscreenElement) document.exitFullscreen();</script>"


def present() -> None:
    """Show one slide and the controls: Back, Next, Close (also ←, →, Page Up/Down, Esc).

    'Full screen' (or F) fills the screen; 'Save as PDF' lays out all slides, one per page,
    and opens the browser's print dialog.
    """
    slides = deck_slides()
    last = len(slides) - 1
    n = min(ss.get("deck_slide", 0), last)
    st.html(deck_css(slides))
    st.html(brand_css())
    if ss.get("deck_print"):
        st.html(deck_print_css(slides))
        with st.container(horizontal=True, vertical_alignment="center", key="deckprintbar"):
            st.button(
                "Back to slides",
                icon=":material/arrow_back:",
                on_click=stop_print,
                key="deck-print-back",
            )
            st.caption(
                "All slides are below, one per page. In the print dialog choose **Save as "
                "PDF**, landscape, with **background graphics** on. Use Ctrl+P to open it again."
            )
        for i, kind in enumerate(slides, start=1):
            render_slide(kind, i, len(slides))
        # open the print dialog once the charts have been drawn
        st.html(
            "<script>setTimeout(() => window.print(), 3000);</script>",
            unsafe_allow_javascript=True,
        )
        return
    render_slide(slides[n], n + 1, len(slides))
    # controls; the buttons also answer the arrow keys, Page Up/Down (clickers) and Esc
    with st.container(horizontal=True, vertical_alignment="center", key="decknav"):
        st.button(
            "Back",
            icon=":material/arrow_back:",
            on_click=move,
            args=(-1, last),
            disabled=n == 0,
            shortcut="Left",
            key="deck-back",
        )
        st.markdown(f"**{n + 1}** / {len(slides)}")
        st.button(
            "Next",
            icon=":material/arrow_forward:",
            on_click=move,
            args=(1, last),
            disabled=n == last,
            shortcut="Right",
            key="deck-next",
        )
        st.space("stretch")
        st.html(FULL_SCREEN, unsafe_allow_javascript=True)
        st.button(
            "Save as PDF",
            icon=":material/picture_as_pdf:",
            on_click=start_print,
            help="All slides, one per page, through the browser's print dialog",
            key="deck-pdf",
        )
        st.button(
            "Close",
            icon=":material/close:",
            on_click=stop_presentation,
            shortcut="Esc",
            key="deck-close",
        )
    with st.container(key="deckkeys"):  # hidden: the keys a presentation clicker sends
        st.button("Next page", on_click=move, args=(1, last), shortcut="PageDown", key="pg-next")
        st.button("Previous page", on_click=move, args=(-1, last), shortcut="PageUp", key="pg-back")


if ss.get("deck_on"):
    present()
    st.stop()
st.html(EXIT_FULL_SCREEN, unsafe_allow_javascript=True)


st.title("Luxembourg's trade in goods at a glance")
# the start button sits on the right of the tab row (pulled down onto it by the style below)
with st.container(horizontal=True, key="present-start"):
    st.space("stretch")
    st.button(
        "Presentation mode",
        icon=":material/slideshow:",
        on_click=start_presentation,
        key="present-btn",  # not the state's name: a button's key holds its own value
        help="Show the key findings as full-screen slides (Back, Next, Close; arrow keys)",
    )
challenge_tab, findings_tab, glance_tab = st.tabs(
    ["The challenge", "Key findings", "More evidence"], default="Key findings"
)

# --- the challenge: the problem the page answers -------------------------------------------------
with challenge_tab:
    render_challenge()

# --- key findings: the story for decision-makers, ready to present or print ---------------------
with findings_tab:
    story, end = ov.findings[:-1], ov.findings[-1]
    st.markdown(f"## {ov.findings_hero}")
    st.markdown(ov.findings_intro)
    # the story in four numbers: equal tiles, each in its chapter's tint
    tiles = [f for f in story if f.metric_value]
    for col, f in zip(st.columns(len(tiles)), tiles, strict=True):
        with col, st.container(border=True, key=f"tile-{f.key}", height="stretch"):
            st.metric(
                f.metric_label,
                f.metric_value,
                f.metric_delta,
                delta_color=f.delta_color,
                delta_arrow=f.delta_arrow,
                help=f.title,
            )
    # one chapter per finding: headline, evidence, why it matters and its chart, alternating
    for i, f in enumerate(story, start=1):
        if f.key in WIDE:  # two panels need the card's full width: text on top, chart below
            with st.container(border=True, key=f"card-{f.key}"):
                text, why = st.columns([1, 1], gap="large")
                with text:
                    chapter_label(f"{i} · ", f)
                    st.markdown(f"### {f.headline}")
                    st.markdown(f.title)
                with why:
                    if f.analysis:
                        st.markdown(f.analysis)
                    more_button(f)
                fig = hero_figure(f.key, f.frames, lang)
                if fig is not None:
                    st.plotly_chart(fig, key=f"hero-{f.key}", config=hero_config, alt=f.headline)
                st.caption(f.summary)
            continue
        with st.container(border=True, key=f"card-{f.key}"):
            if i % 2:
                text, chart = st.columns([1, 1], gap="large", vertical_alignment="center")
            else:
                chart, text = st.columns([1, 1], gap="large", vertical_alignment="center")
            with text:
                chapter_label(f"{i} · ", f)
                st.markdown(f"### {f.headline}")
                st.markdown(f.title)
                if f.analysis:
                    st.markdown(f.analysis)
                more_button(f)
            with chart:
                fig = hero_figure(f.key, f.frames, lang)
                if fig is not None:
                    st.plotly_chart(fig, key=f"hero-{f.key}", config=hero_config, alt=f.headline)
    # the conclusion: three things to watch, each in the tint of its chapter
    with st.container(border=True, key=f"card-{end.key}"):
        chapter_label("", end)
        st.markdown(f"### {end.headline}")
        st.markdown(end.summary)
        if end.tiles:
            for col, (title, body), (tile_icon, chapter) in zip(
                st.columns(len(end.tiles)), end.tiles, WATCH, strict=False
            ):
                with col, st.container(border=True, key=f"watch-{chapter}", height="stretch"):
                    st.markdown(f"**{tile_icon} {title}**")
                    st.markdown(body)
        more_button(end)

# --- at a glance: five business questions ------------------------------------------------------
with glance_tab:
    for i, p in enumerate(ov.panels, start=1):
        figs = overview_figures(p.key, p.frames, p.chart_titles, lang)
        with st.container(border=True):
            source = BRIEF.get(p.key)
            st.caption(f"Hackathon brief · {source}" if source else "Our own question")
            st.subheader(f"{i}. {p.question}")
            st.markdown(f"##### {p.takeaway}")
            left, right = st.columns([2, 3], gap="large")
            with left:
                st.markdown("\n".join(f"- {fact}" for fact in p.facts))
                for lim in p.limits:
                    st.caption(f":material/info: {lim}")
                explore_button(p.key, p.explore_question, p.explore_spec)
            if figs:
                with right:
                    st.plotly_chart(
                        figs[0], key=f"ov-{p.key}-0", config=chart_config, alt=p.chart_titles[0]
                    )
            rest = figs[1:]
            if rest:
                cols = st.columns(len(rest))
                for j, (col, fig) in enumerate(zip(cols, rest, strict=True), start=1):
                    with col:
                        st.plotly_chart(fig, key=f"ov-{p.key}-{j}", config=chart_config)
            evidence(p.key, p.sql, p.frames["main"], p.methods)

# --- next step (not printed) -----------------------------------------------------------------
with st.container(horizontal=True, vertical_alignment="center", key="next-step"):
    st.markdown("**Have a more specific question?** Ask it in your own words.")
    if st.button("Ask the assistant", icon=":material/forum:", type="primary"):
        st.switch_page(ASK_PAGE)
