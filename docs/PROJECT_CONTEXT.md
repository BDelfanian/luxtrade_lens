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

**For whom:** an **employee of a Luxembourg public institution**: STATEC, a ministry (Economy, Finance, Foreign & European Affairs), the central bank (BCL) or a public agency. They know the economy, but not Comext codes, SQL or the HS nomenclature, and they work in **English, French or German**. Policymakers, journalists and citizens come second. The tool must work for someone who doesn't know what "CN8" means.

**Our answer in one line:** *ask a trade question in your own words (EN/FR/DE). The tool turns it into a choice of **who × what × when × which flow** and answers with an interactive chart, table or pivot table, a short plain-language insight, the data limits that apply, and a trace showing where every number comes from.* Full design: **[SOLUTION_DESIGN.md](SOLUTION_DESIGN.md)**.

## 1b. Coach guidance (14 Oct)

1. **The questions are only samples.** We don't build six separate answers. We build a **general tool** that can answer these questions *and others like them* (§8).
2. **The product dimension matters most.** Finding and preparing the right product data (levels, labels, code changes) is the critical first task (§7a).
3. **Always keep WHAT and WHY in mind** (§1a). The pitch opens with them.
4. **Make grading easy for the jury.** We avoid complex solutions: fewer features, done well, with each one obviously tied to a criterion (§6).

