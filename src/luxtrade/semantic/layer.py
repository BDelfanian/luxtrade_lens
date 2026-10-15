"""Read-only access to the semantic layer: queries with a timeout, coverage, dimensions, labels."""

import threading
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path

import duckdb
import pandas as pd

from luxtrade import config
from luxtrade.config import SQL_TIMEOUT_S

SPECIAL_KEYS = {
    "OTHER": ("Other", "Autres", "Sonstige"),
    "UNDISCLOSED": (
        "Undisclosed / not specified",
        "Non divulgué / non spécifié",
        "Nicht offengelegt / nicht ermittelt",
    ),
    "CONFIDENTIAL": ("Confidential", "Confidentiel", "Vertraulich"),
    "TOTAL": ("All goods", "Tous les produits", "Alle Waren"),
    "EU27": ("EU27 countries", "Pays de l'UE27", "EU27-Länder"),
    "NON_EU27": ("Non-EU27 countries", "Pays hors UE27", "Nicht-EU27-Länder"),
    "DISCLOSED": ("Published at CN8 level", "Publié au niveau NC8", "Auf KN8-Ebene veröffentlicht"),
}
REPORTER_LABEL = ("Luxembourg", "Luxembourg", "Luxemburg")
LANG_COL = {"en": "label_en", "fr": "label_fr", "de": "label_de"}


class QueryError(RuntimeError):
    """Raised when a query fails or exceeds its time limit."""


@dataclass(frozen=True)
class Coverage:
    """What the data covers (from ``meta_coverage``)."""

    first_period: date
    latest_complete_period: date
    latest_period: date
    extraction_date: str
    is_placeholder: bool
    source: str

    @property
    def latest_complete_year(self) -> int:
        """Last calendar year with all 12 months complete (intra + extra)."""
        p = self.latest_complete_period
        return p.year if p.month == 12 else p.year - 1

    @property
    def vintage(self) -> str:
        """Short data-vintage tag used in run IDs and captions."""
        return f"{self.extraction_date}{'-placeholder' if self.is_placeholder else ''}"


class SemanticLayer:
    """Read-only DuckDB connection factory plus cached dimensions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or config.DB_PATH)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"{self.db_path} not found. Run `python -m luxtrade.process.placeholder` "
                "(placeholder data) or the real pipeline first."
            )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(
            str(self.db_path),
            read_only=True,
            config={"enable_external_access": False, "lock_configuration": True},
        )

    def query(self, sql: str, timeout_s: float = SQL_TIMEOUT_S) -> pd.DataFrame:
        """Run one read-only statement; raise ``QueryError`` on failure or timeout."""
        con = self._connect()
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        try:
            return con.execute(sql).df()
        except duckdb.InterruptException as exc:
            raise QueryError(f"query exceeded {timeout_s:.0f}s") from exc
        except duckdb.Error as exc:
            raise QueryError(str(exc).splitlines()[0]) from exc
        finally:
            timer.cancel()
            con.close()

    @cached_property
    def coverage(self) -> Coverage:
        """Coverage row as a typed object."""
        row = self.query("SELECT * FROM meta_coverage").iloc[0]
        return Coverage(
            first_period=pd.Timestamp(row["first_period"]).date(),
            latest_complete_period=pd.Timestamp(row["latest_complete_period"]).date(),
            latest_period=pd.Timestamp(row["latest_period"]).date(),
            extraction_date=str(row["extraction_date"]),
            is_placeholder=bool(row["is_placeholder"]),
            source=str(row["source"]),
        )

    @cached_property
    def partners(self) -> pd.DataFrame:
        """Partner dimension indexed by code."""
        return self.query("SELECT * FROM dim_partner").set_index("partner")

    @cached_property
    def products(self) -> pd.DataFrame:
        """Product dimension indexed by code."""
        return self.query("SELECT * FROM dim_product").set_index("product")

    @cached_property
    def sections(self) -> pd.DataFrame:
        """HS section dimension indexed by code."""
        return self.query("SELECT * FROM dim_section").set_index("section")

    @cached_property
    def reporters(self) -> list[str]:
        """Reporters available for benchmarking."""
        return sorted(self.query("SELECT DISTINCT reporter FROM v_eu_reporters_hs2")["reporter"])

    def label(self, code: str, kind: str, lang: str = "en") -> str:
        """Human label for a partner, product or section code in the given language."""
        col = LANG_COL.get(lang, "label_en")
        idx = ("en", "fr", "de").index(lang) if lang in ("en", "fr", "de") else 0
        if code in SPECIAL_KEYS:
            return SPECIAL_KEYS[code][idx]
        if kind == "reporter" and code == config.REPORTER:
            return REPORTER_LABEL[idx]  # never a partner of itself, so not in dim_partner
        table = {
            "partner": self.partners,
            "product": self.products,
            "section": self.sections,
            "reporter": self.partners,
        }.get(kind)
        if table is not None and code in table.index:
            return str(table.loc[code, col])
        return code

    def has_code(self, code: str, kind: str) -> bool:
        """Return True if the code exists in the matching dimension."""
        if kind == "partner":
            return code in self.partners.index
        if kind == "product":
            return code in self.products.index or code == "TOTAL"
        if kind == "reporter":
            return code in self.reporters
        return False
