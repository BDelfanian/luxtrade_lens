# Project Context — STATEC Hackathon 2026: Luxembourg External Trade

**Team:** The Outliers (Behrouz, Mina, Kasra) · **Venue:** GovTech Lab, Luxembourg · **Dates:** 14–16 Oct 2026

---

## 1. The challenge in one sentence

Build the **most effective (smart, interactive) visual representation of Luxembourg's external trade in goods**: who it trades with, what it trades, how this changes over time and across seasons, and how it compares with other countries. Use only the Eurostat dataset that was provided.

## 2. Official questions (brochure, slides 18–19)

| # | Question | What it means in practice |
|---|----------|---------------------------|
| Q1 | Who are Luxembourg's **main trading partners** (exports & imports)? How have they **evolved over time**? | Partner rankings, partner shares over time, rank changes |
| Q2 | What are the **main categories of goods** exported/imported? How have the patterns changed? | HS2 chapter composition over time |
| Q3 | For a **given product category**, who are the principal partners? | Product → partner view |
| Q4 | For a **given partner country**, what are the main goods (HS2)? How can **HS4 → HS6 → CN8 detail** be shown while **highlighting only the most significant flows**? | Partner → product drill-down with automatic "top-N + Other" filtering |
| Q5 | How does Luxembourg's trade **compare with other countries**? | Benchmarking LU against other EU reporters |
| Q6 | Do trade flows have **seasonal patterns**, overall or by product? How can the evolution be shown **with purely seasonal effects filtered out**? | Seasonal decomposition, seasonally adjusted trends |
| — | "Any other element you consider relevant" | Room for our own ideas (see §7) |

## 3. Notes from the organiser briefing (14 Oct)

- **Goods only**, not services.
- Focus on Luxembourg's **main partners**.
- Use both **monthly and annual** frequencies.
- Aim for the **smartest, most interactive tool** to answer the questions.
- Cover **categories and sub-categories** (the HS hierarchy).
- Use visualisations that make **comparison** easy.
- Show **seasonal patterns** of goods.
- Propose **our own ideas** for answering the most fundamental questions.
- **Stick to the provided data.** Don't rely on other sources.

## 4. Hard requirements ("Key considerations", slide 22)

1. **Focus on Luxembourg.**
2. **Temporal dimension:** compare different points in time.
3. **Geospatial dimension:** for example, compare Luxembourg with other countries (maps are expected).

## 5. Deliverables (slide 21) and licensing (slide 25)

| Deliverable | Content |
|-------------|---------|
| **Pitch deck** | Idea, approach (tools, methodology), mini demo. **5-minute pitch** on Fri 16 Oct at 10:30 |
| **Reproducible artefacts** | Jupyter notebook(s), scripts/app, `requirements.txt` / `environment.yml`, licence, README |
| **Transmission** | Link to a public Git repository, shared at the end of the hackathon |

Licensing rules:
- The repository must include an **open-source licence with an SPDX identifier**. EUPL-1.2 is preferred for the EU public sector; Apache-2.0 and MIT are also accepted.
- Include a **Data Card** that cites Eurostat as the source and states the data licence (Eurostat data is reusable with attribution).
- Don't commit large raw data. Provide a download script instead, plus small aggregated samples if needed.
- Dependencies must have compatible licences.
- Don't use the STATEC logo or brand outside the materials they approved.

## 6. Evaluation criteria (slide 23) and how we'll address each one

| Criterion | Our answer |
|-----------|------------|
| **Reproducibility & Openness** | One-command pipeline (`download → process → app`), pinned environment, EUPL-1.2, Data Card, documented method |
| **Clarity & Quality of Presentation** | A 5-minute story built around 3–4 "wow" insights, rehearsed and timed, with a live demo and a recorded backup |
| **Use of Data** | Use the full depth: monthly and annual data, HS2→CN8, value and quantity (unit values), all EU reporters for benchmarking |
| **Innovation & Experimentation** | Smart significance filtering, outlier and structural-break detection (our team name!), seasonal adjustment, concentration metrics |
| **Functional PoC** | A working interactive app with all six questions reachable from one interface, deployed online |

The jury is mostly STATEC heads of department and unit: macroeconomics, IT, data access, forecasting, communication and the Data Lab. They will reward **statistically sound methods**, **clean engineering** and **clear communication** about equally.

## 7. Data source

