"""Data: the dataset behind the app, its source, structure, tables, columns and processing.

Reference page, opened from the top bar. Tables, columns and limitations are read from the
semantic catalogue and the limitations registry, so this page always matches the code.
UI only (GUIDELINES §1.1).
"""

import re

import pandas as pd
import streamlit as st

from luxtrade.agents import guard
from luxtrade.agents.sql_guard import check_sql
from luxtrade.app.components import get_assistant, load_overview
from luxtrade.config import ATTRIBUTION, DATASET_ID
from luxtrade.semantic.catalog import VIEWS
from luxtrade.viz.format import fmt_eur

assistant = get_assistant()
cov = assistant.sem.coverage
about = load_overview(st.session_state.get("lang") or "en", cov.vintage).about

BULK_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/files/"
    "?sort=1&dir=comext%2FCOMEXT_DATA%2FPRODUCTS"
)
API_GUIDE_URL = (
    "https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/"
    "api-getting-started/comext-database"
)
REUSE_URL = "https://ec.europa.eu/eurostat/about-us/policies/copyright"

st.title("The data")
st.markdown(
    f"Every number in LuxTrade Lens comes from one public dataset: **Eurostat Comext "
    f"{DATASET_ID}**, *EU trade since 1988 by HS2-4-6 and CN8*. No other data source and no "
    "general knowledge of an AI model is used."
)

# --- source and coverage -----------------------------------------------------------------------
with st.container(border=True):
    st.subheader(":material/public: Source", anchor=False)
    st.markdown(
        f"- **Dataset:** Eurostat Comext {DATASET_ID}, compiled by Eurostat from the national "
        "statistical institutes (STATEC for Luxembourg).\n"
        f"- **Access used:** the Comext [bulk download service]({BULK_URL}), one file per "
        "month (`full_v2_YYYYMM.7z`). The [Comext API]({API_GUIDE_URL}) is used only to "
        "cross-check totals: for December 2025 the two agree to the euro.\n"
        "- **Why bulk files:** every row carries the full CN8 detail and the extra product "
        "classifications, there is no row limit, and the app runs on local files with no "
        "network dependency during a demo.\n"
        f"- **Licence:** free reuse with attribution ([Eurostat policy]({REUSE_URL})). "
        f"*{ATTRIBUTION.format(date=about['extraction_date'])}*"
    )
cols = st.columns(4)
facts = [
    ("First month", f"{about['first_period']:%b %Y}"),
    ("Latest complete month", f"{about['latest_complete_period']:%b %Y}"),
    ("Records (Luxembourg)", f"{about['records']:,}"),
    ("Partners × CN8 products", f"{about['partners']} × {about['products']:,}"),
]
for col, (label, value) in zip(cols, facts, strict=True):
    col.metric(label, value, border=True)
st.caption(
    f"Data vintage {cov.extraction_date}. Months after "
    f"{about['latest_complete_period']:%b %Y} hold extra-EU trade only so far, because "
    "intra-EU data is published later; the app stops complete views at the latest complete "
    "month."
)

