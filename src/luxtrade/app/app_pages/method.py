"""How it works: from a question to a checked answer, and the project behind the app.

Reference page, opened from the top bar: the processing pipeline, how SQL is built and
verified, how the chart is chosen, how the explanations are written, and the team.
UI only (GUIDELINES §1.1).
"""

import json

import pandas as pd
import streamlit as st

from luxtrade.agents.analyse import analyse
from luxtrade.agents.compile_sql import compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.presets import preset
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql
from luxtrade.app.components import CONTRIBUTORS, POC_NOTE, get_assistant
from luxtrade.config import (
    LLM_DEFAULT_MODELS,
    LLM_DEFAULT_PROVIDER,
    LLM_TIMEOUT_S,
    MAX_RETRIES,
    SQL_ROW_LIMIT,
    SQL_TIMEOUT_S,
)
from luxtrade.viz.charts import build_figures
from luxtrade.viz.format import fmt_eur, fmt_pct
from luxtrade.viz.selector import MAP_MAX_UNDISCLOSED_PCT, MAP_MIN_COUNTRIES, choose_view


@st.cache_data(show_spinner=False, max_entries=8)
def chart_example(preset_id: str, vintage: str) -> dict:
    """Run a preset exactly as the assistant does, up to the chart choice (no LLM involved)."""
    question, spec = preset(preset_id).for_language("en")
    sem = get_assistant().sem
    resolved = apply_defaults(spec, sem.coverage)
    compiled = compile_spec(resolved)
    a = analyse(resolved, sem.query(check_sql(compiled.sql)), sem)
    special_pct = 0.0
    if compiled.stats_sql:
        row = sem.query(check_sql(compiled.stats_sql)).fillna(0.0).iloc[0]
        special_pct = 100 * row["special"] / row["total"] if row["total"] else 0.0
    iso3 = int(a.main["iso3"].notna().sum()) if "iso3" in a.main.columns else 0
    kind = choose_view(resolved, a.main, iso3_count=iso3, undisclosed_pct=special_pct)
    return {
        "question": question,
        "spec": resolved,
        "main": a.main,
        "rows": len(a.main),
        "iso3": iso3,
        "special_pct": special_pct,
        "kind": kind,
    }


def result_shape(ex: dict) -> str:
    """What the query returned, in words."""
    m = ex["main"]
    if "kind" in m.columns:
        items = int((m["kind"] == "item").sum())
        return (
            f"{items} ranked rows (top {ex['spec'].top_n} for exports, imports and total), "
            "plus Other and Confidential"
        )
    if "period" in m.columns:
        return f"{m['period'].nunique()} months, {m['flow'].nunique()} flow"
    return f"{ex['rows']} rows"


def rule_fired(ex: dict) -> str:
    """The selector rule that picked this chart, in words, with the numbers it used."""
    spec, kind = ex["spec"], ex["kind"]
    if kind == "map":
        return (
            f"Ranking by partner with {ex['iso3']} ranked rows carrying a country code (at "
            f"least {MAP_MIN_COUNTRIES}) and "
            f"{ex['special_pct']:.1f} % undisclosed (below {MAP_MAX_UNDISCLOSED_PCT:g} %) "
            "→ map + ranked bars"
        )
    if kind == "bar" and spec.breakdown == "product":
        return "Ranking by product → sorted bars (a treemap is kept for compositions)"
    if kind == "season":
        return "Intent is seasonality → raw vs seasonally adjusted line + month × year heatmap"
    if kind == "treemap":
        return "Drill-down by product → treemap with Top-N + Other + Confidential"
    if kind == "change":
        return "Ranking by change between two years → diverging bars, rises in blue, falls in red"
    if kind == "stacked":
        return (
            "Shares over a few years → one stacked bar per year (stacked areas for longer series)"
        )
    return f"Intent {spec.intent} → {kind}"


REPO_URL = "https://github.com/BDelfanian/luxtrade_lens"

st.title("How it works")
st.markdown(
    "**LLMs translate, code computes.** A language model turns your question into a "
    "structured request and words the final paragraph. Every number is computed by SQL or "
    "tested Python, and every step is recorded so the answer can be checked and reproduced."
)

