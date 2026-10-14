import pandas as pd
import pytest

from luxtrade.config import PARTNERS_FILE, PRODUCTS_FILE, TRADE_FILE

CONTRACT = [
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


@pytest.fixture(scope="module")
def trade(processed_dir):
    return pd.read_parquet(processed_dir / TRADE_FILE)


def test_trade_follows_the_data_contract(trade):
    assert list(trade.columns) == CONTRACT
    assert set(trade["flow"]) == {"import", "export"}
    assert set(trade["level"]) == {0, 8}
    assert trade["product"].map(type).eq(str).all()


def test_product_codes_keep_leading_zeros(trade):
    assert trade["product"].str.startswith("04").any()
    assert (trade.loc[trade["level"] == 8, "product"].str.len() == 8).all()


def test_detail_reconciles_to_total(trade):
    keys = ["period", "partner", "flow", "trade_type"]
    detail = trade[trade["level"] == 8].groupby(keys)["value_eur"].sum()
    total = trade[trade["level"] == 0].set_index(keys)["value_eur"]
    pd.testing.assert_series_equal(detail.sort_index(), total.sort_index(), check_names=False)


def test_masked_codes_are_flagged_and_kept(trade):
    masked = trade[trade["product"].str.contains("X")]
    assert not masked.empty and masked["is_confidential"].all()


def test_latest_months_are_extra_eu_only(trade):
    recent = trade[trade["period"] > pd.Timestamp("2025-12-01").date()]
    assert not recent.empty and set(recent["trade_type"]) == {"extra"}


def test_unknown_quantity_is_null_not_zero(trade):
    assert trade["qty_kg"].isna().any()
    assert not (trade["qty_kg"] == 0).any()


def test_dimensions_have_three_languages(processed_dir):
    products = pd.read_parquet(processed_dir / PRODUCTS_FILE)
    partners = pd.read_parquet(processed_dir / PARTNERS_FILE)
    for df in (products, partners):
        assert {"label_en", "label_fr", "label_de"} <= set(df.columns)
    assert partners.set_index("partner").at["DE", "label_fr"] == "Allemagne"
    assert partners.set_index("partner").at["QY", "is_special"]
