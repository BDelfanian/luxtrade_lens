# statec-hackathon-outliers

## Comext downloader and database importer

Requires Python 3.12 or later. Install the package and its ingestion dependencies:

```bash
python -m pip install -e .
```

Edit [config/download.yaml](config/download.yaml) for inclusive reference months,
wildcard include/exclude patterns, official directory URLs, and the download directory.
The initial selection is January–December 2025, excluding annual (`52`) files.
Edit [database.yaml](database.yaml) for the local DuckDB path, memory limit, and threads.
Optionally copy [.env.sample](.env.sample) to `.env` for local overrides.
Environment variables such as `COMEXT_DATABASE__PATH` override `.env`, which overrides YAML.
`settings.py` validates the required files and all nested configuration before either command.
DuckDB requires no credentials; secrets must never be put in YAML or committed to Git.

```bash
python -m comext download
python -m comext load
```

Downloads follow actual links in Eurostat's HTML directory listings. Files stream to `.part`
and are renamed after size and format checks; SHA-256 completion receipts retain their source
URLs. Complete downloads and successfully imported files are skipped on subsequent runs.
Failures return a nonzero exit code and can be retried. Downloaded archives remain available.
No automatic revision checking or incremental updates are implemented.

The loader discovers the existing `data/raw/monthly_trade` archives recursively, alongside
new downloads. It ignores duplicate pre-existing extraction folders and processes one archive
at a time, removing only its own temporary extraction. It also accepts standalone CSV/`.dat`
files. Existing downloads without a receipt are recorded with a local `file:` URI rather than
an invented remote URL. `load` imports all locally available files; date and wildcard settings
select remote downloads, not which already-downloaded trade files to load.

DuckDB SQL stages only `REPORTER = 'LU'`, preserves all 18 original fields and string codes,
and inserts `DECIMAL(28,4)` measures without passing through floats. Excess decimal precision
fails the file rather than silently rounding it. `row_number` is the original 1-based data
record position, excluding the CSV header and before the Luxembourg filter. The data and
`imported_files` record commit in the same transaction, with complete rollback on failure.
There are no foreign keys from trade records to partner or product lookup tables.

Formats verified against local Eurostat 2002/2010 data, a live download of
`full_v2_202501.7z`, and official metadata on 14 October 2026:

- Trade archives contain a comma-separated `.dat` file with the 18-column header required
  by [load.py](src/comext/load.py); unknown schemas fail explicitly.
- English `CN.txt` and `PARTNERS_ISO.txt` are headerless UTF-8 TSV files with four fields:
  code, validity start (`DD/MM/YYYY`), validity end, and English description. Quotes in
  descriptions are literal text. CN includes historical intervals; `31/12/2500` is an
  open-ended validity marker, not a requested classification year.
- CN rows are expanded into years from the configured range and existing archive filenames.
  Where a code changes during a year, `(year, code)` stores the latest applicable definition
  in that year. Official empty descriptions and special codes are retained. Partner codes
  use the latest official name; `PARTNERS.txt` numeric codes are also supported if present.

Sources: [Eurostat Files API and directory listings](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-migrating/bulkdownload)
and [Comext API guide](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started/comext-database).
The downloader discovers classifications through `COMEXT_METADATA`, without guessing metadata
filenames or assigning today's CN descriptions to historical codes.

TODO: add explicit incremental-download and revision/re-import policies, including extending
the years of an already imported CN snapshot when new periods are added. For now, an imported
path is always skipped, even if its contents or the configured year range subsequently change.

Focused offline checks:
`python -m pytest tests/comext --confcutdir=tests/comext -o cache_dir=.pytest_cache_comext`.

**The Outliers** — STATEC Hackathon 2026 (14–16 Oct, GovTech Lab, Luxembourg).

**LuxTrade Lens** helps public-sector staff explore **Luxembourg's external trade in goods** (Eurostat Comext `DS-045409`):
- **Ask** a question in English, French or German.
- **Get** an interactive data product, chosen automatically for the question: chart, map, table or pivot table.
- **Read** a short plain-language insight, the data limits that apply, and a full trace of where every number comes from.
- **Follow up** in the same session (*"and for imports?"*, *"only Germany"*).
- **Get help with vague questions:** the tool suggests three precise, validated rewrites instead of guessing.

Every answer has a **run ID** and every conversation a **session ID**, so both can be recalled, resumed and re-verified later.

> *"Quels sont les principaux partenaires du Luxembourg à l'export, et comment ont-ils évolué ?"* → ranked map and lines + 5-sentence insight + SQL and sources, run `3f9a1c07e2`

**How it works, in one line:** a small LangGraph agent graph turns the question into a structured *who × what × when × flow* query. The data is queried with guarded SQL, and analysis and forecasts are done in tested Python. **LLMs translate, code computes.**

| Document | What's in it |
|---|---|
| [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) | Challenge, WHAT/WHY, users, requirements, jury criteria |
| [docs/SOLUTION_DESIGN.md](docs/SOLUTION_DESIGN.md) | Architecture: agents, `QuerySpec`, NL2SQL guardrails, chart rules, forecasting, insight grounding, traceability, UI |
| [docs/DATA_CARD.md](docs/DATA_CARD.md) | Source, licence, coverage, limitations (with the IDs the app uses) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Plan, roles, priorities, risks |
| [docs/GUIDELINES.md](docs/GUIDELINES.md) | Engineering rules: layers, contracts, testing, Git, ownership |

## For the jury

*(Draft. Links and numbers are filled in at the feature freeze.)*

