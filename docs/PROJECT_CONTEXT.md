# Project Context — STATEC Hackathon 2026: Luxembourg External Trade

**Team:** The Outliers (Behrouz, Mina, Kasra) · **Venue:** GovTech Lab, Luxembourg · **Dates:** 14–16 Oct 2026

---

## 1. The challenge in one sentence

Build the **most effective (smart, interactive) visual representation of Luxembourg's external trade in goods**: who it trades with, what it trades, how this changes over time and across seasons, and how it compares with other countries. Use only the Eurostat dataset that was provided.

## 1a. Problem statement: WHAT are we solving, and WHY?

> Check every feature against this section. If a feature doesn't serve the WHAT or the WHY, cut it.

**WHAT:** Luxembourg's trade data is very rich: about 250 partners × about 10,000 CN8 products × 2 flows × monthly data since 1999. But today it is only available as **tables**, for example in the Eurostat data browser. Anyone wanting a simple answer, like *"what do we sell to Germany, and is it growing?"*, has to know the codes, build queries and assemble charts by hand. The data exists. **Getting answers out of it is the bottleneck.**

**WHY:**
- Luxembourg is a **small, very open economy**, so trade matters a lot to it, and it depends on a handful of partners and products. Knowing *who we depend on, for what, and how that is changing* is basic economic intelligence.
- **Shocks show up in trade first**, e.g. COVID-19 and the 2022 energy crisis. Seasonality can hide or fake such signals unless it is filtered out.
- STATEC wants to become a **data-engineering institute** that turns numbers into "levers for understanding and action" (slide 10). A reusable, open tool directly supports that mission.

**For whom:** STATEC analysts first, then policymakers, journalists and curious citizens. The tool must work for someone who doesn't know what "CN8" means.

**Our answer in one line:** *a simple tool where any trade question becomes a choice of **who × what × when × which flow**, answered by a clear chart and a sentence in plain language.*

## 1b. Coach guidance (14 Oct)

1. **The questions are only samples.** We don't build six separate answers. We build a **general tool** that can answer these questions *and others like them* (§8).
2. **The product dimension matters most.** Finding and preparing the right product data (levels, labels, code changes) is the critical first task (§7a).
3. **Always keep WHAT and WHY in mind** (§1a). The pitch opens with them.
4. **Make grading easy for the jury.** We avoid complex solutions: fewer features, done well, with each one obviously tied to a criterion (§6).

## 2. Official sample questions (brochure, slides 18–19)

These are **examples** of what the tool must be able to answer, not the full scope (coach tip 1).

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
| **Innovation & Experimentation** | The general "who × what × when × flow" engine with question presets, smart significance filtering, seasonal adjustment, simple outlier flags (our team name!) |
| **Functional PoC** | A working interactive app with all six questions reachable from one interface, deployed online |

**Make grading easy** (coach tip 4):
- The README opens with a **"For the jury" table** that maps each criterion to where it is shown: an app page, a file or a command.
- The app has **a few tabs with clear names**, and every chart has a title that states its takeaway.
- Setup and launch take three commands. A hosted link means the jury needs no setup at all.
- We present no method we can't explain in one sentence.

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

## 7a. The product dimension (priority one, coach tip 2)

Every view depends on the product data being right, so this gets checked **before** any app work.

| Check | Why it matters |
|---|---|
| Which levels actually exist in DS-045409 (TOTAL, HS2, HS4, HS6, CN8), and for which years and frequencies | Decides what the drill-down can offer |
| **Product labels** (Eurostat code lists) for every level, in English | No one can read "8703"; everyone can read "Motor cars" |
| **Hierarchy consistency:** does CN8 → HS6 → HS4 → HS2 → TOTAL add up? Where are the gaps (confidential trade, special codes like chapter 99)? | Totals must reconcile, or the "Other" bucket has to explain the gap |
| **Code changes over time** (yearly CN changes, HS revisions) | Decides how far back each level can be trusted as a time series |
| **Quantity coverage** (`QUANTITY_IN_100KG`, supplementary units) by level | Decides whether unit values (price proxy) are feasible |
| **Higher-level groupings:** the 21 HS **sections** built from HS2 chapters (e.g. "Base metals", "Machinery") | A friendlier top level than 97 chapters. This is part of the HS nomenclature itself, not external data |

**Open question for the coach:** are Eurostat's own classification metadata allowed (code lists/labels, CN correspondence tables, HS sections)? We assume **yes**, since they describe the provided dataset rather than adding new data.

## 8. Our concept (working title: *"LuxTrade Lens"*)

**One general engine, not six answers.** Every trade question is a choice along four dimensions:

```
WHO (partner / country group) × WHAT (product, any level) × WHEN (period, M/A) × FLOW (import/export/balance)
```

The app is a set of filters over these dimensions plus a few chart types that suit each combination. The sample questions become **presets**: one click sets the filters. New questions need no new code. That way we address coach tip 1 *and* keep things simple (coach tip 4).

An **interactive web app** (Streamlit/Plotly) with a short guided story for the pitch and free exploration for the jury. The modules below are **views of the same engine**, ordered by priority. The lower ones are optional.

| Module | Questions | Key visuals |
|--------|-----------|-------------|
| **Overview** | Q1, Q2 | KPI tiles (exports, imports, balance, YoY), stacked area of top partners/chapters, bump chart of rank changes |
| **Partner Explorer** | Q1, Q4 | World choropleth (geospatial), partner profile, HS2→CN8 drill-down treemap/sunburst with automatic "Top-N + Other" |
| **Product Explorer** | Q2, Q3 | Product hierarchy picker, partner map for the selected product, Sankey (partners ↔ product groups) |
| **Seasonality Lab** | Q6 | STL decomposition, month×year heatmap, seasonal-subseries plot, raw vs seasonally adjusted overlay |
| **Benchmark** | Q5 | LU vs EU reporters: intra/extra-EU share, partner concentration (HHI), product diversification, growth indices (all computed from the same dataset) |
| **Outlier Radar** *(optional signature, kept simple)* | Extra | One simple, explainable rule: flag months that deviate strongly from their seasonally adjusted trend (robust z-score), plus newly emerging or vanishing partners and products. No black-box models. |

### Methods for "highlighting only the most significant flows" (Q4)

- **Pareto cut:** show the flows that make up X% (e.g. 80%) of the parent's value and collapse the rest into "Other".
- **Adaptive Top-N** at each hierarchy level (HS2 → HS4 → HS6 → CN8), drilling down on click.
- **Significance by change, not just size:** surface flows with large absolute or relative changes.

## 9. Constraints and principles

- **Simple beats clever.** Prefer a clear bar or line chart over an exotic one, and a transparent rule over a model. Add complexity only when it clearly makes the answer easier to see.
- **Every feature must pass the WHAT/WHY test** (§1a).

- **Only the provided Eurostat data.** Every metric is derived from DS-045409: no GDP, population or external sources. If a normalisation needs external data, we drop it or flag it clearly as optional.
- **Values in EUR, current prices.** Unit values (EUR/100 kg) serve as a price proxy where quantities exist.
- **Reproducible first:** the pipeline should work from a clean clone.
- **Time-box:** the build window is about 2.5 days, so anything not demo-ready by Thursday evening gets cut.
