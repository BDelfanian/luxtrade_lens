# Roadmap — The Outliers @ STATEC Hackathon 2026

**Hard deadline:** pitch on **Fri 16 Oct, 10:30** (5 minutes). The repository link is shared at the end of the hackathon. **Feature freeze: Thu 15 Oct, 18:00.**
Background and requirements: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · Architecture: [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md) · Data: [DATA_CARD.md](DATA_CARD.md)

> **Coach principles. Check them at every stand-up:**
> 1. The questions are samples, so build a **general who × what × when × flow tool**. The ask box, the presets and the filters all drive the same `QuerySpec`.
> 2. **Product data comes first**, including labels in EN/FR/DE, since entity resolution depends on them.
> 3. Always ask **WHAT problem, and WHY** it matters ([PROJECT_CONTEXT §1a](PROJECT_CONTEXT.md)).
> 4. **Make grading easy. Avoid complexity.** LLMs translate, code computes. Every step can be explained in one sentence.

## Roles

| Person | Primary | Secondary |
|--------|---------|-----------|
| **Behrooz** | **Solution design and integration:** `QuerySpec`, LangGraph graph and supervisor, interpreter (incl. session context) / optimiser / SQL fallback / insight prompts, rewrite validation, SQL guard, grounding check, run records, sessions and traceability | README, methodology, reproducibility, reviews |
| **Mina** | **Solution components:** analytics tools (rankings, composition, significance, seasonality, forecast, benchmark), chart selector and Plotly builders, pivot, Streamlit UI (conversation thread, answer card, suggestion chips, session history, Refine) | Deployment, UX |
| **Kasra** | **All data tasks:** bulk download, data model, cleaning, validation, DATA_CARD, **semantic layer** (DuckDB views, `dim_*` with EN/FR/DE labels, `meta_coverage`), **limitations registry**, expected answers for the golden questions | EDA and data insights |

Everyone reviews each other's work and joins rehearsals.

---

## Phase 0 — Setup (Wed 14 Oct, 10:30–12:00)

- [x] Repository structure, `.gitignore` for `data/raw/`, **LICENSE (EUPL-1.2)**, README skeleton
- [x] `environment.yml` / `requirements.txt` (Python 3.12, pinned)
- [x] **Validate data access:** API and bulk both tested; **bulk chosen** (see [DATA_CARD.md](DATA_CARD.md))
- [x] Decide the scope: **2002 → latest complete month**; LU at full CN8 detail; EU27 reporters as HS2 summaries for benchmarking
- [x] **Solution design:** natural-language questions → agent graph → data product + insight + trace ([SOLUTION_DESIGN.md](SOLUTION_DESIGN.md))

## Phase 1 — Foundations in parallel (Wed 14 Oct, 14:00–18:00)

**Kasra (data, product first)**
- [ ] **Product-dimension audit** ([PROJECT_CONTEXT §7a](PROJECT_CONTEXT.md)):
  - levels × years
  - labels in **EN/FR/DE**
  - hierarchy reconciliation
  - confidential and special codes
  - code changes
  - quantity coverage

  Write the findings into `docs/DATA_CARD.md` right away.