# --- the original file -------------------------------------------------------------------------
st.subheader(":material/description: Structure of the original files", anchor=False)
st.markdown(
    "Each monthly bulk file is a comma-separated table with a header and 18 fixed columns, "
    "about 2.9 million rows for all EU reporters, of which about 62,000 are Luxembourg's."
)
raw_columns = pd.DataFrame(
    [
        ("REPORTER", "Declaring country (ISO-2). We keep LU, plus EU peers for benchmarking"),
        ("PARTNER", "Partner country (ISO-2). Q* codes are undisclosed partners"),
        ("TRADE_TYPE", "I = intra-EU, E = extra-EU"),
        ("PRODUCT_NC", "CN8 product code (text), TOTAL, or a masked confidential code"),
        (
            "PRODUCT_SITC, _CPA21, _CPA22, _BEC, _BEC5",
            "Other product classifications linked to the CN8 code",
        ),
        ("PRODUCT_SECTION", "HS section 01–21; TO = total; XX = confidential"),
        ("FLOW", "1 = import, 2 = export"),
        ("STAT_PROCEDURE", "Statistical procedure; all procedures are summed"),
        ("SUPPL_UNIT", "Supplementary unit (pieces, litres…), differs by product"),
        ("PERIOD", "YYYYMM"),
        ("VALUE_EUR", "Trade value in euros: the main indicator"),
        ("VALUE_NAC", "Value in national currency, identical to EUR for Luxembourg (dropped)"),
        ("QUANTITY_KG", "Net mass in kg"),
        ("QUANTITY_SUPPL_UNIT", "Quantity in the supplementary unit"),
    ],
    columns=["Column", "Meaning"],
)
st.table(raw_columns, hide_index=True, alt="Columns of the bulk files")

# --- product codes -------------------------------------------------------------------------------
st.subheader(":material/account_tree: Product codes: HS and CN8", anchor=False)
st.markdown(
    "Every product is identified by a code that gets more precise with each pair of digits. "
    "The first six digits are the **Harmonized System (HS)** of the World Customs "
    "Organization, the same in every country and revised about every five years (2002, "
    "2007, 2012, 2017, 2022). The European Union adds two digits to make the **Combined "
    "Nomenclature (CN8)**, revised every year. HS chapters are grouped into 21 **sections**."
)
products = assistant.sem.products
counts = products.groupby("level").size()
levels = pd.DataFrame(
    [
        ("Section", "I–XXI (roman)", "21", "Broad family of goods, e.g. XV Base metals"),
        ("HS2 chapter", "2 digits", f"{counts.get(2, 0):,}", "e.g. 72 Iron and steel"),
        ("HS4 heading", "4 digits", f"{counts.get(4, 0):,}", "e.g. 7216 Steel angles and sections"),
        ("HS6 subheading", "6 digits", f"{counts.get(6, 0):,}", "International detail"),
        ("CN8 product", "8 digits", f"{counts.get(8, 0):,}", "EU detail: the level in the data"),
    ],
    columns=["Level", "Code", "Codes in the data", "What it describes"],
)
st.table(levels, hide_index=True, alt="Levels of the product classification")
st.markdown(
    "**How the app uses them.** Long series (2002 onwards) are shown by HS2 chapter, which "
    "is stable; HS4 and HS6 for medium periods; CN8 for recent years only, because CN8 "
    "codes can split, merge or disappear from one year to the next. When a company's trade "
    "is confidential, its CN8 code is masked, e.g. `27XXXXXX` = confidential within chapter "
    "27; that value stays in its chapter and shows as *Confidential* in drill-downs. "
    "Chapter 99 holds trade whose chapter is not disclosed."
)

