# statec-hackathon-outliers

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
| Clarity & Quality of Presentation | Hosted app link · pitch deck in `docs/pitch/` |
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

Questions typed in the ask box need an Anthropic API key. Put it in a `.env` file at the repository root (git-ignored):
```
ANTHROPIC_API_KEY=sk-ant-...
LUXTRADE_LLM_MODEL=claude-sonnet-4-6   # default; optional override
```
Without a key, the presets, the Refine filters and the stored runs and sessions (history, `demo/runs/`) still work. Insights then use the template fallback, and the optimiser is hidden.

### Run
```bash
python -m luxtrade.ingest.download      # fetch Eurostat bulk files + manifest (~1–1.5 h, resumable)
python -m luxtrade.process.build        # build Parquet + DuckDB views + quality report
streamlit run src/luxtrade/app/Home.py  # launch the app
```

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
data/processed/   cleaned Parquet + DuckDB views (the data contract)
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
