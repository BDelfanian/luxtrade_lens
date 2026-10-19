"""Seasonal adjustment with STL (statsmodels), on log values so the pattern is proportional."""

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

STL_SETTINGS = {"period": 12, "robust": True, "seasonal": 13}


def stl_decompose(series: pd.Series) -> pd.DataFrame:
    """Decompose a monthly series (DatetimeIndex) into trend, seasonal factor and adjusted values.

    Columns: observed, trend, seasonal_factor (multiplicative, 1 = no effect), adjusted.
    """
    y = series.astype(float).clip(lower=1.0)
    res = STL(np.log(y), **STL_SETTINGS).fit()
    factor = np.exp(res.seasonal)
    return pd.DataFrame(
        {
            "observed": series.astype(float),
            "trend": np.exp(res.trend),
            "seasonal_factor": factor,
            "adjusted": series.astype(float) / factor,
        },
        index=series.index,
    )


def seasonal_profile(decomposed: pd.DataFrame) -> pd.DataFrame:
    """Average seasonal factor per calendar month over the last 5 years (columns: month, factor)."""
    recent = decomposed.iloc[-60:]
    prof = recent.groupby(recent.index.month)["seasonal_factor"].mean()
    return pd.DataFrame({"month": prof.index.astype(int), "factor": prof.to_numpy()})


def method_note() -> str:
    """One-line method description for the trace."""
    return (
        "STL on log values (period 12, robust, seasonal window 13); adjusted = observed / factor; "
        "the month profile averages the seasonal factors of the last 5 years"
    )
