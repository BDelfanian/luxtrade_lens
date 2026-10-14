"""Overview: Luxembourg's trade in goods at a glance, the landing page (SOLUTION_DESIGN §8a).

The big picture first: headline figures, five business questions answered from the data, and
what the data can't tell. Each section opens the same question in the assistant for details.
UI only: the content comes from ``Assistant.overview`` (agents/overview.py).
"""

import streamlit as st

from luxtrade.app.components import ASK_PAGE, get_assistant, load_overview, queue
from luxtrade.config import ATTRIBUTION
from luxtrade.viz.charts import overview_figures

assistant = get_assistant()
cov = assistant.sem.coverage
lang = st.session_state.get("lang") or "en"
ov = load_overview(lang, cov.vintage)
about = ov.about
chart_config = {"displaylogo": False}

st.title("Luxembourg's trade in goods at a glance")
st.caption(
    f"Eurostat Comext {about['dataset']} · {ov.year} unless stated. Every number on this page is "
    "computed from the data by fixed rules, and the query behind each section is under "
    "**Evidence**. No AI writes these texts."
)
# --- headline figures -----------------------------------------------------------------------
with st.container(horizontal=True):
    for k in ov.kpis:
        st.metric(
            k.label,
            k.value,
            k.delta,
            delta_color=k.delta_color,
            help=k.help,
            border=True,
            height="stretch",
            chart_data=k.spark or None,
        )

# --- context: the data, how to use the app, what the data can't tell ------------------------
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
        "1. **Start here** for the big picture: five questions, answered from the data.\n"
        "2. **Explore** a section to open the same question in the assistant, with "
        "filters, tables and a full trace.\n"
        "3. **Ask** your own question in English, French or German."
    )
with limits_col, st.container(border=True, height="stretch"):
    st.markdown("**:material/block: What the data can't tell you**")
    st.markdown("\n".join(f"- {m}" for m in ov.limits))

# --- five business questions ----------------------------------------------------------------
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
            if st.button(
                "Explore in the assistant",
                key=f"explore-{p.key}",
                icon=":material/arrow_forward:",
                help=p.explore_question,
            ):
                queue(
                    "spec",
                    spec=p.explore_spec.model_dump(),
                    question=p.explore_question,
                    origin="overview",
                )
                st.switch_page(ASK_PAGE)
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
        with st.expander("Evidence: queries, data and method", icon=":material/fact_check:"):
            for n, sql in enumerate(p.sql, start=1):
                st.caption(f"Query {n} of {len(p.sql)} (checked by the SQL guard)")
                st.code(sql, language="sql")
            main = p.frames["main"]
            st.dataframe(main, hide_index=True, width="stretch")
            st.download_button(
                "Download CSV",
                main.to_csv(index=False).encode("utf-8"),
                file_name=f"luxtrade_overview_{p.key}_{ov.year}.csv",
                mime="text/csv",
                key=f"csv-ov-{p.key}",
            )
            st.markdown("**Method**\n" + "\n".join(f"- {m}" for m in p.methods))

# --- next step and provenance ---------------------------------------------------------------
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown("**Have a more specific question?** Ask it in your own words.")
    if st.button("Ask the assistant", icon=":material/forum:", type="primary"):
        st.switch_page(ASK_PAGE)
st.caption(ATTRIBUTION.format(date=about["extraction_date"]))
with st.expander("How the dataset summary was computed"):
    st.code(about["sql"], language="sql")
