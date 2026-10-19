"""Project-wide paths and constants (single source of truth)."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"  # per-month LU extracts reduced from the bulk files
PROCESSED_DIR = DATA_DIR / "processed"
# Overridable for tests and deployment
RUNS_DIR = Path(os.environ.get("LUXTRADE_RUNS_DIR", DATA_DIR / "runs"))
DEMO_RUNS_DIR = ROOT_DIR / "demo" / "runs"
LOG_DIR = ROOT_DIR / "logs"
GOLDEN_FILE = ROOT_DIR / "tests" / "golden" / "questions.yaml"

# Processed files (the data contract, GUIDELINES §1.3) and the semantic-layer database
TRADE_FILE = "trade.parquet"
PRODUCTS_FILE = "products.parquet"
PARTNERS_FILE = "partners.parquet"
BENCHMARK_FILE = "benchmark.parquet"
META_FILE = "meta.json"
DUCKDB_FILE = "luxtrade.duckdb"
DB_PATH = Path(os.environ.get("LUXTRADE_DB", PROCESSED_DIR / DUCKDB_FILE))
QUALITY_REPORT_FILE = "quality_report.json"
LINEAGE_FILE = "lineage.json"
MANIFEST_FILE = "manifest.json"  # in RAW_DIR

# Comext bulk download (DATA_CARD §1)
BULK_FILES_URL = "https://ec.europa.eu/eurostat/api/dissemination/files/"
BULK_DATA_DIR = "comext/COMEXT_DATA/PRODUCTS"
BULK_CODELIST_DIR = "comext/COMEXT_METADATA/CLASSIFICATIONS_AND_RELATIONS/CLASSIFICATIONS"
CODELIST_LANGUAGES = {"en": "ENGLISH", "fr": "FRENCH", "de": "GERMAN"}
CODELIST_FILES = ("CN.txt", "PARTNERS_ISO.txt")

DATASET_ID = "DS-045409"
REPORTER = "LU"
LU_FIRST_YEAR = 1999  # LU reported jointly with BE (BLEU) before 1999
SERIES_FIRST_YEAR = 2002  # bulk files start in Jan 2002 (DATA_CARD §4.1)

FLOWS = {"1": "import", "2": "export"}
PRODUCT_LEVELS = (0, 2, 4, 6, 8)

# Fixed EU27 (2020) composition for intra/extra comparisons (DATA_CARD §4.6)
EU27_2020 = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()  # noqa: SIM905
)
# Explicit list of special partner codes, never a pattern (DATA_CARD §4.2b)
SPECIAL_PARTNERS = frozenset(["QP", "QQ", "QR", "QS", "QU", "QV", "QW", "QX", "QY", "QZ"])
BENCHMARK_REPORTERS = ("LU", "BE", "NL", "DE", "FR", "AT")

ATTRIBUTION = "Source: Eurostat, Comext DS-045409, extracted {date}; calculations by The Outliers."

# LLM (SOLUTION_DESIGN §10). Keys come from .env / environment, never from code. Provider and
# model are resolved when the LLM is created (after .env is loaded): LUXTRADE_LLM_PROVIDER,
# LUXTRADE_LLM_MODEL.
LLM_DEFAULT_PROVIDER = "openai"
LLM_DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-4-6"}
LLM_KEY_VARS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
}
LLM_TIMEOUT_S = 60.0

# Query and agent limits (SOLUTION_DESIGN §5)
SQL_ROW_LIMIT = 10_000
SQL_TIMEOUT_S = 10.0
MAX_RETRIES = 2
SESSION_CONTEXT_TURNS = 5
DEFAULT_TOP_N = 10
STORED_ROWS_LIMIT = 2_000
DASHBOARD_MAX_ANIMATION_PERIODS = 360

# Forecast eligibility (SOLUTION_DESIGN §5.5)
FORECAST_MIN_MONTHS = 60
FORECAST_DEFAULT_HORIZON = 12
FORECAST_MAX_HORIZON = 36  # three years; intervals widen with the horizon
