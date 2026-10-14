import numpy as np
import pandas as pd
import pytest

from luxtrade.analytics import benchmark, forecast, rankings, seasonality, timeseries


def test_top_n_preserves_the_total_and_pools_hidden_keys():
    df = pd.DataFrame(
        {
            "key": ["DE", "FR", "BE", "NL", "IT", "UNDISCLOSED"],
            "value": [50.0, 30.0, 10.0, 5.0, 3.0, 2.0],
        }
    )
    out = rankings.top_n_with_other(df, 3)
    assert out["value"].sum() == pytest.approx(100.0)
    assert out["share"].sum() == pytest.approx(100.0)
    assert list(out["key"]) == ["DE", "FR", "BE", "OTHER", "UNDISCLOSED"]
    assert out.loc[out["key"] == "OTHER", "value"].item() == 8.0


def test_masked_product_codes_are_never_ranked():
    df = pd.DataFrame({"key": ["27XX", "84", "99"], "value": [60.0, 30.0, 10.0]})
    out = rankings.top_n_with_other(df, 5)
    assert out.loc[out["kind"] == "item", "key"].tolist() == ["84"]
    assert out.loc[out["kind"] == "confidential", "value"].item() == 70.0


def test_balance_and_growth():
    df = pd.DataFrame(
        {
            "period": [2024, 2024, 2025, 2025],
            "flow": ["export", "import"] * 2,
            "value": [10.0, 15.0, 12.0, 14.0],
        }
    )
    bal = timeseries.to_balance(df, ["period"])
    assert bal["value"].tolist() == [-5.0, -2.0]
    assert timeseries.cagr_pct(100, 121, 2) == pytest.approx(10.0)
    assert timeseries.change_pct(0, 5) is None


def _seasonal_series(years=8, noise=0.02, seed=1):
    idx = pd.date_range("2016-01-01", periods=12 * years, freq="MS")
    pattern = np.tile([1.0, 1.0, 1.1, 1.0, 1.0, 1.0, 1.0, 0.7, 1.05, 1.1, 1.0, 0.85], years)
    trend = np.linspace(100, 130, len(idx))
    rng = np.random.default_rng(seed)
    return pd.Series(trend * pattern * rng.lognormal(0, noise, len(idx)), index=idx)


def test_stl_recovers_the_august_dip():
    prof = seasonality.seasonal_profile(seasonality.stl_decompose(_seasonal_series()))
    assert prof.loc[prof["factor"].idxmin(), "month"] == 8
    assert prof["factor"].min() == pytest.approx(0.7, abs=0.08)


def test_projection_has_ordered_intervals_and_a_baseline():
    res = forecast.project(_seasonal_series(), horizon=12)
    proj = res.frame[res.frame["kind"] == "projection"]
    assert len(proj) == 12
    assert (proj["lo95"] <= proj["lo80"]).all() and (proj["lo80"] <= proj["value"]).all()
    assert (proj["value"] <= proj["hi80"]).all() and (proj["hi80"] <= proj["hi95"]).all()
    assert res.mape_naive > 0 and "back-test" in res.method_note()


def test_short_series_are_not_projected():
    assert forecast.eligibility(_seasonal_series(years=3)) is not None
    assert forecast.eligibility(_seasonal_series(years=6)) is None


def test_spike_detection_flags_one_off_flows():
    s = _seasonal_series(noise=0.01)
    s.iloc[50] *= 4
    flags = timeseries.robust_spikes(s)
    assert flags.iloc[50] and flags.sum() == 1


def test_benchmark_index_and_intra_share():
    df = pd.DataFrame(
        {
            "reporter": ["LU"] * 4,
            "period": [2015, 2015, 2016, 2016],
            "trade_type": ["intra", "extra"] * 2,
            "value_eur": [80.0, 20.0, 90.0, 30.0],
        }
    )
    totals = (
        df.groupby(["reporter", "period"], as_index=False)["value_eur"]
        .sum()
        .rename(columns={"value_eur": "value"})
    )
    assert benchmark.index_to_base(totals, 2015).tolist() == [100.0, 120.0]
    assert benchmark.intra_share(df)["intra_share"].tolist() == [80.0, 75.0]