**How the natural-language design (decided 14 Oct) respects these tips:**
- *Tip 1:* the language layer only fills in the general who × what × when × flow query. Presets and filters use the same engine.
- *Tip 2:* product labels and the hierarchy, in EN/FR/DE, are what make entity resolution work, so product data is still the first task.
- *Tip 3:* WHAT and WHY stay the opening of the pitch.
- *Tip 4:* **LLMs translate, code computes.** LLMs only interpret the question, word the insight and, when needed, suggest rewrites of vague questions or write SQL for unusual ones. Every number comes from SQL or tested Python. Routing, chart choice, limitation checks, rewrite validation and forecasting are transparent rules. Each step can be explained in one sentence ([SOLUTION_DESIGN §3](SOLUTION_DESIGN.md#3-architecture-overview)).

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
| **Reproducibility & Openness** | One-command pipeline (`download → process → app`), pinned environment, EUPL-1.2, Data Card. **Every answer has a run ID that replays and re-verifies its result** (result hash), and the SQL is shown |
| **Clarity & Quality of Presentation** | The app opens on an **Overview**: Luxembourg's trade at a glance (size, partners and dependence, products, seasonality, EU peers), each with a takeaway headline and its evidence. The 5-minute story is built around 3–4 "wow" insights, asked live in FR/DE/EN, rehearsed and timed, with recorded runs as a backup |
| **Use of Data** | Use the full depth: monthly and annual data, HS2→CN8, value and quantity (unit values), all EU reporters for benchmarking. Data limits are shown, not hidden (limitations registry) |
| **Innovation & Experimentation** | Multilingual natural-language questions with follow-ups in context → automatically chosen data product + grounded insight; a question optimiser that turns vague questions into validated, answerable ones; a traceable agent graph; statistical projections with a baseline check; smart significance filtering; seasonal adjustment |
| **Functional PoC** | A working interactive app: overview page, ask box, presets for all six questions, Refine filters, history, deployed online. Accuracy measured on a golden question set |

**Make grading easy** (coach tip 4):
- The README opens with a **"For the jury" table** that maps each criterion to where it is shown: an app page, a file or a command.
- The app has **two pages with clear names**: **Overview** (the big picture, the landing page) and **Ask** (specific questions). Every overview section has a headline that states its takeaway.
- Setup and launch take three commands. A hosted link means the jury needs no setup at all.
- We present no method we can't explain in one sentence.

The jury is mostly STATEC heads of department and unit: macroeconomics, IT, data access, forecasting, communication and the Data Lab. They will reward **statistically sound methods**, **clean engineering** and **clear communication** about equally.

## 7. Data source

**Eurostat Comext, `DS-045409`: "EU trade since 1988 by HS2-4-6 and CN8".**
Browser: <https://ec.europa.eu/eurostat/databrowser/view/ds-045409/legacyMultiFreq/table?category=ext_go.ext_go_detail>

### Access decision (validated 14 Oct): **Comext bulk files**

We tested both the API and the bulk download. The team chose the **bulk monthly files** (`full_v2_YYYYMM.7z`, Jan 2002 → Jul 2026), filtered to Luxembourg at download. The API is kept only for cross-checking totals. Reasons, file structure, coverage and measured figures are in **[DATA_CARD.md](DATA_CARD.md)**.

Bulk-file dimensions: `REPORTER`, `PARTNER` (ISO-2, no aggregates), `TRADE_TYPE` (intra/extra), `PRODUCT_NC` (CN8), plus **SITC, CPA, BEC, BEC5 and HS section** per row, `FLOW`, `PERIOD`, `VALUE_EUR`, `QUANTITY_KG`, `QUANTITY_SUPPL_UNIT`.

### Key data limitations (details and handling in [DATA_CARD.md §4](DATA_CARD.md#4-limitations-and-how-we-handle-them))

| Limitation | In short | Our handling |
|---|---|---|
| **Starts in 2002** | Bulk files begin Jan 2002 (LU-only data exists from 1999; joint with Belgium before that) | Series start in 2002 and this is stated in the app |
| **Confidential codes** | Masked codes such as `27XXXXXX`, `3920XXXX`, `99XXXXXX`; about 4.9 % of imports and 1.7 % of exports hidden at CN8 level (Dec 2025) | Flag them, never drop them; "Confidential" slice in drill-downs; totals still reconcile |
| **Latest months incomplete** | Intra-EU is published later; Jan–Jul 2026 are extra-EU only | Detect the latest complete month automatically |
| **Code changes** | CN8 changes yearly, HS about every 5 years | Long trends at HS2/section level; CN8 for recent snapshots |
| **No partner aggregates; Brexit** | World/intra/extra must be derived; UK switches in 2021 | Fixed EU27 (2020) composition |
| **Nominal values, partial quantities** | Current euros; quantity is 0 in about 4 % of rows | Label as nominal; unit values only where valid |
| **Revisions, asymmetries, volatility** | Provisional months; mirror flows differ; spikes from a few firms | Manifest + extraction date; LU as reporter only; flag spikes, don't delete them |

## 7a. The product dimension (priority one, coach tip 2)

Every view depends on the product data being right, so this gets checked **before** any app work.

| Check | Why it matters |
|---|---|
| Which levels actually exist in DS-045409 (TOTAL, HS2, HS4, HS6, CN8), and for which years and frequencies | Decides what the drill-down can offer |
| **Product labels** (Eurostat code lists) for every level, in English | No one can read "8703"; everyone can read "Motor cars" |
| **Hierarchy consistency:** does CN8 → HS6 → HS4 → HS2 → TOTAL add up? Where are the gaps (confidential trade, special codes like chapter 99)? | Totals must reconcile, or the "Other" bucket has to explain the gap |
| **Code changes over time** (yearly CN changes, HS revisions) | Decides how far back each level can be trusted as a time series |
| **Quantity coverage** (`QUANTITY_KG` in the bulk files, supplementary units) by level | Decides whether unit values (price proxy) are feasible |
| **Higher-level groupings:** the 21 HS **sections** built from HS2 chapters (e.g. "Base metals", "Machinery") | A friendlier top level than 97 chapters. This is part of the HS nomenclature itself, not external data |

| **Labels in EN, FR and DE** for products and partners | The assistant resolves *"Allemagne"*, *"Maschinen"* or *"cars"* to codes by looking them up in these labels ([SOLUTION_DESIGN §5.2](SOLUTION_DESIGN.md#52-interpreter-llm-structured-output)) |

**Open question for the coach:** are Eurostat's own classification metadata allowed (code lists/labels in EN/FR/DE, CN correspondence tables, HS sections)? We assume **yes**, since they describe the provided dataset rather than adding new data.

## 8. Our concept: *LuxTrade Lens*, ask a question and get a data product

**One general engine, not six answers.** Every trade question becomes a choice along four dimensions:

```
WHO (partner / country group) × WHAT (product, any level) × WHEN (period, M/A) × FLOW (import/export/balance)
```

We reach that engine through **several doors, all producing the same structured query** (`QuerySpec`):
1. **Ask:** a question in EN/FR/DE. A small agent graph interprets it, checks it against the data limits, queries, analyses, picks the right view and writes the insight.
2. **Follow up:** *"and for imports?"*, *"only Germany"*, *"zoom in on the second one"*. The question is interpreted in the context of the session's earlier answers. The context carried over is always shown.
3. **Optimise:** when a question is too vague, ambiguous or beyond the data, the tool offers **three precise rewrites**, each checked as answerable, or lets the user ask more specifically. It never guesses.
4. **Presets:** the sample questions Q1–Q6 as one-click buttons (no LLM needed).
5. **Refine:** filters on every answer (period, flow, partner, product, level, top-N) that re-run the query instantly (no LLM needed).

Every answer is a **data product** chosen automatically from the shape of the result. It can be:
- a KPI tile
- a line or area chart
- a ranked bar chart
- a choropleth map
- a treemap drill-down
- a pivot table
- a seasonality heatmap
- a projection with an uncertainty band

It always comes with an interactive table, a **4–5 sentence insight** in the user's language, **the limitations that apply** and a **"How we got this" trace**. Every answer has a run ID, and every conversation has a session ID, both used for history, recall and resuming.

The architecture, agents, rules and UI are in **[SOLUTION_DESIGN.md](SOLUTION_DESIGN.md)**.

### Which answer covers which sample question

| Answer type (intent) | Questions | Default data product |
|---|---|---|
| Ranking / evolution | Q1, Q2 | Ranked bars + choropleth; lines or stacked area over time; rank changes |
| Partner → product drill-down | Q4 | Treemap HS2 → HS4 → HS6 → CN8 with automatic Top-N + "Other" + "Confidential" |
| Product → partner | Q3 | Partner map + ranked bars for the selected product |
| Benchmark | Q5 | LU vs EU reporters: intra-EU share, partner concentration (HHI), indexed growth (2015 = 100), EU map |
| Seasonality | Q6 | Month × year heatmap; raw vs seasonally adjusted (STL) |
| Projection *(where applicable)* | Extra | ETS projection with 80/95 % intervals, checked against a "same month last year" baseline |
| Pivot | Extra | Two dimensions × measure, user-selected axes |
| Simple outlier flags *(optional)* | Extra | Months that deviate strongly from the seasonally adjusted trend (robust z-score) |

### Methods for "highlighting only the most significant flows" (Q4)

- **Pareto cut:** show the flows that make up X% (e.g. 80%) of the parent's value and collapse the rest into "Other".
- **Adaptive Top-N** at each hierarchy level (HS2 → HS4 → HS6 → CN8), drilling down on click.
- **Significance by change, not just size:** surface flows with large absolute or relative changes.

## 9. Constraints and principles

- **Simple beats clever.** Prefer a clear bar or line chart over an exotic one, and a transparent rule over a model. Add complexity only when it clearly makes the answer easier to see.
- **LLMs translate, code computes.** An LLM may interpret the question (in its session context), suggest rewrites of vague questions, write SQL for unusual questions, and phrase the insight. It never produces a number, and its rewrites are shown only after code has checked that they are answerable. Every figure comes from SQL or tested Python, and the insight is checked against those figures.
- **Say the limit, don't guess.** When a question goes beyond the data (pre-2002, services, GDP, mirror flows, causes), the tool says so plainly and offers the nearest answerable question ([DATA_CARD §4](DATA_CARD.md#4-limitations-and-how-we-handle-them), [SOLUTION_DESIGN §5.3](SOLUTION_DESIGN.md#53-limitation-guard-rules-no-llm)).
- **Traceable by default.** Every answer shows its assumptions, SQL, data vintage and methods, and has a run ID that replays and re-verifies it.
- **Every feature must pass the WHAT/WHY test** (§1a).
- **Only the provided Eurostat data.** Every metric is derived from DS-045409: no GDP, population or external sources. The LLM's general knowledge is not a data source. Eurostat's own code lists and labels describe the dataset, so we use them (pending coach confirmation, §7a).
- **Values in EUR, current prices.** Unit values (EUR/kg) serve as a price proxy where quantities exist.
- **Forecasts are projections, not predictions.** Classical statistical models only (exponential smoothing), on aggregated series, with intervals and a baseline check. No ML models and no external drivers.
- **Reproducible first:** the pipeline and the app work from a clean clone. Presets and stored runs work without an LLM key.
- **Time-box:** the build window is about 2.5 days. Anything not demo-ready by Thursday 18:00 gets cut, following the cut order in [ROADMAP.md](ROADMAP.md).
