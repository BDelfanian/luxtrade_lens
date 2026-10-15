"""Real pipeline (interim extracts → contract files → semantic layer) on tiny synthetic archives."""

import json
from datetime import date

import duckdb
import pandas as pd
import pytest

from luxtrade.config import (
    BENCHMARK_FILE,
    DUCKDB_FILE,
    META_FILE,
    PARTNERS_FILE,
    PRODUCTS_FILE,
    QUALITY_REPORT_FILE,
    TRADE_FILE,
)
from luxtrade.ingest.download import run
from luxtrade.process.build import build, product_labels
from luxtrade.process.codelists import read_codelist
from luxtrade.process.validate import TRADE_COLUMNS
from luxtrade.semantic.build import build_database


@pytest.fixture
def processed(bulk_raw, tmp_path):
    interim, out = tmp_path / "interim", tmp_path / "processed"
    assert run("202512", None, bulk_raw, interim, offline=True) == 0
    report = build(interim, bulk_raw, out)
    return out, report


@pytest.fixture
def trade(processed):
    return pd.read_parquet(processed[0] / TRADE_FILE)


def test_trade_follows_the_data_contract(trade):
    assert list(trade.columns) == TRADE_COLUMNS
    assert set(trade["level"]) == {0, 8}
    assert set(trade["flow"]) == {"import", "export"}
    assert set(trade["trade_type"]) == {"intra", "extra"}
    assert set(trade["reporter"]) == {"LU"} and set(trade["freq"]) == {"M"}
    assert trade["period"].iloc[0] == date(2025, 12, 1)


def test_statistical_procedures_are_summed_and_unknown_quantity_is_null(trade):
    row = trade[(trade["partner"] == "DE") & (trade["product"] == "04061000")]
    assert len(row) == 1 and row["value_eur"].item() == 1500
    assert pd.isna(row["qty_kg"].item())  # one part reported 0 kg → unknown
    assert not (trade["qty_kg"] == 0).any()


def test_masked_codes_are_flagged_and_kept(trade):
    masked = trade[trade["product"].str.contains("X")]
    assert set(masked["product"]) == {"27XXXXXX", "99XXXXXX"} and masked["is_confidential"].all()


def test_detail_reconciles_to_total_per_flow_and_trade_type(processed):
    _, report = processed
    assert report["reconciliation"]["groups_off_tolerance"] == 0
    # per partner, QY detail has no TOTAL row: its value sits in DE's TOTAL (Comext behaviour)
    assert report["reconciliation_by_partner_info"]["groups_without_total_row"] > 0


def test_latest_complete_month_is_detected(processed):
    out, report = processed
    assert report["latest_complete_month"] == "2025-12"
    assert report["months_extra_eu_only"] == ["2026-01"]
    meta = json.loads((out / META_FILE).read_text())
    assert meta["is_placeholder"] is False and meta["last_complete_month"] == "2025-12"
    assert (out / QUALITY_REPORT_FILE).exists()


def test_products_get_official_labels_in_three_languages(processed):
    products = pd.read_parquet(processed[0] / PRODUCTS_FILE).set_index("product")
    assert products.at["04061000", "label_fr"] == "Fromages frais, y.c. de lactosérum"
    assert products.at["04061000", "label_en"] != "Old wording"  # latest validity wins
    assert products.at["04061000", "parent"] == "040610"
    assert products.at["27", "label_de"] == "Mineralische Brennstoffe und Mineralöle"  # curated
    assert products.at["04", "label_en"] == "Dairy produce; eggs; honey"  # curated overlay
    assert products.at["27XXXXXX", "label_en"] == "Confidential — Mineral fuels and oils"
    assert products.at["27XXXXXX", "is_confidential"]
    assert products.at["04061000", "sitc"] == "02491"
    assert pd.isna(products.at["04061000", "bec5"])  # '.....' placeholder → null


def test_partners_have_iso3_and_flags(processed):
    partners = pd.read_parquet(processed[0] / PARTNERS_FILE).set_index("partner")
    assert partners.at["US", "iso3"] == "USA"
    assert partners.at["DE", "label_fr"] == "Allemagne" and partners.at["DE", "is_eu27_2020"]
    assert partners.at["QY", "is_special"] and pd.isna(partners.at["QY", "iso3"])


def test_benchmark_keeps_benchmark_reporters_only(processed):
    bench = pd.read_parquet(processed[0] / BENCHMARK_FILE)
    assert list(bench.columns) == ["reporter", "trade_type", "flow", "hs2", "period", "value_eur"]
    assert set(bench["reporter"]) == {"BE", "LU"}


def test_semantic_layer_builds_on_real_pipeline_output(processed):
    out, _ = processed
    build_database(out)
    with duckdb.connect(str(out / DUCKDB_FILE), read_only=True) as con:
        cov = con.execute("SELECT latest_complete_period, is_placeholder FROM meta_coverage")
        assert cov.fetchone() == (date(2025, 12, 1), False)
        total = con.execute("SELECT sum(value_eur) FROM v_lu_trade WHERE period = '2025-12-01'")
        assert total.fetchone()[0] == 2100  # detail only: TOTAL rows never mixed in


def test_codelist_parser_tolerates_stray_tabs(bulk_raw):
    labels = read_codelist(bulk_raw / "codelists" / "fr" / "CN.txt")
    assert labels["290891"] == "Dinosèbe"


def test_all_caps_chapter_labels_are_sentence_cased():
    cn = pd.DataFrame(
        {
            "label_en": ["LIVE ANIMALS"],
            "label_fr": ["ANIMAUX VIVANTS"],
            "label_de": ["LEBENDE TIERE"],
        },
        index=["05"],
    )
    assert product_labels("05", 2, cn) == ("Live animals", "Animaux vivants", "Lebende tiere")


def test_unknown_codes_fall_back_to_parent_label():
    cn = pd.DataFrame(columns=["label_en", "label_fr", "label_de"])
    assert product_labels("0406", 4, cn)[0] == "Cheese"  # curated heading
    assert product_labels("040610", 6, cn)[0] == "Cheese (040610)"
