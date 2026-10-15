import pandas as pd
import pytest

from luxtrade.ingest.reduce import interim_paths, reduce_archive


@pytest.fixture
def reduced(bulk_raw, tmp_path):
    interim = tmp_path / "interim"
    result = reduce_archive(bulk_raw / "bulk" / "full_v2_202512.7z", "202512", interim, tmp_path)
    lu_path, eu_path = interim_paths(interim, "202512")
    return result, pd.read_parquet(lu_path), pd.read_parquet(eu_path)


def test_reduce_keeps_every_lu_row_and_nothing_else(reduced):
    result, lu, _ = reduced
    assert result.rows_total == 9 and result.rows_lu == 7 == len(lu)
    assert set(lu["reporter"]) == {"LU"}
    assert "value_nac" not in lu.columns


def test_reduce_keeps_codes_as_text_and_values_as_numbers(reduced):
    _, lu, _ = reduced
    assert "04061000" in set(lu["product_nc"])  # leading zero kept
    assert lu["period"].eq("202512").all()
    assert lu["value_eur"].dtype == "float64"


def test_reduce_summarises_every_reporter_by_hs2(reduced):
    _, _, eu = reduced
    be = eu[eu["reporter"] == "BE"].set_index(["trade_type", "hs2"])["value_eur"]
    assert be[("E", "04")] == 900 and be[("I", "27")] == 5000
    assert "TOTAL" not in set(eu["hs2"])


def test_reduce_rejects_an_archive_for_another_month(bulk_raw, tmp_path):
    with pytest.raises(ValueError, match="PERIOD"):
        reduce_archive(bulk_raw / "bulk" / "full_v2_202512.7z", "202511", tmp_path / "i", tmp_path)
