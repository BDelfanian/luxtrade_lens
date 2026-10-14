"""Project-wide paths and constants (single source of truth)."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LOG_DIR = ROOT_DIR / "logs"

DATASET_ID = "DS-045409"
REPORTER = "LU"
LU_FIRST_YEAR = 1999  # LU reported jointly with BE (BLEU) before 1999

FLOWS = {"1": "import", "2": "export"}
PRODUCT_LEVELS = (0, 2, 4, 6, 8)