# --- the pipeline --------------------------------------------------------------------------------
st.subheader(":material/account_tree: From a question to an answer", anchor=False)
st.graphviz_chart(
    """digraph {
    rankdir=LR; bgcolor="transparent";
    node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11,
          color="#c9c8c2", fillcolor="#ffffff"];
    edge [color="#8a8984", arrowsize=0.7];
    q [label="Question\\n(EN, FR, DE)", fillcolor="#eef4ff"];
    i [label="1 Interpret\\nLLM → QuerySpec", fillcolor="#fff3e0"];
    g [label="2 Limitation guard\\nrules"];
    s [label="3 Query builder\\nspec → SQL"];
    sg [label="SQL guard\\nread-only checks"];
    a [label="4 Analytics\\nPython"];
    v [label="5 Visualise\\nrules"];
    w [label="6 Insight\\nLLM + grounding check", fillcolor="#fff3e0"];
    r [label="Run record\\nrun ID, SQL, hash", fillcolor="#eef4ff"];
    o [label="Optimiser\\n3 checked rewrites", fillcolor="#fff3e0"];
    q -> i -> g -> s -> sg -> a -> v -> w -> r;
    g -> o [label=" blocked or vague", fontsize=9, fontcolor="#8a8984"];
    }""",
    width="stretch",
)
st.caption("Orange steps use a language model; all other steps are deterministic code.")
llm_use = pd.DataFrame(
    [
        ("Interpret", "Always", "Turns the question and its session context into a QuerySpec"),
        ("Insight", "Always", "Writes 4–5 sentences from a fact sheet computed by code"),
        ("Optimise", "Vague, blocked or failed questions", "Proposes three rewrites"),
        ("SQL fallback", "Questions the spec can't express", "Writes SQL, then guarded"),
        ("Scenario plan", "Scenario builder", "Proposes 3–5 questions, each checked by code"),
        ("Scenario follow-up", "Scenario builder", "Proposes 0–2 questions from the answers"),
        ("Scenario answer", "Scenario builder", "Combines the steps' facts, checked by code"),
        ("Scenario review", "Scenario builder", "Judges whether each claim follows; adds no text"),
    ],
    columns=["LLM step", "When", "What it does"],
)
st.table(llm_use, hide_index=True, alt="Where a language model is used")

# --- language models -----------------------------------------------------------------------------
st.subheader(":material/smart_toy: Language models used", anchor=False)
llm = get_assistant().llm
in_use = (
    f"**In use now:** `{llm.model}` ({type(llm).__name__.removesuffix('LLM')})."
    if llm is not None
    else "**In use now:** none. The app runs offline: Overview, presets and stored answers only."
)
st.markdown(in_use)
models = pd.DataFrame(
    [
        (
            "Model",
            LLM_DEFAULT_MODELS["openai"],
            LLM_DEFAULT_MODELS["anthropic"],
        ),
        (
            "Selected by",
            f"LUXTRADE_LLM_PROVIDER = openai (default: {LLM_DEFAULT_PROVIDER})",
            "LUXTRADE_LLM_PROVIDER = anthropic",
        ),
        ("Other model", "LUXTRADE_LLM_MODEL", "LUXTRADE_LLM_MODEL"),
        (
            "Output",
            "Strict JSON schema, validated by Pydantic models",
            "Structured output, parsed into the same Pydantic models",
        ),
        (
            "Randomness",
            "Temperature 0",
            "Adaptive thinking, low or medium effort per step",
        ),
        (
            "Time limit and retries",
            f"{LLM_TIMEOUT_S:g} s per call, 2 retries",
            f"{LLM_TIMEOUT_S:g} s per call, 2 retries",
        ),
    ],
    columns=["Setting", "OpenAI (default)", "Anthropic (alternative)"],
)
st.table(models, hide_index=True, alt="Language model settings")
st.markdown(
    "**Never done by a language model:** computing a number, writing the SQL of a known "
    "question type, checking limitations, choosing the chart, or writing the Overview texts. "
    "Every model call, with its step and model, is recorded in the answer's trace."
)

