# Engineering Guidelines — The Outliers

These are the rules we follow while building the project. They support the jury criteria: **Reproducibility & Openness** and a **Functional PoC**. They are sized for a 2.5-day hackathon: strict where it protects the demo and the audit trail, light everywhere else.

> **Golden rule:** a fresh clone must go `setup → pipeline → app` with no manual steps. Every number shown in the app must be traceable to the SQL that produced it, the processed files, and the Eurostat bulk files behind them, all recorded in the answer's run record.

> **LLM rule:** LLMs translate, code computes. An LLM (`gpt-4.1-mini` by default, or `claude-sonnet-4-6`; see `agents/llm.py`) may interpret a question in its session context, suggest rewrites of vague questions, write SQL for unusual questions, and phrase an insight. It never produces a number, picks a chart, decides a limitation, or shows a rewrite that code hasn't validated. See [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md).

> **Simplicity rule (coach):** before writing code, ask *what problem does this solve, and why does it matter?* Choose the simplest solution that answers it. Prefer standard charts, transparent rules and fewer features done well. If a method can't be explained to the jury in one sentence, don't ship it.

---

## 1. Architecture

### 1.1 Layers (one-way dependencies)

```
 Eurostat bulk files
        │
 ┌──────▼──────┐  ┌─────────────┐  ┌─────────────┐
 │   ingest    │─▶│   process   │─▶│  semantic   │  DuckDB views, dim_* labels,
 │ (download,  │  │ (clean,     │  │ (read-only  │  meta_coverage, limitations.yaml
 │  manifest)  │  │  hierarchy, │  │  SQL layer) │
 └─────────────┘  │  validate)  │  └──────┬──────┘
   data/raw/      └─────────────┘         │
                  data/processed/         │
                  (Parquet = CONTRACT)    │
          ┌───────────────┬───────────────┼───────────────┐
   ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
   │  analytics  │ │     viz     │ │   agents    │ │    runs     │
   │ pure funcs: │ │ chart       │ │ LangGraph:  │ │ run records,│
   │ rankings,   │ │ selector,   │ │ supervisor, │ │ run_id,     │
   │ STL, ETS,   │ │ Plotly      │ │ nodes, SQL  │ │ replay,     │
   │ benchmark   │ │ builders    │ │ guard, LLM  │ │ re-verify   │
   └─────────────┘ └─────────────┘ └──────┬──────┘ └──────┬──────┘
                                          │               │
                                   ┌──────▼───────────────▼──────┐
                                   │   app (Streamlit, UI only)  │
                                   └─────────────────────────────┘
```

- **Dependencies point one way.** `agents` uses `semantic`, `analytics`, `viz` and `runs`. `app` uses `agents` and `runs`. Nothing imports `app`. The app never calls Eurostat or the LLM directly.
- **`analytics` and `viz` have pure functions:** DataFrame in, DataFrame / figure / value out. No I/O and no LLM calls. They are easy to test and easy to reuse in notebooks.
- **All LLM calls live in `agents/llm.py`** behind one small interface (`structured_call(prompt, schema, effort)`), so tests can swap in a fake LLM.
- **All SQL goes through `agents/sql_guard.py`**, both compiled and LLM-written, against a read-only DuckDB connection.
- **The app layer holds no business logic.** It renders run records and sends `QuerySpec`s or questions to the graph. If a computation appears in a page file, move it.
- **Notebooks are for exploring and showing results.** Code worth keeping moves into `src/` before it is used anywhere else.

### 1.2 Package layout

```
src/luxtrade/
├── config.py          # paths, constants, settings (single source of truth)
├── logging_setup.py   # logging configuration
├── ingest/            # download.py, manifest.py
├── process/           # clean.py, hierarchy.py, validate.py, build.py (real pipeline, Kasra)
│                      # placeholder.py + nomenclature.py (synthetic data in the contract)
├── semantic/          # build.py (DuckDB views), layer.py (read-only queries, coverage,
│                      # labels), catalog.py (schema for the LLM), lookup.py (EN/FR/DE
│                      # label search), limitations.yaml
├── analytics/         # rankings.py, composition.py, significance.py,
│                      # seasonality.py, forecast.py, benchmark.py, outliers.py
├── viz/               # selector.py (rules table), charts.py (Plotly), pivot.py
├── agents/            # spec.py (QuerySpec, Interpretation), defaults.py, graph.py,
│                      # supervisor.py, service.py (Assistant), interpret.py, context.py,
│                      # optimise.py, guard.py, compile_sql.py, sql_guard.py, analyse.py,
│                      # facts.py, insight.py, grounding.py, presets.py, llm.py, prompts/,
│                      # evaluate.py
├── runs/              # store.py (run records, run_id, result_hash, replay),
│                      # sessions.py (session_id, turns, resume)
└── app/               # Home.py (layout, sidebar, thread) + components.py (answer card)
tests/                 # mirrors src/luxtrade/ one-to-one; tests/golden/ for the question set
```