# Three real chains from section to CN8, each a large item of Luxembourg's trade
EXAMPLES = {
    "Electric cars": "87038010",
    "Steel H-beams": "72163390",
    "Diesel": "27101943",
}
# only chains that exist in the loaded code lists (the synthetic test data has fewer codes)
examples = {
    name: cn8
    for name, cn8 in EXAMPLES.items()
    if all(cn8[:digits] in products.index for digits in (2, 4, 6, 8))
}
if examples:
    code_year = cov.latest_complete_year
    chapters = ", ".join(f"'{cn8[:2]}'" for cn8 in examples.values())
    code_sql = check_sql(
        f"""SELECT cn8, sum(value_eur) AS value_eur
FROM v_lu_trade
WHERE year = {code_year} AND hs2 IN ({chapters})
GROUP BY cn8"""
    )
    by_cn8 = assistant.sem.query(code_sql).set_index("cn8")["value_eur"]
    sections = assistant.sem.sections
    st.markdown(
        f"**Real examples**, with Luxembourg's trade (exports + imports) in {code_year} at "
        "each level:"
    )
    for tab, cn8 in zip(st.tabs(list(examples)), examples.values(), strict=True):
        with tab:
            section_code = products.loc[cn8[:2], "section"]
            rows = []
            if section_code in sections.index:
                rows.append(
                    (
                        "Section",
                        sections.loc[section_code, "roman"],
                        sections.loc[section_code, "label_en"],
                        "",
                    )
                )
            # non-breaking spaces keep each level on one line, so the column is wide enough
            for name, digits in (
                ("HS2\u00a0chapter", 2),
                ("HS4\u00a0heading", 4),
                ("HS6", 6),
                ("CN8", 8),
            ):
                code = cn8[:digits]
                value = by_cn8[by_cn8.index.str.startswith(code)].sum()
                rows.append((name, code, products.loc[code, "label_en"], fmt_eur(value)))
            st.table(
                pd.DataFrame(
                    rows, columns=["Level", "Code", "Official label", f"Trade\u00a0{code_year}"]
                ),
                hide_index=True,
                alt=f"Product code chain for {cn8}",
            )
    with st.expander("How the example values were computed"):
        st.code(code_sql, language="sql")

# --- processing ----------------------------------------------------------------------------------
st.subheader(":material/conversion_path: What we do to the data", anchor=False)
steps = pd.DataFrame(
    [
        (
            "1. Download",
            "ingest/download.py",
            "Fetch each monthly 7z file and the EN/FR/DE code lists; record source URL, "
            "server date and SHA-256 checksum in a manifest. Interrupted runs resume.",
        ),
        (
            "2. Reduce",
            "ingest/reduce.py",
            "Keep every Luxembourg row (lossless) and the HS2 totals of BE, NL, DE, FR and AT "
            "for benchmarking. Codes stay text, so leading zeros survive.",
        ),
        (
            "3. Build",
            "process/build.py",
            "Sum over statistical procedures; flag masked codes as confidential and Q* "
            "partners as undisclosed; map flows and trade types; attach EN/FR/DE labels; "
            "mark unknown masses as missing, not zero.",
        ),
        (
            "4. Validate",
            "process/validate.py",
            "Stop on bad codes, duplicate keys or a wrong schema. Check that detail plus "
            "masked rows equals the TOTAL rows for every month, trade type and flow.",
        ),
        (
            "5. Serve",
            "semantic/build.py",
            "Load the Parquet files into a read-only DuckDB database and expose the "
            "semantic views below: the only tables any query may use.",
        ),
    ],
    columns=["Step", "Code", "What happens"],
)
st.table(steps, hide_index=True, alt="Processing steps")
st.markdown(
    "**Never done:** dropping masked or confidential rows, editing values by hand, or mixing "
    "TOTAL rows with detail rows. Values stay in current euros (nominal), as published."
)

# --- tables and columns ------------------------------------------------------------------------
st.subheader(":material/table_chart: Tables and columns", anchor=False)
st.markdown(
    "The assistant, the dashboards and every chart query these views, and nothing else. "
    "The SQL guard rejects any other table."
)
for view, (description, columns) in VIEWS.items():
    with st.expander(f"`{view}` · {description}"):
        st.dataframe(
            pd.DataFrame(columns, columns=["Column", "Type", "Meaning"]),
            hide_index=True,
            width="stretch",
        )

# --- limits --------------------------------------------------------------------------------------
st.subheader(":material/block: What the data can and can't say", anchor=False)
st.markdown(
    "Each known limit of the data is a rule in the limitations registry. The assistant "
    "checks every question and every result against it, and either warns or refuses with an "
    "explanation."
)
limits = pd.DataFrame(
    [
        (lim_id, entry.get("section", ""), re.sub(r"\{[^}]*\}", "x", entry["message"]))
        for lim_id, entry in guard.registry().items()
    ],
    columns=["ID", "Data card", "Rule shown to the user"],
)
st.table(limits, hide_index=True, alt="Limitations registry")
