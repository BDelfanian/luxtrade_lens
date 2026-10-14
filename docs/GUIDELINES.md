# Engineering Guidelines — The Outliers

These are the rules we follow while building the project. They support the jury criteria: **Reproducibility & Openness** and a **Functional PoC**. They are sized for a 2.5-day hackathon: strict where it protects the demo and the audit trail, light everywhere else.

> **Golden rule:** a fresh clone must go `setup → pipeline → app` with no manual steps, and every number shown in the app must be traceable to a Eurostat query.

> **Simplicity rule (coach):** before writing code, ask *what problem does this solve, and why does it matter?* Choose the simplest solution that answers it. Prefer standard charts, transparent rules and fewer features done well. If a method can't be explained to the jury in one sentence, don't ship it.

---

## 1. Architecture

### 1.1 Layers (one-way dependencies)

```
 Eurostat API / bulk files
        │
 ┌──────▼───────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │   ingest     │──▶│   process    │──▶│  analytics   │──▶│     app      │
 │ (download,   │   │ (clean, tidy,│   │ (seasonality,│   │ (Streamlit + │
 │  manifest)   │   │  hierarchy,  │   │  outliers,   │   │  Plotly; UI  │
 │              │   │  validate)   │   │  benchmark)  │   │  only)       │
 └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
   data/raw/          data/processed/      pure functions      reads processed
                      (Parquet = CONTRACT)                     data only
```

- **Dependencies go left to right only.** `app` never calls the Eurostat API. `analytics` never does I/O.
- **`analytics` has pure functions:** DataFrame in, DataFrame or value out. They are easy to test and easy to reuse in notebooks.
- **The app layer holds no business logic.** It calls `analytics` or `queries` and renders the result. If a computation appears in a page file, move it.
- **Notebooks are for exploring and showing results.** Code worth keeping moves into `src/` before it is used anywhere else.

### 1.2 Package layout

```
src/luxtrade/
├── config.py          # paths, constants, settings (single source of truth)
├── logging_setup.py   # logging configuration
├── ingest/            # download.py, manifest.py
├── process/           # clean.py, hierarchy.py, validate.py, build.py
├── analytics/         # rankings.py, composition.py, significance.py,
│                      # seasonality.py, outliers.py, benchmark.py
├── queries.py         # DuckDB/pandas read helpers over data/processed
└── app/               # Home.py + pages/ (one file per module)
tests/                 # mirrors src/luxtrade/ one-to-one
```

### 1.3 Data contract (lets work happen in parallel)

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
| `value_eur` | float64 | `VALUE_IN_EUROS` |
| `qty_100kg` | float64 | nullable |

Lookup tables: `products.parquet` (`product`, `level`, `parent`, `label`) and `partners.parquet` (`partner`, `label`, `iso3`, `is_aggregate`, `is_eu`).

Until the real pipeline is ready, `tests/fixtures/` holds a **small synthetic file with the same schema**. The app and analytics are built against it from Day 1.

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
- **Methods are documented:** `docs/METHODOLOGY.md` defines every metric (HHI, Pareto cut, STL parameters, outlier rules) and every decision (e.g. "LU series start in 1999 because of BLEU").
- **Every chart cites its source** in a caption: *"Source: Eurostat DS-045409, extracted YYYY-MM-DD; Outliers calculations."*
- **Commit history tells the story:** small, descriptive commits (see §6). No force-push on `main`.

## 5. Testing — one test module per functionality

- **Mirror structure:** `src/luxtrade/analytics/seasonality.py` → `tests/analytics/test_seasonality.py`, and so on.
- **Framework:** `pytest`. Shared synthetic fixtures live in `tests/conftest.py` and `tests/fixtures/`.
- **What to test** (in priority order):
  1. **analytics:** rankings, shares, HHI, Pareto/Top-N + "Other" (values must still sum to the parent!), seasonal adjustment (on a known synthetic seasonal series), outlier flags (on an injected spike).
  2. **process:** product codes keep their leading zeros; hierarchy parent mapping; flow code mapping; schema matches the contract; no duplicate keys.
  3. **ingest:** query/URL builder; manifest content. **No live network calls in tests.** Mock the HTTP layer.
  4. **app:** smoke test only. Each page imports and renders against the fixture (`streamlit.testing.v1.AppTest`).
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
| Ingest + manifest | **Behrooz** | Kasra | `ingest/`, `tests/ingest/` |
| Processing + validation + data contract | **Behrooz** | Mina | `process/`, `queries.py`, `tests/process/` |
| Seasonality + outlier analytics | **Behrooz** | Kasra | `analytics/seasonality.py`, `analytics/outliers.py` |
| App shell, navigation, styling, deployment | **Mina** | Behrooz | `app/Home.py`, `app/components/` |
| Overview, Partner, Product pages (Q1–Q4) + significance drill-down | **Mina** | Kasra | `app/pages/`, `analytics/significance.py` |
| Rankings, composition, benchmark analytics (Q5) | **Kasra** | Behrooz | `analytics/rankings.py`, `composition.py`, `benchmark.py` |
| Seasonality & Benchmark pages | **Kasra** | Mina | `app/pages/` |
| EDA notebooks, insights, METHODOLOGY.md, pitch deck | **Kasra** | All | `notebooks/`, `docs/` |
| README, DATA_CARD, licence, reproducibility test | **Behrooz** | All | root, `docs/` |

**Working agreements:**
- **Shared interfaces need agreement:** the data contract (§1.3), `config.py` and `queries.py` signatures. Announce the change and get one teammate's OK.
- **Parallel by default:** Mina and Kasra build against `tests/fixtures/` while Behrooz finishes the real pipeline. They swap to real data with no code changes.
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
- [ ] Docs are updated if behaviour, metrics or the data contract changed
- [ ] The PR is reviewed and merged, and `main` still runs end-to-end

## 9. Standard commands

```bash
ruff check --fix . && ruff format .      # lint + format
pytest                                   # fast tests
pytest -m "slow or network"              # optional heavier tests
python -m luxtrade.ingest.download       # fetch raw data + manifest
python -m luxtrade.process.build         # build processed Parquet + quality report
streamlit run src/luxtrade/app/Home.py   # launch the app
```

## 10. Security & compliance

- Use only public Eurostat data. No personal data, credentials or tokens in the repo. Use `.env` or Streamlit secrets, which are git-ignored.
- Add new dependencies only with licences compatible with EUPL-1.2 (MIT, BSD and Apache-2.0 are fine).
- Don't use the STATEC logo or branding outside the materials they approved.
