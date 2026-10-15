"""Overview: Luxembourg's trade in goods at a glance, the landing page (SOLUTION_DESIGN §8a).

Two tabs. **Key findings** tells the story for decision-makers, ready to present: one line, the
story in four numbers, a chapter per finding (headline, evidence, chart) and three things to
watch; "To know more" opens a finding's charts, queries and method in a dialog. **At a
glance** answers five business questions from the data. The data description, how to use the
app and what the data can't tell sit in a closed section at the end. Each finding and question
opens in the assistant for details.
UI only: the content comes from ``Assistant.overview`` (agents/overview.py, agents/findings.py).
"""

import pandas as pd
import streamlit as st

from luxtrade.agents.findings import Finding
from luxtrade.app.components import ASK_PAGE, get_assistant, load_overview, queue
from luxtrade.config import ATTRIBUTION
from luxtrade.viz.charts import finding_figures, hero_figure, overview_figures

assistant = get_assistant()
cov = assistant.sem.coverage
lang = st.session_state.get("lang") or "en"
ov = load_overview(lang, cov.vintage)
about = ov.about
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


def finding_detail(f: Finding) -> None:
    """Body of the 'To know more' dialog: facts, charts, caveats and evidence."""
    st.markdown(f"### {f.headline}")
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


def more_button(f: Finding, primary: bool = False) -> None:
    """'To know more': the finding's charts, queries and method in a dialog."""
    if st.button(
        "To know more",
        key=f"more-{f.key}",
        icon=":material/open_in_full:",
        type="primary" if primary else "secondary",
    ):
        st.dialog(f.name, width="large")(finding_detail)(f)


# icon and badge colour of each chapter; the conclusion's three things to watch
CHAPTER = {
    "diversification": (":material/category:", "blue"),
    "shocks": (":material/bolt:", "red"),
    "europe": (":material/public:", "violet"),
    "prices": (":material/scale:", "orange"),
    "conclusion": (":material/flag:", "gray"),
}
WATCH_ICONS = (":material/factory:", ":material/local_shipping:", ":material/local_gas_station:")

st.title("Luxembourg's trade in goods at a glance")
findings_tab, glance_tab = st.tabs(["Key findings", "At a glance"])

# --- key findings: the story for decision-makers, ready to present ------------------------------
with findings_tab:
    story, end = ov.findings[:-1], ov.findings[-1]
    st.markdown(f"## {ov.findings_hero}")
    st.markdown(ov.findings_intro)
    # the story in four numbers
    with st.container(horizontal=True):
        for f in story:
            st.metric(
                f.metric_label,
                f.metric_value,
                f.metric_delta,
                delta_color=f.delta_color,
                delta_arrow=f.delta_arrow,
                help=f.title,
                border=True,
                height="stretch",
            )
    # one chapter per finding: headline, evidence and its chart, alternating sides
    for i, f in enumerate(story, start=1):
        icon, color = CHAPTER[f.key]
        with st.container(border=True):
            if i % 2:
                text, chart = st.columns([5, 6], gap="large", vertical_alignment="center")
            else:
                chart, text = st.columns([6, 5], gap="large", vertical_alignment="center")
            with text:
                st.badge(f"{i} · {f.name}", icon=icon, color=color)
                st.markdown(f"### {f.headline}")
                st.markdown(f.title)
                more_button(f)
            with chart:
                fig = hero_figure(f.key, f.frames, lang)
                if fig is not None:
                    st.plotly_chart(fig, key=f"hero-{f.key}", config=hero_config, alt=f.headline)
    # the conclusion: three things to watch
    icon, color = CHAPTER["conclusion"]
    with st.container(border=True):
        st.badge(end.name, icon=icon, color=color)
        st.markdown(f"### {end.headline}")
        st.markdown(end.summary)
        if end.tiles:
            for col, (title, body), tile_icon in zip(
                st.columns(len(end.tiles)), end.tiles, WATCH_ICONS, strict=False
            ):
                with col, st.container(border=True, height="stretch"):
                    st.markdown(f"**{tile_icon} {title}**")
                    st.markdown(body)
        more_button(end, primary=True)

# --- at a glance: five business questions ------------------------------------------------------
with glance_tab:
    for i, p in enumerate(ov.panels, start=1):
        figs = overview_figures(p.key, p.frames, p.chart_titles, lang)
        with st.container(border=True):
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

# --- context, on demand: the data, how to use the app, what the data can't tell ------------
with st.expander(
    "About the data, how to use this app and what the data can't tell you",
    icon=":material/info:",
):
    st.caption(
        f"Eurostat Comext {about['dataset']} · {ov.year} unless stated. Every number on this "
        "page is computed from the data by fixed rules, and the query behind each section is "
        "under **Evidence**. No AI writes these texts."
    )
    # columns, not a horizontal container: three across on desktop, fully stacked on a phone
    data_col, use_col, limits_col = st.columns(3)
    with data_col, st.container(border=True, height="stretch"):
        st.markdown("**:material/database: The data**")
        st.markdown(
            f"- **{about['dataset']}** (Eurostat Comext): Luxembourg's declared trade in goods\n"
            f"- Monthly, {about['first_period']:%b %Y} → "
            f"{about['latest_complete_period']:%b %Y} complete ({about['months']} months)\n"
            f"- {about['partners']} partner countries × {about['products']:,} CN8 products × "
            "exports and imports\n"
            f"- {about['records']:,} records · extracted {about['extraction_date']}"
        )
    with use_col, st.container(border=True, height="stretch"):
        st.markdown("**:material/route: How to use this app**")
        st.markdown(
            "1. **Start here** with the key findings, or the big picture in five questions.\n"
            "2. **To know more** opens a finding's charts and evidence; **Explore** opens the "
            "same question in the assistant, with filters, tables and a full trace.\n"
            "3. **Ask** your own question in English, French or German."
        )
    with limits_col, st.container(border=True, height="stretch"):
        st.markdown("**:material/block: What the data can't tell you**")
        st.markdown("\n".join(f"- {m}" for m in ov.limits))

# --- next step and provenance ---------------------------------------------------------------
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown("**Have a more specific question?** Ask it in your own words.")
    if st.button("Ask the assistant", icon=":material/forum:", type="primary"):
        st.switch_page(ASK_PAGE)
st.caption(ATTRIBUTION.format(date=about["extraction_date"]))
with st.expander("How the dataset summary was computed"):
    st.code(about["sql"], language="sql")