# --- SQL -----------------------------------------------------------------------------------------
st.subheader(":material/database: How SQL is created and verified", anchor=False)
st.markdown(
    "**No NL2SQL package, and for known question types no SQL written by a language "
    "model.** The model only fills in a form: a structured request called a *QuerySpec* "
    "(intent, partners, products, period, flow…), returned as JSON. Our own Python "
    "compiler then turns that form into SQL with fixed, tested templates. Only a question "
    "the form can't express goes to the model to write SQL itself, and that SQL passes the "
    "same checks."
)
who = pd.DataFrame(
    [
        ("1. Understand the question", "Language model", "A QuerySpec (JSON form)"),
        ("2. Fill what was left open", "Python rules (defaults.py)", "A complete spec + 'Assumed'"),
        ("3. Write the SQL", "Python compiler (compile_sql.py), fixed templates", "One SELECT"),
        ("3b. Rare fallback", "Language model, from the table catalogue", "One SELECT"),
        ("4. Check the SQL", "SQL guard: sqlglot parser + rules", "Accepted, with a LIMIT"),
        ("5. Run it", "DuckDB, read-only", "The result table"),
    ],
    columns=["Step", "Done by", "Output"],
)
st.table(who, hide_index=True, alt="Who creates and checks the SQL")
st.caption("sqlglot is a SQL parser: it is used only to read and check SQL, never to write it.")

# A real example: the question and the model's form were recorded on 15 Oct 2026; the SQL and
# the rows below are produced live by the same code the assistant uses.
EXAMPLE_QUESTION = "Quels produits le Luxembourg a-t-il importés de Chine en 2024 ?"
EXAMPLE_SPEC = {
    "language": "fr",
    "intent": "ranking",
    "breakdown": "product",
    "partners": ["CN"],
    "period_start": "2024",
    "period_end": "2024",
    "flow": "import",
}
sem = get_assistant().sem
resolved = apply_defaults(QuerySpec(**EXAMPLE_SPEC), sem.coverage)
example_sql = check_sql(compile_spec(resolved).sql)

st.markdown("##### A real example, step by step")
step1, step2 = st.columns(2, gap="large")
with step1, st.container(border=True, height="stretch"):
    st.markdown("**1. The question**, typed in French")
    st.markdown(f"> *{EXAMPLE_QUESTION}*")
    st.markdown("**The model's answer**: a form, not SQL")
    st.code(json.dumps(EXAMPLE_SPEC, indent=2, ensure_ascii=False), language="json")
    st.caption(
        "Chine was matched to the code CN by the label search; the model may use no other "
        "code. Fields the question did not mention stay empty."
    )
with step2, st.container(border=True, height="stretch"):
    st.markdown("**2. Defaults** fill the gaps, shown on the answer as *Assumed*:")
    st.markdown(
        f"product level **{resolved.product_level}**, top **{resolved.top_n}**, "
        f"annual totals · *{'; '.join(resolved.assumptions) or 'none'}*"
    )
    st.markdown("**3. The compiler writes the SQL**, and **4. the guard checks it**:")
    st.code(example_sql, language="sql")
    st.caption(
        "One SELECT, only an allowed view, no file access; the guard added the LIMIT. "
        "Values are summed in SQL, not by the model."
    )

rows = sem.query(example_sql).head(5)
total = sem.query(example_sql)["value_eur"].sum()
result = pd.DataFrame(
    {
        "HS2 chapter": rows["key"],
        "Product": [sem.label(code, "product", "en") for code in rows["key"]],
        "Imports from China, 2024": [fmt_eur(v) for v in rows["value_eur"]],
        "Share": [fmt_pct(100 * v / total) for v in rows["value_eur"]],
    }
)
st.markdown("**5. The result** (first five rows), then the chart and the checked paragraph:")
st.table(result, hide_index=True, alt="Result of the example query")
st.markdown(
    "**When the form is not enough.** A question such as *months in which imports from "
    "China exceeded exports to France* has no template. The model then writes the SQL from "
    "the table catalogue and worked examples; the same guard checks it, a failing query goes "
    f"back to the model (at most {MAX_RETRIES} retries), and the run record flags it as "
    "custom SQL."
)

st.markdown("##### How the answer is verified")
st.markdown(
    "- **SQL guard** on every query, compiled or generated: exactly one SELECT, only the "
    "whitelisted views, no file access, table functions or settings; a forced LIMIT of "
    f"{SQL_ROW_LIMIT:,} rows.\n"
    f"- **Database** opened read-only, external access disabled, {SQL_TIMEOUT_S:g}-second "
    "timeout.\n"
    "- **Shown:** the exact SQL is under *How we got this* / *Evidence*, ready to copy.\n"
    "- **Reproducible:** each answer stores its SQL and a SHA-256 hash of its result, so "
    "re-running the SQL on the same data proves the same numbers.\n"
    "- **Checked independently:** the preset answers were recomputed from the raw files "
    "with separate code; every table and number matched."
)