**Eurostat Comext, `DS-045409`: "EU trade since 1988 by HS2-4-6 and CN8".**
Browser: <https://ec.europa.eu/eurostat/databrowser/view/ds-045409/legacyMultiFreq/table?category=ext_go.ext_go_detail>

### Dimensions (to confirm when we first load the data)

| Dimension | Values of interest |
|-----------|--------------------|
| `freq` | `M` (monthly), `A` (annual) |
| `reporter` | `LU`, plus other EU members (for Q5) |
| `partner` | ~250 countries plus aggregates (e.g. `EU27_2020_INTRA`, `EU27_2020_EXTRA`, `WORLD`) |
| `product` | `TOTAL`, HS2 (2 digits), HS4, HS6, CN8 (8 digits) |
| `flow` | `1` = import, `2` = export |
| `indicators` | `VALUE_IN_EUROS`, `QUANTITY_IN_100KG`, `SUPPLEMENTARY_QUANTITY` |

### Access options (to validate on Day 1)

1. **Comext SDMX 2.1 API**, with filtered queries for LU only, e.g.
   `https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409/M.LU..TOTAL.2.VALUE_IN_EUROS`
   (the exact key order must be checked against the DSD).
2. **Comext bulk download**: monthly full files (all reporters, CN8). These are large but complete, and work best for the CN8 drill-down.
3. **Data browser export (CSV/TSV)** as a fallback for quick prototyping.

### Known data caveats (we should state these explicitly; it shows statistical maturity)

- **Belgium–Luxembourg Economic Union (BLEU):** Luxembourg was reported jointly with Belgium until 1998. LU-only series start in **1999**.
- **Nomenclature changes:** CN8 codes change every year and HS is revised roughly every 5 years (2002, 2007, 2012, 2017, 2022). Long CN8 series can break. HS2 and HS4 are much more stable.
- **Confidential trade:** some flows are suppressed or pooled (e.g. chapter 99 / special codes). Totals ≠ sum of detail.
- **Intra-EU vs extra-EU:** intra-EU trade comes from Intrastat (with exemption thresholds), extra-EU from customs. Methods differ.
- **Asymmetries:** LU exports to X ≠ X's imports from LU (CIF/FOB, timing, quasi-transit, the "Rotterdam effect").
- **Small open economy:** a few large firms and products (e.g. steel, tyres, aircraft-related goods, pharmaceuticals) can create spikes. These are true outliers and need explanation, not removal.
- **Revisions:** recent months are provisional.

## 8. Our concept (working title: *"LuxTrade Lens"*)

An **interactive web app** (Streamlit/Plotly) with a guided story mode for the pitch and an exploration mode for the jury.

| Module | Questions | Key visuals |
|--------|-----------|-------------|
| **Overview** | Q1, Q2 | KPI tiles (exports, imports, balance, YoY), stacked area of top partners/chapters, bump chart of rank changes |
| **Partner Explorer** | Q1, Q4 | World choropleth (geospatial), partner profile, HS2→CN8 drill-down treemap/sunburst with automatic "Top-N + Other" |
| **Product Explorer** | Q2, Q3 | Product hierarchy picker, partner map for the selected product, Sankey (partners ↔ product groups) |
| **Seasonality Lab** | Q6 | STL decomposition, month×year heatmap, seasonal-subseries plot, raw vs seasonally adjusted overlay |
| **Benchmark** | Q5 | LU vs EU reporters: intra/extra-EU share, partner concentration (HHI), product diversification, growth indices (all computed from the same dataset) |
| **Outlier Radar** *(our signature feature)* | Extra | Automatic detection of unusual flows: spikes, structural breaks, newly emerging partners/products, unit-value anomalies |

### Methods for "highlighting only the most significant flows" (Q4)

- **Pareto cut:** show the flows that make up X% (e.g. 80%) of the parent's value and collapse the rest into "Other".
- **Adaptive Top-N** at each hierarchy level (HS2 → HS4 → HS6 → CN8), drilling down on click.
- **Significance by change, not just size:** surface flows with large absolute or relative changes.

## 9. Constraints and principles

- **Only the provided Eurostat data.** Every metric is derived from DS-045409: no GDP, population or external sources. If a normalisation needs external data, we drop it or flag it clearly as optional.
- **Values in EUR, current prices.** Unit values (EUR/100 kg) serve as a price proxy where quantities exist.
- **Reproducible first:** the pipeline should work from a clean clone.
- **Time-box:** the build window is about 2.5 days, so anything not demo-ready by Thursday evening gets cut.