- [ ] `ingest/download.py`: stream the 295 monthly files. For each: download → manifest (SHA-256) → extract → keep LU + EU27 HS2 summaries → delete raw. **Start it early in the background (~1–1.5 h).**
- [ ] `process/`: tidy Parquet + `dim_product`, `dim_partner` (with ISO-3 for maps) + reconciliation test (detail + confidential = `TOTAL`)
- [x] `semantic/build.py`: the six views in [SOLUTION_DESIGN §5.4](SOLUTION_DESIGN.md#54-query-builder-spec-first-sql-fallback-nl2sql), including `meta_coverage` (latest complete month)
- [x] Placeholder data in the exact contract (`python -m luxtrade.process.placeholder`), also used by the tests

**Behrooz (design and integration)**
- [x] Freeze the `QuerySpec` and run-record schemas (Pydantic) and the defaults table
- [x] LangGraph graph: supervisor + 7 nodes, end-to-end on placeholder data
- [x] LLM wrapper with two providers (OpenAI **`gpt-4.1-mini`** default, Anthropic `claude-sonnet-4-6`), strict structured output, timeouts, offline fallback; `.env` handling
- [ ] Top up API credit, then run the golden evaluation on the live model
- [x] Session model: `session_id`, turn records, context rebuilt from run records
- [x] Dependencies: add `langgraph`, `anthropic`, `sqlglot`, `pydantic`, `python-dotenv`, `pyyaml`; regenerate `requirements.txt`
- [ ] Remove `ruptures` (unused) and decide on `sdmx1` (API cross-check only)

**Mina (components)**
- [ ] Streamlit shell: conversation thread (`st.chat_message`) with answer cards (Insight / Chart / Table / Pivot / How we got this), ask box + "Optimise" button + suggestion chips, sidebar (presets, sessions & history, data status), all against dummy run records
- [ ] Chart selector rules table + the first builders (line, bar, choropleth, KPI)

**Exit criterion:** a question typed in the UI flows through stub nodes to a rendered chart on fixture data; the bulk download is running.

## Phase 2 — Core answer path (Thu 15 Oct, 09:00–13:00)

- [ ] **Interpreter** with `lookup_entity` over EN/FR/DE labels → `QuerySpec` + stated assumptions (Behrooz)
- [ ] **Spec → SQL compiler** for ranking, time series, composition, drill-down and product → partner + **SQL guard** (Behrooz, with Kasra for the views)
- [ ] **Limitation guard** v1: L01, L02, L03, L04, S01, S02 (Kasra: registry; Behrooz: guard node)
- [ ] Analytics tools: rankings, shares, YoY, Pareto / Top-N + Other + Confidential (Mina)
- [ ] **Insight writer** + fact sheet + grounding check + template fallback (Behrooz)
- [ ] Run records with `run_id`, `result_hash`, `session_id`, `turn`, `followup_of`, `origin`; session history panel with search, resume, and `?run=` / `?session=` deep links (Behrooz + Mina)
- [ ] **Follow-ups v1:** session context (last 5 turns: spec + result entities) in the interpreter; inherited fields shown on the card + "Start fresh"; `view_only` re-render (Behrooz + Mina)
- [ ] **Question optimiser v1:** automatic route for core ambiguity, unresolved entities and blocking limitations → three rewrites with specs → validation (codes, guard, SQL compile) → chips + "Ask more specifically" (Behrooz: node + validation; Mina: chips UI)
- [ ] Golden questions v1: 12 questions (Q1–Q4 in EN/FR/DE) + 2 follow-up chains + 3 vague questions, with expected answers (Kasra)

**Exit criterion:** Q1–Q4 asked in EN, FR and DE produce correct, traced answers with insights on real data; a follow-up ("and for imports?") works; a vague question gets three valid rewrites.

## Phase 3 — Differentiators (Thu 15 Oct, 14:00–18:00)

- [ ] **Seasonality** (Q6): STL, month × year heatmap, raw vs adjusted (Mina)
- [ ] **Benchmark** (Q5): LU vs EU reporters at HS2, indexed growth, EU map (Mina + Kasra)
- [ ] **Projection**: ETS + seasonal-naive back-test, intervals, eligibility rules, "Show projection" button (Mina)
- [ ] **Refine** controls → spec → SQL re-run without the LLM; pivot table (Mina)
- [ ] Supervisor conflict rules + retries ([SOLUTION_DESIGN §5.1](SOLUTION_DESIGN.md#51-supervisor-graph-router-deterministic)); the remaining limitation rules (Behrooz + Kasra)
- [ ] Optimiser v2: the on-demand "Optimise" button and "Not what you meant?" link; routes for SQL failure and empty results (Behrooz + Mina)
- [ ] LLM SQL fallback, only if Phase 2 is solid (Behrooz)
- [ ] Golden set → 24 questions incl. 4 that must be refused + 4 follow-up chains + 6 vague questions; run `python -m luxtrade.agents.evaluate` (all)
- [ ] **Pitch coaching slot:** sessions run Thu 13:00–16:40
- [ ] **Feature freeze at 18:00 → tag `v0.1-demo`**

**Exit criterion:** all sample questions answerable through the ask box *and* the presets; evaluation scores recorded.

### Cut order if time runs out (cut from the top)

1. LLM SQL fallback (the spec path covers Q1–Q6)
2. Outlier flags
3. On-demand "Optimise" button and "Not what you meant?" (keep the automatic optimiser route)
4. Pivot table (the table view stays)
5. Follow-ups that reference result positions ("the second one"); keep the field changes ("and imports?", "only Germany")
6. Annual-series projection (keep monthly)
7. Benchmark map (keep the bars)

**Never cut:** the limitation guard, grounding check, rewrite validation, the inherited-context notice, trace tab, run/session IDs, presets and offline replay. They are the core of the traceability story.

## Phase 4 — Polish, deploy, document (Thu evening → Fri 10:00)

- [ ] Deploy the app (Streamlit Community Cloud or similar) with the API key in secrets. Keep a **local fallback** and record the **demo runs** (`demo/runs/`) so the demo replays offline
- [ ] Record a screen video of the demo as a second backup
- [ ] README: purpose (WHAT/WHY), quick start, screenshots, app link, **"For the jury" table**, evaluation scores
- [ ] `docs/DATA_CARD.md` final pass; limitation IDs in sync with `limitations.yaml`
- [ ] `docs/METHODOLOGY.md`:
  - significance filtering
  - STL and ETS settings
  - back-test
  - grounding rules
  - metric definitions
- [ ] Methodology notebook that reproduces the key figures
- [ ] Test a clean clone → pipeline → app on a second laptop, with and without an API key

## Phase 5 — Pitch (Fri 16 Oct, 09:00–10:30)

**5-minute structure:**
1. **Hook (30 s):** one surprising Luxembourg trade fact from the data
2. **WHAT and WHY (30 s):** rich data locked in tables; a ministry analyst needs an answer now, in their language
3. **Live demo (2 min 30 s):**
   - Ask in **French** → map + insight → open **"How we got this"** (assumptions, SQL, limits)
   - Follow up: *"Et pour les importations ?"* → same view for imports; "Kept from your previous question" is visible
   - Follow up: *"Zoom in on the second one"* → drill-down from that partner to CN8
   - Ask in **German** about a product's trend → seasonally adjusted series + **projection** with an uncertainty band
   - Ask a **vague** question (*"How is our trade doing?"*) → three validated rewrites → click one
   - Ask an **out-of-scope** question (GDP) → clear refusal + answerable alternatives
   - Paste a **session ID** → the whole thread is back; ✅ re-verify one answer
4. **Method and openness (45 s):**
   - "LLMs translate, code computes": the graph on one slide
   - evaluation scores
   - EUPL licence and reproducibility
5. **Value for STATEC and close (45 s):** works for any Comext-style table; next steps (EU-hosted model, more datasets)

- [ ] Deck ready by Thu night; **2+ timed rehearsals** Fri morning
- [ ] Backup: offline replay of demo runs + video + screenshots in the deck

---

## Priority guard (MoSCoW)

| Must | Should | Could | Won't (this time) |
|------|--------|-------|-------------------|
| Ask box (EN/FR/DE) → `QuerySpec` → spec-compiled SQL; Q1–Q4 + presets; map; automatic chart choice; interactive Plotly + table; grounded 4–5 sentence insight; limitation guard; **follow-ups within a session**; **automatic question optimiser (3 validated rewrites)**; trace tab; run/session IDs + history + offline replay; reproducible repo, licence, pitch | Seasonality (Q6), Benchmark (Q5), projections (ETS + baseline), Refine controls, on-demand "Optimise" button, golden-set evaluation, deployment | LLM SQL fallback, pivot table, positional follow-ups ("the second one"), outlier flags, Sankey, unit values | External data (GDP, population, prices); ML or deep-learning forecasts; causal explanations; change-point algorithms; services trade; memory across sessions; Luxembourgish |

## Risk register

| Risk | Mitigation |
|------|------------|
| Bulk download slow or interrupted (11 GB) | Resumable script (skips files already in the manifest); filter while downloading; start on Day 1 |
| Agent scope is too big for 1.5 days | Spec-first design: presets and Refine work without the LLM; strict cut order (Phase 3); stubs end-to-end on Day 1 |
| LLM gives wrong numbers or invented facts | Numbers come only from SQL or Python; grounding check; template fallback; golden-set evaluation |
| LLM picks wrong entities or SQL | Codes only from the label lookup; SQL templates for known intents; SQL guard; trace shows the SQL |
| Network, API key or rate limit fails during the live demo | Offline replay of recorded demo runs by run ID; presets without the LLM; local instance; video |
| Latency (2 LLM calls per answer, up to 4 with optimiser or SQL fallback) | `gpt-4.1-mini` (fast, low cost) for every step; Refine and presets skip the LLM; stored runs open instantly; live step progress in the UI |
| Follow-up picks up the wrong context | Structured context only (specs + result entities, last 5 turns); inherited fields shown on the card + "Start fresh"; follow-up chains in the golden set |
| Optimiser suggests questions that can't be answered | Every rewrite is validated (codes, limitation guard, SQL compile) before it's shown; presets fill empty slots |
| Data limitations misread (confidential codes, incomplete recent months, 2002 start) | Limitations registry fires automatically; [DATA_CARD.md §4](DATA_CARD.md); captions |
| Nomenclature breaks distort CN8 time series | Long series at HS2/HS4; rule L05 warns and suggests a coarser level |
| Forecasts over-trusted | Eligibility rules, baseline check, intervals, "projection" wording (S05) |
| Wrong or misunderstood product data | Product audit first (Phase 1); reconcile totals; document gaps in the Data Card |
| Misreading LU specifics (spikes, transit) | Insights describe, never explain causes (S04); volatility warning (L11) |