### 1.3 Data contract (lets work happen in parallel)

> **Draft. Kasra owns the final data model; Behrooz reviews it for fit with the overall design.** The columns below are a starting point. See [DATA_CARD §4b](DATA_CARD.md) for the measured missing-value profile and row-grain findings.

`data/processed/` is the **interface between the pipeline and the app**. The schema is fixed. Changes to it need agreement from the team (see §7).

**`trade.parquet`**, long format, one row per observation:

| column | type | notes |
|---|---|---|
| `freq` | str | `M` or `A` |
| `period` | date | first day of month or year |
| `reporter` | str | ISO-2 / Eurostat code, e.g. `LU` |
| `partner` | str | Eurostat partner code |
| `flow` | str | `import` or `export` |
| `product` | str | `TOTAL` or HS/CN code as a **string** (keep leading zeros!) |
| `level` | int8 | 0 = TOTAL, 2, 4, 6, 8 (digits) |
| `trade_type` | str | `intra` or `extra` (from bulk `TRADE_TYPE`) |
| `is_confidential` | bool | masked code such as `27XXXXXX` (see [DATA_CARD §4.2](DATA_CARD.md)) |
| `value_eur` | float64 | bulk `VALUE_EUR` |
| `qty_kg` | float64 | bulk `QUANTITY_KG`; null when 0 or missing |

Lookup tables:
- `products.parquet`: `product`, `level`, `parent`, `label`, **`label_en`, `label_fr`, `label_de`**, `section`, `is_confidential`, plus `sitc`, `bec`, `bec5`, `cpa` from the bulk files.
- `partners.parquet`: `partner`, `label`, **`label_en`, `label_fr`, `label_de`**, `iso3`, `is_aggregate`, **`is_eu27_2020`, `is_special`**.

The EN/FR/DE labels are what let the assistant understand questions in all three languages.

Two more files:
- `benchmark.parquet`: EU reporter summaries, with columns `reporter`, `trade_type`, `flow`, `hs2`, `period` and `value_eur`.
- `meta.json`: `extraction_date`, `source` and `is_placeholder`.

**Placeholder data:** `python -m luxtrade.process.placeholder` writes all five files in exactly this contract with synthetic values (`is_placeholder: true`), so the semantic layer, agents and app run before the real pipeline exists. Kasra's pipeline replaces these files. Nothing else changes.

Until the real pipeline is ready, the tests generate a **small placeholder set with the same schema** (`process/placeholder.py`, `SMALL` config) in a temporary folder.

