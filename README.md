# statec-hackathon-outliers

**The Outliers** — STATEC Hackathon 2026 (14–16 Oct, GovTech Lab, Luxembourg).

An interactive, reproducible tool for exploring **Luxembourg's external trade in goods**: partners, products (HS2 → CN8), changes over time, seasonality, and comparison with other EU countries. It is built on the Eurostat Comext dataset `DS-045409`.

- Project context and requirements: [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md)
- Roadmap and task plan: [docs/ROADMAP.md](docs/ROADMAP.md)
- Engineering guidelines (architecture, testing, Git workflow, ownership): [docs/GUIDELINES.md](docs/GUIDELINES.md)

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
data/processed/   small cleaned aggregates (Parquet)
src/luxtrade/     package: ingest, process, analytics, app
notebooks/        EDA and methodology notebooks
tests/            pytest suite mirroring src/luxtrade/
docs/             context, roadmap, data card, methodology
```

## Licence

Code: [EUPL-1.2](LICENSE) (SPDX: `EUPL-1.2`).
Data: Eurostat, reused under the [Eurostat copyright and reuse policy](https://ec.europa.eu/eurostat/about-us/policies/copyright) with attribution.
