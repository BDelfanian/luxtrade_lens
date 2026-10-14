# Roadmap — The Outliers @ STATEC Hackathon 2026

**Hard deadline:** pitch on **Fri 16 Oct, 10:30** (5 minutes). The repository link is shared at the end of the hackathon.
Background, requirements and the concept are in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

> **Coach principles. Check them at every stand-up:**
> 1. The questions are samples, so build a **general who × what × when × flow tool** with presets, not six one-off answers.
> 2. **Product data comes first.** Get it right before building views.
> 3. Always ask **WHAT problem, and WHY** it matters ([PROJECT_CONTEXT §1a](PROJECT_CONTEXT.md)).
> 4. **Make grading easy. Avoid complexity.**

## Suggested roles (adjust freely)

| Person | Primary | Secondary |
|--------|---------|-----------|
| **Behrooz** | Bulk download pipeline; analytics (rankings, benchmark, seasonality, outliers) | README, methodology, reproducibility |
| **Mina** | App and visualisation (Streamlit/Plotly, maps, drill-down) | UX, deployment |
| **Kasra** | **Data management:** data model, data contract, missing-value rules, cleaning and validation, DATA_CARD | EDA and key insights |

Everyone reviews each other's work and joins rehearsals.

---

## Phase 0 — Setup (Wed 14 Oct, 10:30–12:00)

- [ ] Repository structure (below), `.gitignore` for `data/raw/`, **LICENSE (EUPL-1.2)**, README skeleton
- [ ] `environment.yml` / `requirements.txt` (python ≥3.11, pandas, pyarrow, duckdb, plotly, streamlit, statsmodels, requests)
- [x] **Validate data access:** API and bulk both tested; **bulk chosen** (see [DATA_CARD.md](DATA_CARD.md))
- [x] Decide the scope: **2002 → latest complete month**; LU at full CN8 detail; EU27 reporters as summaries for benchmarking

```
├── data/            raw/ (git-ignored)  processed/ (small Parquet aggregates)
├── src/
│   ├── download.py  # reproducible fetch from Eurostat
│   ├── process.py   # clean, harmonise, build HS hierarchy, aggregates
│   ├── analytics.py # seasonality, concentration, outliers
│   └── app/         # Streamlit app (pages per module)
├── notebooks/       # EDA + methodology notebook
├── docs/            # context, roadmap, Data Card, methodology
├── LICENSE  README.md  environment.yml  requirements.txt  Makefile
```

**Exit criterion:** raw LU data lands on disk via a script.

## Phase 1 — Data foundation, product first (Wed 14 Oct, 14:00–18:00)

- [ ] **Product-dimension audit** (coach tip 2, see [PROJECT_CONTEXT §7a](PROJECT_CONTEXT.md)): available levels × years × frequencies; labels; hierarchy reconciliation (CN8→…→TOTAL); confidential and special codes; CN/HS code changes; quantity coverage. **Write the findings into `docs/DATA_CARD.md` right away.**
- [ ] Build the HS2 → 21 HS **sections** mapping as a friendly top level
- [ ] Ask the coach: are Eurostat classification metadata (labels, CN correspondence tables) OK to use?
- [ ] `download.py`: stream the 295 monthly bulk files (2002 → latest). For each: download → manifest (SHA-256) → extract → keep LU rows + EU27 reporter summaries (reporter × trade type × flow × HS2 × month) → delete raw. **Start it early, in the background (~1–1.5 h).**
- [ ] Reconciliation test: detail + confidential = `TOTAL` per month; spot-check against the API
- [ ] `process.py`: tidy long table → Parquet; product hierarchy table (CN8→HS6→HS4→HS2) with labels; partner table with ISO codes and labels for the maps
- [ ] Data-quality checks: totals vs sum of children, confidential codes, missing months, the 1999 BLEU start
- [ ] Quick EDA notebook: top partners, top chapters, monthly series. **Write down 5 candidate insights.**
- [ ] (Parallel) App skeleton with navigation and dummy charts

**Exit criterion:** clean Parquet + first EDA insights + app shell running locally.

## Phase 2 — Core modules (Thu 15 Oct, 09:00–13:00)