# --- data products -------------------------------------------------------------------------------
st.subheader(":material/bar_chart: How the chart type is chosen", anchor=False)
st.markdown(
    "Rules, not a model, pick the data product from the question's intent and the result's "
    "shape. A chart the user asks for wins when it fits the data; every answer also has a "
    "table and a CSV download."
)
views = pd.DataFrame(
    [
        ("One number", "KPI tile with change on the year"),
        ("Ranking of partners, 5+ countries", "Choropleth map + ranked bars"),
        ("Ranking of products or a split", "Sorted bar chart"),
        ("Composition or drill-down by product", "Treemap, with Top-N + Other + Confidential"),
        ("Values over time", "Line chart (stacked area for shares)"),
        ("Two dimensions × value", "Pivot table with heat colouring"),
        ("Seasonality", "Raw vs seasonally adjusted line + month × year heatmap"),
        ("Projection", "History, dashed projection and an uncertainty band"),
        ("Comparison with EU countries", "Indexed lines (2015 = 100)"),
    ],
    columns=["Question / result", "Data product"],
)
st.table(views, hide_index=True, alt="Chart type rules")
st.markdown("##### Real examples")
st.caption(
    "Three preset questions, run live through the same compiler, analysis and selector as "
    "the assistant."
)
CHART_EXAMPLES = {"Partners → map": "Q1", "Products → bars": "Q2", "Seasonality": "Q6"}
for tab, pid in zip(st.tabs(list(CHART_EXAMPLES)), CHART_EXAMPLES.values(), strict=True):
    with tab:
        ex = chart_example(pid, get_assistant().sem.coverage.vintage)
        spec = ex["spec"]
        left, right = st.columns([2, 3], gap="large")
        with left:
            st.markdown(f"> *{ex['question']}*")
            trace = pd.DataFrame(
                [
                    ("Intent", spec.intent),
                    ("Broken down by", spec.breakdown),
                    ("Period, flow", f"{spec.period_start} – {spec.period_end}, {spec.flow}"),
                    ("Result", result_shape(ex)),
                    ("Rule that fires", rule_fired(ex)),
                    ("Data product", ex["kind"]),
                ],
                columns=["Input", "Value"],
            )
            st.table(trace, hide_index=True, alt=f"Chart choice for {pid}")
        with right:
            figs = build_figures(
                ex["kind"],
                ex["main"],
                ex["question"],
                measure=spec.measure,
                monthly=spec.freq == "M",
            )
            if figs:
                st.plotly_chart(figs[0], key=f"chart-example-{pid}", config={"displaylogo": False})
st.caption(
    "The Dashboard page works the other way round: you write a guarded SQL query and map "
    "its columns to a line, bar, area, pie or bar-race chart."
)

# --- explanations --------------------------------------------------------------------------------
st.subheader(":material/edit_note: How the explanations are written", anchor=False)
left, right = st.columns(2, gap="large")
with left, st.container(border=True, height="stretch"):
    st.markdown("**Overview: fixed templates, no LLM**")
    st.markdown(
        "Every sentence on the Overview is a template in EN, FR and DE, filled with numbers "
        "from SQL shown under *Evidence*. A headline appears only when the data supports "
        "it; otherwise a neutral question replaces it."
    )
with right, st.container(border=True, height="stretch"):
    st.markdown("**Assistant: LLM, then a grounding check**")
    st.markdown(
        "The model sees a fact sheet computed by code, never the raw table, with rules: "
        "copy numbers exactly, name the flow of every ranking, no causal claims. Code then "
        "checks that every number and every country in the text is in the facts. If not, "
        "the model rewrites once, then a fixed template is used instead."
    )
st.markdown(
    "**Limits and follow-ups.** Questions outside the data (services, GDP, causes, other "
    "countries' detail) are refused with the reason and three answerable alternatives. "
    "Follow-ups inherit the previous question's fields, shown on the answer so you can "
    "start fresh. Each answer has a **run ID** and each conversation a **session ID** that "
    "can be reopened from a link."
)

