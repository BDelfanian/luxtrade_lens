"""Eurostat Comext code lists (CN, partners) in EN, FR and DE.

Files are tab-separated without header: ``code, valid_from, valid_to, label`` (dates
``dd/mm/yyyy``). A code can have several validity periods; we keep the label of the most
recent one, which is the wording users know today.
"""

from pathlib import Path

import pandas as pd

from luxtrade.config import CODELIST_LANGUAGES

_COLUMNS = ["code", "valid_from", "valid_to", "label"]


def _sortable(dates: pd.Series) -> pd.Series:
    """``dd/mm/yyyy`` → ``yyyymmdd`` (string order = date order)."""
    parts = dates.str.split("/", expand=True)
    return parts[2] + parts[1] + parts[0]


def read_codelist(path: Path) -> pd.Series:
    """Read one code list file; return the latest label per code (empty labels dropped).

    Parsed line by line because a few Eurostat lines carry stray tabs and quotes inside the
    label (e.g. FR CN ``290891``); the first four fields are kept.
    """
    rows = [
        line.split("\t")[:4]
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.count("\t") >= 3
    ]
    df = pd.DataFrame(rows, columns=_COLUMNS)
    df["code"] = df["code"].str.strip()
    df["label"] = df["label"].str.strip().str.strip('"').str.strip()
    df = df[(df["code"] != "") & (df["label"] != "")]
    df = df.assign(_to=_sortable(df["valid_to"]), _from=_sortable(df["valid_from"]))
    df = df.sort_values(["code", "_to", "_from"]).drop_duplicates("code", keep="last")
    return df.set_index("code")["label"]


def load_codelist(raw_dir: Path, name: str) -> pd.DataFrame:
    """Return ``label_en``, ``label_fr``, ``label_de`` indexed by code for one code list.

    FR or DE labels missing in Eurostat's files fall back to the English label.
    """
    labels = {
        f"label_{lang}": read_codelist(raw_dir / "codelists" / lang / name)
        for lang in CODELIST_LANGUAGES
    }
    df = pd.DataFrame(labels)
    for col in ("label_fr", "label_de"):
        df[col] = df[col].fillna(df["label_en"])
    return df[df["label_en"].notna()]