| Criterion | Where to see it |
|---|---|
| Reproducibility & Openness | Quick start below (3 commands); `data/raw/manifest.json`; any answer's **"How we got this"** tab → **Re-verify**; EUPL-1.2 |
| Clarity & Quality of Presentation | Hosted app link: the **Overview** landing page (Luxembourg's trade at a glance, with evidence) · pitch deck in `docs/pitch/` |
| Use of Data | [DATA_CARD.md](docs/DATA_CARD.md); CN8 drill-downs; EU benchmark; limitation messages in the app |
| Innovation & Experimentation | Multilingual questions with follow-ups → automatic data product + grounded insight; question optimiser; projections with a baseline check ([SOLUTION_DESIGN.md](docs/SOLUTION_DESIGN.md)) |
| Functional PoC | Hosted app; presets Q1–Q6; golden-set scores: *to be filled* (`python -m luxtrade.agents.evaluate`) |

## Setup (reproducible environment)

Requires **Python 3.12**. Every dependency is pinned in `requirements.txt`.

**Windows (PowerShell)**
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .            # installs the luxtrade package (src/) in editable mode
```

**macOS / Linux**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .            # installs the luxtrade package (src/) in editable mode
```

**Conda (alternative)**
```bash
conda env create -f environment.yml
conda activate statec-outliers
pip install -e .
```

### LLM access (optional for presets and stored runs)

Questions typed in the ask box need an LLM API key. Copy `.env.example` to `.env` at the repository root (git-ignored) and fill it in. The provider is configurable:

| `LUXTRADE_LLM_PROVIDER` | Key | Default model |
|---|---|---|
| `openai` (current default) | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |

```
LUXTRADE_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
# LUXTRADE_LLM_MODEL=gpt-4.1-mini      # optional override
```
A key already set as an environment variable works too. The API is billed separately from ChatGPT or Claude subscriptions.
Without a key, the presets, the Refine filters and the stored runs and sessions (history, `demo/runs/`) still work. Insights then use the template fallback, and the optimiser is hidden.

### Run
The real-data Parquet files (Eurostat extraction of 14 Oct 2026, complete until Jun 2026) are in the repo under `data/processed/`. Only the DuckDB semantic layer is rebuilt locally, because it is too large for GitHub:
```bash
python -m luxtrade.semantic.build       # DuckDB semantic layer from the shared Parquet files (seconds)
streamlit run src/luxtrade/app/Home.py  # launch the app
pytest                                  # tests use their own synthetic data, no network needed
```
`python -m luxtrade.process.placeholder` writes synthetic data into the same folder, so **it overwrites the shared real data**. Use it only for development without real data, and restore the real files with `git checkout -- data/processed`.

To refresh the real data from Eurostat, the pipeline writes the same files ([GUIDELINES §1.3](docs/GUIDELINES.md)):
```bash
python -m luxtrade.ingest.download      # fetch + reduce Eurostat bulk files, write manifest (~1–1.5 h)
python -m luxtrade.process.build        # contract Parquet + quality report + DuckDB semantic layer
```
- **Quick start on real data:** `python -m luxtrade.ingest.download --from 2024-01` (~30 files, a few minutes), then `process.build`.
- **Resumable:** re-run the same command after an interruption. Only missing or republished months are fetched; partial files resume where they stopped.
- **Disk:** each `.7z` (25–45 MB, ~400 MB unzipped) is reduced right away to `data/interim/` (~1 MB per month: every LU row plus EU HS2 summaries) and then deleted. Total ~0.3 GB instead of ~11 GB. Add `--keep-archives` to keep them.
- **Blocked network?** Download the `full_v2_YYYYMM.7z` files in a browser ([bulk folder](https://ec.europa.eu/eurostat/api/dissemination/files/?sort=1&dir=comext%2FCOMEXT_DATA%2FPRODUCTS)) into `data/raw/bulk/`, and `CN.txt` + `PARTNERS_ISO.txt` (from `COMEXT_METADATA/…/CLASSIFICATIONS/{ENGLISH,FRENCH,GERMAN}`) into `data/raw/codelists/{en,fr,de}/`, then run `python -m luxtrade.ingest.download --offline`.
- Other options: `--to 2025-12`, `--workers 3`, `--dry-run`, `--force` (`--help` for all).

For notebooks, register the kernel once:
`python -m ipykernel install --user --name statec-outliers --display-name "Python (statec-outliers)"`

### Adding a dependency
1. Add the package name to `requirements.in`.
2. `pip install -r requirements.in`
3. `pip freeze --exclude-editable > requirements.txt` and restore the two header comments plus the `; sys_platform == "win32"` marker on `pywinpty`.
4. Commit both files.

## Repository layout

```
data/raw/         downloaded Eurostat data (git-ignored, recreated by scripts)
data/processed/   contract Parquet + luxtrade.duckdb (generated, git-ignored)
data/runs/        run records, one JSON file per answer (git-ignored)
demo/runs/        recorded demo runs for offline replay
src/luxtrade/     package: ingest, process, semantic, analytics, viz, agents, runs, app
notebooks/        EDA and methodology notebooks
tests/            pytest suite mirroring src/luxtrade/; tests/golden/ question set
docs/             context, solution design, data card, roadmap, guidelines
```

## Licence

Code: [EUPL-1.2](LICENSE) (SPDX: `EUPL-1.2`).
Data: Eurostat, reused under the [Eurostat copyright and reuse policy](https://ec.europa.eu/eurostat/about-us/policies/copyright) with attribution.