# --- scenarios -----------------------------------------------------------------------------------
st.subheader(":material/route: Scenario builder: a broad question, step by step", anchor=False)
st.graphviz_chart(
    """digraph {
    rankdir=LR; bgcolor="transparent";
    node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11,
          color="#c9c8c2", fillcolor="#ffffff"];
    edge [color="#8a8984", arrowsize=0.7];
    q [label="Broad question", fillcolor="#eef4ff"];
    p [label="1 Plan\\nLLM: 3–5 questions", fillcolor="#fff3e0"];
    c [label="Checks\\ncodes, limits, SQL,\\nyears match"];
    u [label="2 Review\\nyou edit the chain", fillcolor="#eef4ff"];
    r [label="3 Run each step\\nthe assistant above"];
    f [label="4 Follow up\\nLLM: 0–2 questions\\nfrom the facts", fillcolor="#fff3e0"];
    a [label="5 Answer\\nLLM + per-step\\nnumber check", fillcolor="#fff3e0"];
    s [label="Scenario record\\nsteps' run IDs", fillcolor="#eef4ff"];
    q -> p -> c -> u -> r -> f -> a -> s;
    f -> c [style=dashed];
    }""",
    width="stretch",
)
st.markdown(
    "Some questions need several answers. The scenario builder proposes a chain of precise "
    "questions; code keeps only those it can answer from the data. You review the chain, the "
    "assistant answers every step as an ordinary run, then proposes follow-ups about what the "
    "answers revealed. The combined answer is written from the steps' facts only. **Every "
    "number in a point must come from the steps that point cites**, and a number told next to "
    "years must come from a step covering those years. A second, separate language-model call "
    "then checks only the reasoning: directions (more or less), comparisons and superlatives "
    "against the cited numbers. A point that fails is removed, and an answer that fails falls "
    "back to each step's own checked headline. Each scenario has an ID, can be re-verified "
    "step by step and exported as a report."
)

# --- tools ---------------------------------------------------------------------------------------
st.subheader(":material/construction: Tools and packages", anchor=False)
st.markdown(
    "Open-source Python (3.12), running locally with no cloud database. The only thing "
    "that leaves the machine is what the assistant sends to the language model: the "
    "question, the table descriptions and a fact sheet of computed numbers, never the data "
    "tables themselves."
)
tools = pd.DataFrame(
    [
        ("App and charts", "Streamlit", "The web app: pages, tabs, chat, dialogs"),
        ("App and charts", "Plotly", "Interactive charts and maps"),
        ("Data", "DuckDB", "Local analytical database; the read-only semantic views"),
        ("Data", "pandas, PyArrow", "Tables in memory and Parquet files"),
        ("Data", "requests, py7zr", "Download and unpack the Eurostat bulk files"),
        ("Data", "pycountry", "ISO-2 to ISO-3 country codes for the maps"),
        ("Assistant", "LangGraph", "The fixed sequence of steps from question to answer"),
        ("Assistant", "OpenAI and Anthropic SDKs", "Calls to the language model"),
        ("Assistant", "Pydantic", "The QuerySpec form and validated structured output"),
        ("Assistant", "sqlglot", "Parses every query for the SQL guard"),
        ("Assistant", "PyYAML", "The limitations registry"),
        ("Analytics", "statsmodels", "Seasonal adjustment (STL) and projections (ETS)"),
        ("Dashboard API", "FastAPI, uvicorn", "The chart API beside the app"),
        ("Quality", "pytest, ruff", "Automated tests and code style"),
        ("Collaboration", "Git, GitHub, Git LFS", "Shared code, history and the app database"),
    ],
    columns=["Area", "Package or tool", "Used for"],
)
st.table(tools, hide_index=True, alt="Packages and tools used")
st.markdown(
    f"**Reproduce the app.** The [README of the repository]({REPO_URL}#readme) explains how to "
    "install the environment, set the language model key, run the app, and rebuild the "
    "database from the Eurostat files: see its section "
    f"[*Setup (reproducible environment)*]({REPO_URL}#setup-reproducible-environment). "
    "Code under the EUPL-1.2 licence."
)

# --- project -------------------------------------------------------------------------------------
st.subheader(":material/groups: The project", anchor=False)
with st.container(border=True):
    st.markdown(POC_NOTE)
    st.markdown("\n".join(f"- **{name}**, {org}" for name, org in CONTRIBUTORS))
