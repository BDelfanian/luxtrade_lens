# Roadmap — The Outliers @ STATEC Hackathon 2026

**Hard deadline:** pitch on **Fri 16 Oct, 10:30** (5 minutes). The repository link is shared at the end of the hackathon.
Background, requirements and the concept are in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## Suggested roles (adjust freely)

| Person | Primary | Secondary |
|--------|---------|-----------|
| **Behrooz** | Data pipeline (download, cleaning, Parquet/DuckDB), analytics (seasonality, outliers) | Repo hygiene, reproducibility |
| **Mina** | App and visualisation (Streamlit/Plotly, maps, drill-down) | UX, deployment |
| **Kasra** | Insights and storytelling (EDA, benchmark, key findings) | Pitch deck, rehearsal, demo video |

Everyone reviews each other's work and joins rehearsals.

---

## Phase 0 — Setup (Wed 14 Oct, 10:30–12:00)

- [ ] Repository structure (below), `.gitignore` for `data/raw/`, **LICENSE (EUPL-1.2)**, README skeleton
- [ ] `environment.yml` / `requirements.txt` (python ≥3.11, pandas, pyarrow, duckdb, plotly, streamlit, statsmodels, requests)
- [ ] **Validate data access:** test the SDMX API query for `LU`; check the dimension codes (reporter, partner, product, flow, indicators); estimate data volumes
- [ ] Decide the scope: years (1999→latest), reporters for benchmarking (all EU27 at TOTAL/HS2 level, LU only at CN8)

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

## Phase 1 — Data foundation (Wed 14 Oct, 14:00–18:00)

- [ ] `download.py`: LU × all partners × flows {1,2} × products (TOTAL, HS2, HS4, HS6, CN8) × M and A
- [ ] `download.py`: benchmark set of EU27 reporters × TOTAL/HS2 × partner aggregates (intra/extra/world)
- [ ] `process.py`: tidy long table → Parquet; product hierarchy table (CN8→HS6→HS4→HS2) with labels; partner table with ISO codes and labels for the maps
- [ ] Data-quality checks: totals vs sum of children, confidential codes, missing months, the 1999 BLEU start
- [ ] Quick EDA notebook: top partners, top chapters, monthly series. **Write down 5 candidate insights.**
- [ ] (Parallel) App skeleton with navigation and dummy charts

**Exit criterion:** clean Parquet + first EDA insights + app shell running locally.

## Phase 2 — Core modules (Thu 15 Oct, 09:00–13:00)

- [ ] **Overview** (Q1, Q2): KPI tiles, partner/chapter evolution, rank bump chart
- [ ] **Partner Explorer** (Q1, Q4): choropleth, partner profile, HS2→CN8 drill-down with Pareto / Top-N + "Other"
- [ ] **Product Explorer** (Q2, Q3): hierarchy selector → partner ranking + map
- [ ] Global filters: flow (import/export/balance), frequency (M/A), period, metric (value/quantity/unit value)

**Exit criterion:** Q1–Q4 answerable end-to-end in the app.

## Phase 3 — Differentiators (Thu 15 Oct, 14:00–18:00)

- [ ] **Seasonality Lab** (Q6): STL decomposition (statsmodels), month×year heatmap, seasonal subseries, raw vs seasonally adjusted. Per product category.
- [ ] **Benchmark** (Q5): LU vs EU peers. Intra-EU share, partner HHI, product diversification, indexed growth (2015=100), map of the EU.
- [ ] **Outlier Radar** (signature): robust z-score / STL residuals for spikes; change-point detection for structural breaks; "new and vanishing" partners/products; unit-value anomalies
- [ ] **Pitch coaching slot:** register on Day 1. Sessions run Thu 13:00–16:40.
- [ ] **Feature freeze at 18:00 Thursday.**

**Exit criterion:** all six questions plus the Outlier Radar demo-ready.

## Phase 4 — Polish, deploy, document (Thu evening → Fri 10:00)

- [ ] Deploy the app (Streamlit Community Cloud or similar). Keep a **local fallback** and a **recorded screen video**.
- [ ] README: purpose, quick start (`make all` or 3 commands), screenshots, app link
- [ ] `docs/DATA_CARD.md`: source, licence/attribution, coverage, caveats (BLEU, CN changes, confidentiality, asymmetries)
- [ ] `docs/METHODOLOGY.md`: significance filtering, STL settings, outlier rules, metric definitions
- [ ] Methodology notebook that reproduces the key figures
- [ ] Test a clean clone → pipeline → app on a second laptop

## Phase 5 — Pitch (Fri 16 Oct, 09:00–10:30)

**5-minute structure:**
1. **Hook (30 s):** one surprising Luxembourg trade fact from the data
2. **Problem (30 s):** rich data, but hard to explore. The 6 questions.
3. **Live demo (2 min 30 s):** story mode. Overview → partner drill-down to CN8 → seasonality (raw vs adjusted) → Outlier Radar → LU vs EU map
4. **Method and openness (45 s):** pipeline, statistical methods, EUPL, reproducibility
5. **Value for STATEC and close (45 s):** reusable for other datasets; next steps

- [ ] Deck ready by Thu night; **2+ timed rehearsals** Fri morning
- [ ] Backup: offline app + video + screenshots in the deck

---

## Priority guard (MoSCoW)

| Must | Should | Could | Won't (this time) |
|------|--------|-------|-------------------|
| Q1–Q4 in app, map, time slider, monthly+annual, reproducible repo, licence, pitch | Seasonality Lab (Q6), Benchmark (Q5), deployment | Outlier Radar depth, Sankey, unit values, NL query box, story mode | External data (GDP, population), forecasting models, services trade |

## Risk register

| Risk | Mitigation |
|------|------------|
| API slow / rate-limited / large CN8 volumes | Filter queries to LU; cache Parquet early; fall back to bulk files; limit CN8 to recent years if needed |
| Nomenclature breaks distort CN8 time series | Analyse long series at HS2/HS4; use CN8 for recent cross-sections; document it |
| Scope creep | Feature freeze Thu 18:00; follow the MoSCoW table |
| Live demo failure | Recorded video + local instance + screenshots |
| Misreading LU specifics (spikes, transit) | Label them as observations from the data, not causal claims; check with Kasra's EDA |