**Second contract: the semantic layer.** The agents never read Parquet files directly. They query the DuckDB views listed in [SOLUTION_DESIGN §5.4](SOLUTION_DESIGN.md#54-query-builder-spec-first-sql-fallback-nl2sql) (`v_lu_trade`, `v_lu_trade_hs2`, `v_eu_reporters_hs2`, `dim_product`, `dim_partner`, `meta_coverage`). View and column names, and their one-line descriptions in `semantic/catalog.py`, are part of the contract, because the LLM prompts and the SQL templates depend on them.

**Third contract: `QuerySpec`, `Interpretation`, the run record and the session file** (`agents/spec.py`, `runs/store.py`, `runs/sessions.py`). The UI, presets, follow-ups, optimiser, Refine controls, SQL compiler and golden tests all depend on them. Changes need team agreement (§7).

---

## 2. Maintainability

- **Style:** we use `ruff` for both linting and formatting, configured in `pyproject.toml`. Run `ruff check --fix . && ruff format .` before every commit.
- **Naming:** use `snake_case` functions that start with a verb (`compute_hhi`, `load_trade`) and descriptive column names (`value_eur`, not `v`).
- **Type hints** on every public function. **Docstrings** (one line plus Args/Returns when it isn't obvious) on every public function.
- **No magic values.** Codes like `"LU"`, `"EU27_2020_INTRA"`, thresholds and paths live in `config.py`.
- **Small functions** with one responsibility. If a function needs scrolling, split it.
- **No duplicated logic.** Shared transformations belong in `process/` or `analytics/`, not copied across pages.
- **Dependencies:** add a new one only when it's needed. Update `requirements.in` and `requirements.txt` together (see README).
- **No dead code in `main`.** Delete experiments. Git history keeps them.

## 3. Monitorability

Because the pipeline is a batch job and the app is a single demo, "monitoring" here means **we always know what ran, how long it took, and whether the data is healthy.**

- **Logging, not `print`.** Use the standard `logging` module, configured once in `logging_setup.py`:
  - Format: `timestamp | level | module | message`
  - Output goes to the console **and** `logs/pipeline.log` (git-ignored).
  - `INFO` marks each pipeline step (start, end, row counts, duration). `WARNING` covers data anomalies. `ERROR` covers failures, always with context (query, file, period).
- **Timing:** every pipeline step logs its duration (a small `@timed` decorator).
- **Agent runs:** every graph node logs `run_id | node | duration | outcome` (ok / retry / fallback / blocked). Every LLM call also logs the model, effort, input/output tokens and latency. The same data goes into the run record's `trace`, so the UI's "How we got this" tab and the logs never disagree. Logs go to `logs/app.log`.
- **Data-quality report:** `process/validate.py` writes `data/processed/quality_report.json` with:
  - row counts per freq and level
  - the period range
  - missing months
  - totals vs sum-of-children gaps (confidential trade)
  - duplicate keys
  - negative values
- **In-app status:** the app footer shows the **data vintage** (extraction date) and the **last processed timestamp**. A small *About / Data status* page renders the quality report.
- **Fail loudly in the pipeline, gracefully in the app.** Pipeline validation errors stop the run. The app shows a friendly message instead of a stack trace.

## 4. Auditability

Every figure must answer: *where did this number come from, and can I regenerate it?*

- **Run manifest:** each download writes `data/raw/manifest.json` with:
  - the source URL or query and its parameters
  - the UTC timestamp
  - the HTTP status, file size and **SHA-256**
  - the row count
  - the **git commit** of the code that ran
- **Lineage:** `build.py` records which raw files went into each processed file (`data/processed/lineage.json`).
- **Raw is never modified.** Raw files are immutable. All cleaning happens in code, never by hand in Excel.
- **Deterministic outputs:** sort before writing, fix random seeds, and pin dependencies.
- **Methods are documented:** `docs/METHODOLOGY.md` defines every metric (HHI, Pareto cut, STL and ETS parameters, back-test, outlier rules, grounding rules) and every decision (e.g. "series start in 2002 because the bulk files start there; LU-only data exists from 1999", [DATA_CARD §4.1](DATA_CARD.md)).
- **Run records:** every answer is saved as `data/runs/<run_id>.json`. It holds the question, `session_id`, turn, `followup_of` and inherited fields, `origin` (ask / follow-up / optimiser / refine / preset), any optimiser suggestions, `QuerySpec` and assumptions, the limitations fired, the executed SQL, the `result_hash`, the methods and parameters, the data vintage, the node trace, the LLM model and tokens, and the git commit. `run_id` and `result_hash` follow [SOLUTION_DESIGN §6](SOLUTION_DESIGN.md#6-traceability-where-does-this-answer-come-from). Run records are never edited. A re-run creates a new record linked to its parent.
- **Prompts are code:** prompts live in `agents/prompts/` under version control. Changing a prompt means re-running the golden evaluation (§5).
- **Every chart cites its source** in a caption: *"Source: Eurostat, Comext DS-045409, extracted YYYY-MM-DD; calculations by The Outliers."*
- **Commit history tells the story:** small, descriptive commits (see §6). No force-push on `main`.

## 5. Testing — one test module per functionality

- **Mirror structure:** `src/luxtrade/analytics/seasonality.py` → `tests/analytics/test_seasonality.py`, and so on.
- **Framework:** `pytest`. Shared synthetic fixtures live in `tests/conftest.py` and `tests/fixtures/`.
- **What to test** (in priority order):
  1. **analytics:** rankings, shares, HHI, Pareto/Top-N + "Other" (values must still sum to the parent!), seasonal adjustment (on a known synthetic seasonal series), outlier flags (on an injected spike).
  2. **process:** product codes keep their leading zeros; hierarchy parent mapping; flow code mapping; schema matches the contract; no duplicate keys.
  3. **agents** (with a **fake LLM** that returns recorded responses, so there are no network calls):
     - `sql_guard` rejects `DROP`, `ATTACH`, `COPY`, `read_parquet(...)`, multiple statements and unknown views
     - the spec → SQL compiler matches hand-written SQL for each intent
     - limitation rules fire on crafted specs (pre-2002, GDP, CN8 over 10 years, …)
     - grounding catches a changed number, including FR/DE number formats
     - supervisor routing: each conflict row in [SOLUTION_DESIGN §5.1](SOLUTION_DESIGN.md#51-supervisor-graph-router-deterministic) has a test
     - optimiser validation drops rewrites with unknown codes, blocked limitations or SQL that fails the guard
     - follow-up resolution: "and for imports?", "only Germany" and "as a table" produce the expected spec or `view_only` from a stored previous turn; an unrelated question starts a new topic
  4. **viz and runs:** the chart selector rules (table-driven test, one case per row); `run_id` is deterministic; replay reproduces the `result_hash`.
  5. **ingest:** query/URL builder; manifest content. **No live network calls in tests.** Mock the HTTP layer.
  6. **app:** smoke test only. Each page imports and renders against the fixture and a stored run record (`streamlit.testing.v1.AppTest`).
- **Golden evaluation** (`tests/golden/questions.yaml`: about 24 questions in EN/FR/DE including ones that must be refused, follow-up chains, and vague questions for the optimiser): `python -m luxtrade.agents.evaluate` calls the real LLM, so it is marked `network`. It reports spec accuracy (incl. follow-up turns), SQL success, numeric correctness, limitation behaviour and optimiser routing / suggestion validity. Run it after every prompt change and before the freeze. The scores go into the README.
- **Mark** slow or network tests with `@pytest.mark.slow` or `@pytest.mark.network`. They are skipped by default.
- **Rules:**
  - A bug fix comes with a test that reproduces the bug.
  - `pytest` must pass before merging to `main`.
  - Target **coverage of the logic, not 100% of lines**. Every analytics function needs at least one test.

## 6. Git workflow

- **Branches:** `main` must always run (it's demoable). Work happens on short-lived branches named `feat/<area>-<topic>`, `fix/<topic>`, `docs/<topic>`, `data/<topic>`.
- **Commits:** follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat(app): add partner choropleth`, `fix(process): keep leading zeros in CN8`, `test(analytics): cover pareto cut`).
- **Merging:**
  - Open a PR into `main`. **One teammate reviews it** (at least a quick skim) before merging.
  - A PR should be small, ideally under 300 changed lines.
  - Rebase or merge `main` into your branch often to avoid painful conflicts.
- **Never commit:** raw data, secrets, `.venv`, large binaries, HTML exports (`.gitignore` enforces most of this).
- **Tags:** tag `v0.1-demo` at the feature freeze (Thu 18:00) and `v1.0-pitch` before the pitch.

## 7. Task split and ownership

Ownership means *you are responsible for it and you review changes to it*, not that nobody else may touch it.

| Area | Owner | Reviewer | Paths |
|---|---|---|---|
| **Solution design:** architecture, module boundaries, interfaces between layers, integration, technical decisions, these guidelines | **Behrooz** | All | `docs/GUIDELINES.md`, `src/luxtrade/config.py`, `logging_setup.py` |
| **Agent graph and traceability:** `QuerySpec`, supervisor, interpreter + session context, question optimiser + validation, SQL compiler + guard, LLM wrapper, prompts, insight + grounding, run records and sessions, evaluation harness | **Behrooz** | Mina | `agents/`, `runs/`, `tests/agents/`, `tests/runs/`, `docs/SOLUTION_DESIGN.md` |
| Methodology, README, reproducibility test, code-review coordination | **Behrooz** | All | `docs/METHODOLOGY.md`, root |
| **All data tasks:** bulk download + manifest, data model, data contract, cleaning, missing-value rules, validation, DATA_CARD | **Kasra** | Behrooz | `ingest/`, `process/`, `tests/ingest/`, `tests/process/`, `docs/DATA_CARD.md` |
| **Semantic layer:** DuckDB views, `dim_*` with EN/FR/DE labels, label lookup, `meta_coverage`, **limitations registry**, expected golden answers | **Kasra** | Behrooz | `semantic/`, `tests/semantic/`, `tests/golden/` |
| EDA notebooks and data insights | **Kasra** | All | `notebooks/` |
| **Solution components:** analytics tools (rankings, composition, significance drill-down, benchmark, seasonality, forecast, outliers) | **Mina** | Behrooz | `analytics/`, `tests/analytics/` |
| **Solution components:** chart selector, Plotly builders, pivot; app shell (conversation thread, answer card, suggestion chips, session history, Refine, data status), deployment | **Mina** | Behrooz | `viz/`, `app/`, `tests/viz/`, `tests/app/` |
| Pitch deck and rehearsal | **All** (lead to be decided) | All | `docs/pitch/` |

**Working agreements:**
- **Shared interfaces need agreement:** the data contract and semantic views (§1.3), `QuerySpec` and the run record, `config.py`, and `limitations.yaml` IDs (they must match [DATA_CARD §4](DATA_CARD.md)). Announce the change and get one teammate's OK.
- **Parallel by default:**
  - Mina builds components against `tests/fixtures/` and dummy run records.
  - Kasra runs the download and finalises the data model and views.
  - Behrooz keeps the interfaces (data contract, semantic views, `QuerySpec`, run record) stable, so all three sides meet without rework. They swap to real data with no code changes.
- **Stand-ups (5 min):** at the start of each block (09:00, 14:00) and before leaving.
  - What did I finish?
  - What am I doing next?
  - What's blocking me?
- **Task board:** GitHub Issues/Projects (or a shared checklist) mirroring [ROADMAP.md](ROADMAP.md). Every task has one owner and a size (S/M/L).
- **Blocked for more than 30 minutes?** Say so right away.

## 8. Definition of Done (per task)

- [ ] The feature passes the WHAT/WHY test and is the simplest workable solution
- [ ] Code sits in the right layer and module, with type hints and docstrings
- [ ] `ruff check` and `ruff format` are clean
- [ ] Tests are added or updated and `pytest` passes
- [ ] Logging covers new pipeline steps, and charts carry a source caption
- [ ] For agent and prompt changes, the golden evaluation was re-run and no score dropped
- [ ] Docs are updated if behaviour, metrics or the data contract changed
- [ ] The PR is reviewed and merged, and `main` still runs end-to-end

## 9. Standard commands

```bash
ruff check --fix . && ruff format .      # lint + format
pytest                                   # fast tests
pytest -m "slow or network"              # optional heavier tests
python -m luxtrade.process.placeholder   # placeholder data + semantic layer (until real data)
python -m luxtrade.ingest.download       # fetch raw data + manifest
python -m luxtrade.process.build         # build processed Parquet + quality report
python -m luxtrade.semantic.build        # (re)build the DuckDB semantic layer
python -m luxtrade.agents.evaluate       # golden question set (calls the LLM; needs ANTHROPIC_API_KEY)
streamlit run src/luxtrade/app/Home.py   # launch the app (presets and stored runs work without a key)
```

## 10. Security & compliance

- Use only public Eurostat data. No personal data, credentials or tokens in the repo. Use `.env` or Streamlit secrets, which are git-ignored. `ANTHROPIC_API_KEY` is never written into run records or logs.
- **What reaches the LLM:**
  - the user's question and the session's structured context (previous specs and result entities)
  - the schema and catalogue
  - label matches
  - the computed fact sheet

  All of this is public statistical information. Raw data files never leave the machine. The app's About page states that questions are sent to an external LLM service. For production use in a public institution, the LLM endpoint can be swapped for an EU-hosted or on-premises one (`agents/llm.py` is the only place to change).
- **SQL safety:** the DuckDB connection is read-only with external access disabled. Every query passes `sql_guard` (one `SELECT`, whitelisted views only, forced `LIMIT`, timeout). There is no way for a question to read or write files.
- **Prompt injection:** user text is passed to the LLM as data inside clearly delimited fields, never as instructions. LLM outputs are validated against Pydantic schemas before use.
- Add new dependencies only with licences compatible with EUPL-1.2 (MIT, BSD and Apache-2.0 are fine).
- Don't use the STATEC logo or branding outside the materials they approved.