- [ ] **Overview** (Q1, Q2): KPI tiles, partner/chapter evolution, rank bump chart
- [ ] **Partner Explorer** (Q1, Q4): choropleth, partner profile, HS2→CN8 drill-down with Pareto / Top-N + "Other"
- [ ] **Product Explorer** (Q2, Q3): hierarchy selector → partner ranking + map
- [ ] **Core engine:** one set of filters (who × what × when × flow, plus frequency and metric) drives every view
- [ ] **Question presets:** the sample questions as one-click buttons that set the filters (shows generality without extra code)
- [ ] Each chart gets a title that states its takeaway, plus a source caption

**Exit criterion:** Q1–Q4 answerable end-to-end in the app.

## Phase 3 — Differentiators (Thu 15 Oct, 14:00–18:00)

- [ ] **Seasonality Lab** (Q6): STL decomposition (statsmodels), month×year heatmap, seasonal subseries, raw vs seasonally adjusted. Per product category.
- [ ] **Benchmark** (Q5): LU vs EU peers. Intra-EU share, partner HHI, product diversification, indexed growth (2015=100), map of the EU.
- [ ] **Outlier Radar** (optional, keep simple): one explainable rule (robust z-score on seasonally adjusted series) plus "new and vanishing" partners/products. Only if Q1–Q6 are solid.
- [ ] **Pitch coaching slot:** register on Day 1. Sessions run Thu 13:00–16:40.
- [ ] **Feature freeze at 18:00 Thursday.**

**Exit criterion:** all sample questions answerable through the general engine and presets; Outlier Radar only if time allows.

## Phase 4 — Polish, deploy, document (Thu evening → Fri 10:00)

- [ ] Deploy the app (Streamlit Community Cloud or similar). Keep a **local fallback** and a **recorded screen video**.
- [ ] README: purpose (WHAT/WHY), quick start (3 commands), screenshots, app link
- [ ] README **"For the jury" table:** each evaluation criterion → where to see it (app tab / file / command)
- [ ] `docs/DATA_CARD.md`: source, licence/attribution, coverage, caveats (BLEU, CN changes, confidentiality, asymmetries)
- [ ] `docs/METHODOLOGY.md`: significance filtering, STL settings, outlier rules, metric definitions
- [ ] Methodology notebook that reproduces the key figures
- [ ] Test a clean clone → pipeline → app on a second laptop

## Phase 5 — Pitch (Fri 16 Oct, 09:00–10:30)

**5-minute structure:**
1. **Hook (30 s):** one surprising Luxembourg trade fact from the data
2. **WHAT and WHY (30 s):** rich data locked in tables; why trade dependence matters for Luxembourg; who the tool is for
3. **Live demo (2 min 30 s):** story mode. Overview → partner drill-down to CN8 → seasonality (raw vs adjusted) → Outlier Radar → LU vs EU map
4. **Method and openness (45 s):** pipeline, statistical methods, EUPL, reproducibility
5. **Value for STATEC and close (45 s):** reusable for other datasets; next steps

- [ ] Deck ready by Thu night; **2+ timed rehearsals** Fri morning
- [ ] Backup: offline app + video + screenshots in the deck

---

## Priority guard (MoSCoW)

| Must | Should | Could | Won't (this time) |
|------|--------|-------|-------------------|
| Q1–Q4 in app, map, time slider, monthly+annual, reproducible repo, licence, pitch | Seasonality Lab (Q6), Benchmark (Q5), deployment | Simple Outlier Radar, Sankey, unit values, story mode | External data (GDP, population), forecasting/ML models, change-point algorithms, NL query box, services trade |

## Risk register

| Risk | Mitigation |
|------|------------|
| Bulk download slow or interrupted (11 GB) | Resumable script (skips files already in the manifest); filter while downloading; start on Day 1 |
| Data limitations misread (confidential codes, incomplete recent months, 2002 start) | Handled and documented in [DATA_CARD.md §4](DATA_CARD.md); visible footnotes in the app |
| Nomenclature breaks distort CN8 time series | Analyse long series at HS2/HS4; use CN8 for recent cross-sections; document it |
| Scope creep / over-complexity | Feature freeze Thu 18:00; follow the MoSCoW table; every feature must pass the WHAT/WHY test and be explainable in one sentence |
| Wrong or misunderstood product data | Product audit first (Phase 1); reconcile totals; document gaps in the Data Card |
| Live demo failure | Recorded video + local instance + screenshots |
| Misreading LU specifics (spikes, transit) | Label them as observations from the data, not causal claims; check with Kasra's EDA |
