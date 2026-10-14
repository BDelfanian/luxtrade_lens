"""Synthetic placeholder data in the exact processed-data contract (GUIDELINES §1.3).

Lets the semantic layer, agents and app be built before the real Comext pipeline lands.
Values are **synthetic**: shaped like Luxembourg's trade (2025 partner and chapter shares from
docs/benchmarks, seasonality, 2009/2020 dips, 2022 fuel prices, one-off 2025 flows) but they are
NOT Eurostat figures. ``meta.json`` carries ``is_placeholder: true`` and the app shows a banner.

Usage: ``python -m luxtrade.process.placeholder [--small] [--out DIR]``
"""

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from luxtrade.config import (
    BENCHMARK_FILE,
    BENCHMARK_REPORTERS,
    META_FILE,
    PARTNERS_FILE,
    PROCESSED_DIR,
    PRODUCTS_FILE,
    REPORTER,
    TRADE_FILE,
)
from luxtrade.logging_setup import setup_logging, timed
from luxtrade.process.nomenclature import (
    CHAPTERS,
    EU_JOINED,
    EU_LEFT,
    HEADINGS,
    INTRA_SPECIAL,
    PARTNERS,
    is_eu27_2020,
    is_special,
    section_of,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaceholderConfig:
    """Shape of the generated data set."""

    first_month: str = "2002-01"
    last_complete_month: str = "2025-12"
    extra_only_until: str = "2026-07"
    partners: tuple[str, ...] | None = None  # None = every partner in the nomenclature
    chapters: tuple[str, ...] | None = None  # None = every chapter in the nomenclature
    seed: int = 42


SMALL = PlaceholderConfig(
    first_month="2018-01",
    partners=("DE", "FR", "BE", "NL", "US", "CN", "JP", "GB", "QY", "QV"),
    chapters=("04", "27", "39", "72", "84", "85", "87", "99"),
)

# Annual totals in bn EUR (anchor years, interpolated in between)
_ANNUAL_BN = {
    "export": {
        2002: 8.6,
        2007: 12.0,
        2008: 12.2,
        2009: 9.6,
        2012: 11.4,
        2015: 12.1,
        2019: 13.6,
        2020: 12.2,
        2021: 14.3,
        2022: 15.6,
        2023: 15.4,
        2024: 15.8,
        2025: 16.25,
        2026: 16.5,
    },
    "import": {
        2002: 11.7,
        2007: 16.4,
        2008: 17.4,
        2009: 14.1,
        2012: 17.6,
        2015: 18.2,
        2019: 21.0,
        2020: 18.9,
        2021: 22.1,
        2022: 25.6,
        2023: 24.6,
        2024: 24.4,
        2025: 25.1,
        2026: 25.4,
    },
}
# Partner weights (%), from docs/benchmarks/Q1 for the top 10, rough values for the rest
_PARTNER_W = {
    "export": {
        "DE": 24.6,
        "FR": 19.2,
        "BE": 13.2,
        "NL": 5.9,
        "IT": 4.1,
        "ES": 3.2,
        "US": 2.6,
        "PL": 2.4,
        "GB": 2.2,
        "AT": 2.0,
        "CH": 1.6,
        "SE": 1.2,
        "CZ": 1.2,
        "PT": 0.9,
        "DK": 0.8,
        "IE": 0.6,
        "GR": 0.5,
        "CN": 1.4,
        "JP": 0.5,
        "IN": 0.6,
        "KR": 0.4,
        "TR": 0.9,
        "BR": 0.4,
        "CA": 0.4,
        "QV": 1.0,
        "QY": 0.5,
        "QZ": 0.1,
    },
    "import": {
        "BE": 31.1,
        "DE": 27.1,
        "FR": 11.1,
        "NL": 5.6,
        "JP": 1.2,
        "IT": 3.3,
        "CN": 1.1,
        "US": 2.8,
        "PL": 2.1,
        "ES": 1.5,
        "AT": 1.2,
        "GB": 1.3,
        "CH": 1.0,
        "SE": 0.8,
        "CZ": 0.9,
        "PT": 0.4,
        "DK": 0.4,
        "IE": 1.0,
        "GR": 0.1,
        "IN": 0.3,
        "KR": 0.5,
        "TR": 0.6,
        "BR": 0.3,
        "CA": 0.2,
        "QY": 0.15,
        "QZ": 0.05,
        "QV": 0.05,
    },
}
# Chapter weights (%), from docs/benchmarks/Q2 for the leading chapters
_CHAPTER_W = {
    "export": {
        "84": 12.5,
        "39": 9.7,
        "87": 9.6,
        "85": 7.0,
        "72": 6.9,
        "40": 5.2,
        "73": 5.0,
        "04": 4.4,
        "76": 2.9,
        "56": 2.7,
        "27": 1.5,
        "30": 1.0,
        "22": 1.2,
        "29": 1.5,
        "38": 2.0,
        "48": 1.5,
        "64": 1.3,
        "70": 2.0,
        "90": 1.8,
        "94": 0.8,
        "99": 0.6,
    },
    "import": {
        "87": 13.2,
        "84": 11.5,
        "27": 8.9,
        "85": 6.5,
        "39": 5.2,
        "72": 3.8,
        "30": 3.3,
        "40": 3.3,
        "22": 2.5,
        "04": 2.2,
        "73": 2.4,
        "76": 1.8,
        "29": 1.5,
        "38": 2.2,
        "48": 1.2,
        "56": 0.9,
        "64": 0.6,
        "70": 1.3,
        "90": 2.0,
        "94": 1.5,
        "99": 0.1,
    },
}
# Masked confidential codes: (code, chapter, share of that chapter's value)
_MASKED = [("27XXXXXX", "27", 0.20), ("3920XXXX", "39", 0.03), ("87XXXXXX", "87", 0.05)]
_SEASON = np.array([0.95, 1.0, 1.08, 1.02, 1.03, 1.05, 1.0, 0.78, 1.04, 1.06, 1.03, 0.86])
_FUEL_PRICE = {
    2002: 0.6,
    2008: 1.1,
    2009: 0.75,
    2011: 1.15,
    2014: 1.0,
    2015: 0.7,
    2016: 0.6,
    2019: 0.8,
    2020: 0.55,
    2021: 0.85,
    2022: 1.6,
    2023: 1.15,
    2024: 1.0,
    2025: 0.95,
    2026: 0.95,
}
# One-off flows in 2025 (docs/benchmarks/Q1 §4): (flow, partner, cn8, months, M EUR per month)
_ONE_OFFS = [
    ("import", "CN", "85171000", (9, 10, 11, 12), 150.0),
    ("export", "FR", "85171000", (9, 10, 11, 12), 190.0),
    ("import", "JP", "84281000", (7, 10), 350.0),
]


def _interp(anchors: dict[int, float], years: np.ndarray) -> np.ndarray:
    keys = sorted(anchors)
    return np.interp(years, keys, [anchors[k] for k in keys])


def _months(first: str, last: str) -> pd.DatetimeIndex:
    return pd.date_range(f"{first}-01", f"{last}-01", freq="MS")


def _product_universe(chapters: list[str], rng: np.random.Generator) -> pd.DataFrame:
    """CN8 codes per chapter with their within-chapter weight (masked codes included)."""
    rows = []
    for ch in chapters:
        if ch == "99":
            rows.append(("99XXXXXX", ch, 1.0, True))
            continue
        cn8 = [f"{h4}{sub}00" for h4 in HEADINGS if h4.startswith(ch) for sub in ("10", "90")]
        weights = rng.dirichlet(np.full(len(cn8), 1.5))
        masked = [(code, share) for code, mch, share in _MASKED if mch == ch]
        open_share = 1.0 - sum(share for _, share in masked)
        rows += [(code, ch, w * open_share, False) for code, w in zip(cn8, weights, strict=True)]
        rows += [(code, ch, share, True) for code, share in masked]
    return pd.DataFrame(rows, columns=["product", "hs2", "w_in_chapter", "is_confidential"])


def _trade_type(partner: str, periods: pd.DatetimeIndex) -> np.ndarray:
    """Actual intra/extra classification at the time of trade (bulk TRADE_TYPE)."""
    if is_special(partner):
        return np.where(np.full(len(periods), partner in INTRA_SPECIAL), "intra", "extra")
    intra = np.full(len(periods), is_eu27_2020(partner) or partner in EU_LEFT)
    if partner in EU_JOINED:
        intra &= periods >= pd.Timestamp(f"{EU_JOINED[partner]}-01")
    if partner in EU_LEFT:
        intra &= periods < pd.Timestamp(f"{EU_LEFT[partner]}-01")
    return np.where(intra, "intra", "extra")


@timed
def generate_trade(cfg: PlaceholderConfig) -> pd.DataFrame:
    """Generate LU detail rows (CN8 + masked codes) and TOTAL rows in the contract schema."""
    rng = np.random.default_rng(cfg.seed)
    partners = list(cfg.partners or PARTNERS)
    chapters = list(cfg.chapters or CHAPTERS)
    periods = _months(cfg.first_month, cfg.extra_only_until)
    years = periods.year.to_numpy()
    products = _product_universe(chapters, rng)

    frames = []
    for flow in ("export", "import"):
        wp = np.array([_PARTNER_W[flow].get(p, 0.3) for p in partners])
        wp = wp / wp.sum()
        wch = products["hs2"].map(_CHAPTER_W[flow]).fillna(0.5).to_numpy()
        wk = wch * products["w_in_chapter"].to_numpy()
        wk = wk / wk.sum()
        affinity = rng.lognormal(0.0, 0.7, size=(len(partners), len(products)))
        # Small partners trade only part of the range; special partners very few products
        trades = rng.random((len(partners), len(products))) < np.clip(wp[:, None] * 40, 0.25, 1.0)
        for i, p in enumerate(partners):
            if is_special(p):
                trades[i] = rng.random(len(products)) < 0.15

        cell = wp[:, None] * wk[None, :] * affinity * trades  # partner × product
        season = _SEASON[periods.month.to_numpy() - 1]
        fuel = np.where(
            products["hs2"].to_numpy()[None, :] == "27",
            _interp(_FUEL_PRICE, years)[:, None],
            1.0,
        )
        noise = rng.lognormal(0.0, 0.15, size=(len(periods), len(partners), len(products)))
        raw = season[:, None, None] * fuel[:, None, :] * cell[None, :, :] * noise
        # Calibrate each year to its annual total
        annual = _interp(_ANNUAL_BN[flow], years) * 1e9
        year_ids = pd.factorize(years)[0]
        year_sums = np.bincount(year_ids, weights=raw.sum(axis=(1, 2)))
        months_in_year = np.bincount(year_ids)[year_ids]  # 7 for the partial last year
        raw *= (annual * months_in_year / 12 / year_sums[year_ids])[:, None, None]
        covid = np.ones(len(periods))
        covid[(years == 2020) & (periods.month == 4)] = 0.7
        covid[(years == 2020) & (periods.month == 5)] = 0.8
        raw *= covid[:, None, None]

        t_idx, p_idx, k_idx = np.nonzero(raw)
        df = pd.DataFrame(
            {
                "period": periods[t_idx],
                "partner": np.array(partners)[p_idx],
                "product": products["product"].to_numpy()[k_idx],
                "is_confidential": products["is_confidential"].to_numpy()[k_idx],
                "value_eur": raw[t_idx, p_idx, k_idx],
            }
        )
        df["flow"] = flow
        for one_flow, partner, cn8, months, meur in _ONE_OFFS:
            if one_flow != flow or partner not in partners or cn8 not in set(products["product"]):
                continue
            for m in months:
                period = pd.Timestamp(f"2025-{m:02d}-01")
                mask = (
                    (df["period"] == period) & (df["partner"] == partner) & (df["product"] == cn8)
                )
                if mask.any():
                    df.loc[mask, "value_eur"] += meur * 1e6
                elif period in periods:
                    df.loc[len(df)] = [period, partner, cn8, False, meur * 1e6, flow]
        frames.append(df)

    detail = pd.concat(frames, ignore_index=True)
    detail["value_eur"] = detail["value_eur"].round(0)
    detail = detail[detail["value_eur"] > 0]
    detail["trade_type"] = ""
    for p in partners:
        mask = detail["partner"] == p
        types = _trade_type(p, pd.DatetimeIndex(detail.loc[mask, "period"]))
        detail.loc[mask, "trade_type"] = types
    # Latest months: extra-EU only (intra-EU published later, DATA_CARD §4.3)
    recent = detail["period"] > pd.Timestamp(f"{cfg.last_complete_month}-01")
    detail = detail[~recent | (detail["trade_type"] == "extra")]
    # Quantities: rough EUR/kg per chapter; 4 % unknown (null), never 0 (DATA_CARD §4b)
    price = 2.0 + (pd.to_numeric(detail["product"].str[:2], errors="coerce").fillna(50) % 17)
    qty = detail["value_eur"] / price * rng.lognormal(0, 0.2, len(detail))
    detail["qty_kg"] = qty.round(0).where(rng.random(len(detail)) > 0.04)
    detail["level"] = 8

    total = (
        detail.groupby(["period", "partner", "flow", "trade_type"], as_index=False)
        .agg(value_eur=("value_eur", "sum"), qty_kg=("qty_kg", "sum"))
        .assign(product="TOTAL", level=0, is_confidential=False)
    )
    out = pd.concat([detail, total], ignore_index=True)
    out["freq"] = "M"
    out["reporter"] = REPORTER
    cols = [
        "freq",
        "period",
        "reporter",
        "partner",
        "flow",
        "product",
        "level",
        "trade_type",
        "is_confidential",
        "value_eur",
        "qty_kg",
    ]
    out = out[cols].sort_values(["period", "partner", "flow", "level", "product"])
    logger.info("trade rows: %d (%d detail)", len(out), len(detail))
    return out.reset_index(drop=True)


def build_products(trade: pd.DataFrame) -> pd.DataFrame:
    """Product dimension for every code (CN8, HS6, HS4, HS2, masked) seen in the detail rows."""
    cn8 = sorted(set(trade.loc[trade["level"] == 8, "product"]))
    rows = []
    for code in cn8:
        for level in (2, 4, 6, 8):
            rows.append((code[:level], level, code[: level - 2] if level > 2 else "TOTAL"))
    df = pd.DataFrame(rows, columns=["product", "level", "parent"]).drop_duplicates("product")

    def labels(code: str, level: int) -> tuple[str, str, str]:
        ch = CHAPTERS.get(code[:2], ("Chapter " + code[:2],) * 3)
        if "X" in code:
            if code.startswith("99"):
                return CHAPTERS["99"]
            base = HEADINGS.get(code[:4], ch) if code[2:4] != "XX" else ch
            return (
                f"Confidential — {base[0]}",
                f"Confidentiel — {base[1]}",
                f"Vertraulich — {base[2]}",
            )
        if level == 2:
            return ch
        heading = HEADINGS.get(code[:4], ch)
        if level == 4:
            return heading
        return tuple(f"{lab} ({code})" for lab in heading)  # placeholder detail label

    labs = [labels(c, lv) for c, lv in zip(df["product"], df["level"], strict=True)]
    df["label_en"], df["label_fr"], df["label_de"] = zip(*labs, strict=True)
    df["label"] = df["label_en"]
    df["section"] = df["product"].str[:2].map(section_of)
    df["is_confidential"] = df["product"].str.contains("X")
    return df.sort_values(["level", "product"]).reset_index(drop=True)


def build_partners(trade: pd.DataFrame) -> pd.DataFrame:
    """Partner dimension with ISO-3 codes for maps and EN/FR/DE labels."""
    codes = sorted(set(trade["partner"]))
    rows = [(c, *PARTNERS[c]) for c in codes]
    df = pd.DataFrame(rows, columns=["partner", "iso3", "label_en", "label_fr", "label_de"])
    df["label"] = df["label_en"]
    df["is_aggregate"] = False
    df["is_eu27_2020"] = df["partner"].map(is_eu27_2020)
    df["is_special"] = df["partner"].map(is_special)
    return df


@timed
def generate_benchmark(trade: pd.DataFrame, cfg: PlaceholderConfig) -> pd.DataFrame:
    """EU reporter summaries: reporter × trade type × flow × HS2 × month (LU from its detail)."""
    rng = np.random.default_rng(cfg.seed + 1)
    lu = trade[(trade["level"] == 8)].assign(hs2=lambda d: d["product"].str[:2])
    lu = lu.groupby(["period", "flow", "trade_type", "hs2"], as_index=False)["value_eur"].sum()
    lu["reporter"] = REPORTER
    frames = [lu]
    # size vs LU, intra-EU share, yearly growth gap vs LU
    profile = {
        "BE": (28, 0.70, 0.01),
        "NL": (40, 0.62, 0.015),
        "DE": (95, 0.55, 0.005),
        "FR": (42, 0.58, 0.0),
        "AT": (13, 0.70, 0.01),
    }
    totals = lu.groupby(["period", "flow"], as_index=False)["value_eur"].sum()
    hs2 = sorted(lu["hs2"].unique())
    for rep, (size, intra_share, gap) in profile.items():
        mix = rng.dirichlet(np.full(len(hs2), 2.0))
        for _, row in totals.iterrows():
            growth = (1 + gap) ** (row["period"].year - 2015)
            value = row["value_eur"] * size * growth * mix * rng.lognormal(0, 0.05, len(hs2))
            for ttype, share in (("intra", intra_share), ("extra", 1 - intra_share)):
                frames.append(
                    pd.DataFrame(
                        {
                            "period": row["period"],
                            "flow": row["flow"],
                            "trade_type": ttype,
                            "hs2": hs2,
                            "value_eur": (value * share).round(0),
                            "reporter": rep,
                        }
                    )
                )
    out = pd.concat(frames, ignore_index=True)
    out = out[out["reporter"].isin(BENCHMARK_REPORTERS)]
    cols = ["reporter", "trade_type", "flow", "hs2", "period", "value_eur"]
    return out[cols].sort_values(cols[:5]).reset_index(drop=True)


def _write(df: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    if "period" in df.columns:
        idx = table.schema.get_field_index("period")
        table = table.set_column(idx, "period", table.column("period").cast(pa.date32()))
    pq.write_table(table, path)


@timed
def write_placeholder(out_dir: Path = PROCESSED_DIR, cfg: PlaceholderConfig | None = None) -> None:
    """Write trade, products, partners, benchmark and meta files to ``out_dir``."""
    cfg = cfg or PlaceholderConfig()
    out_dir.mkdir(parents=True, exist_ok=True)
    trade = generate_trade(cfg)
    _write(trade, out_dir / TRADE_FILE)
    _write(build_products(trade), out_dir / PRODUCTS_FILE)
    _write(build_partners(trade), out_dir / PARTNERS_FILE)
    _write(generate_benchmark(trade, cfg), out_dir / BENCHMARK_FILE)
    meta = {
        "is_placeholder": True,
        "source": "SYNTHETIC placeholder shaped like Eurostat Comext DS-045409 (not real figures)",
        "extraction_date": datetime.now(UTC).date().isoformat(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": cfg.seed,
        "first_month": cfg.first_month,
        "last_complete_month": cfg.last_complete_month,
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("placeholder data written to %s", out_dir)


def main() -> None:
    """CLI entry point: generate placeholder data, then build the semantic layer."""
    from luxtrade.semantic.build import build_database

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--small", action="store_true", help="small set (2018+, few partners)")
    parser.add_argument("--out", type=Path, default=PROCESSED_DIR)
    args = parser.parse_args()
    setup_logging()
    write_placeholder(args.out, SMALL if args.small else PlaceholderConfig())
    build_database(args.out)


if __name__ == "__main__":
    main()
