"""Time-series helpers: balance, growth, CAGR, peaks."""

import numpy as np
import pandas as pd


def to_balance(df: pd.DataFrame, index: list[str], value: str = "value") -> pd.DataFrame:
    """Exports minus imports per ``index`` row; returns the same shape with flow='balance'."""
    wide = df.pivot_table(index=index, columns="flow", values=value, aggfunc="sum", fill_value=0)
    out = (wide.get("export", 0) - wide.get("import", 0)).rename(value).reset_index()
    return out.assign(flow="balance")


def yoy_pct(series: pd.Series, periods: int = 1) -> pd.Series:
    """Percentage change versus ``periods`` steps earlier."""
    return 100.0 * series.pct_change(periods=periods)


def cagr_pct(first: float, last: float, years: float) -> float | None:
    """Compound annual growth rate in percent; None when undefined."""
    if first <= 0 or last <= 0 or years <= 0:
        return None
    return 100.0 * ((last / first) ** (1 / years) - 1)


def change_pct(first: float, last: float) -> float | None:
    """Total percentage change from first to last; None when first is 0."""
    return 100.0 * (last / first - 1) if first else None


def peak(series: pd.Series) -> tuple[object, float]:
    """Index and value of the maximum."""
    idx = series.idxmax()
    return idx, float(series.loc[idx])


def trough(series: pd.Series) -> tuple[object, float]:
    """Index and value of the minimum."""
    idx = series.idxmin()
    return idx, float(series.loc[idx])


def robust_spikes(series: pd.Series, z: float = 4.0, ratio: float = 2.5) -> pd.Series:
    """Flag points far above a 12-point rolling median (robust z-score and ratio both exceeded)."""
    med = series.rolling(13, center=True, min_periods=5).median()
    mad = (series - med).abs().rolling(13, center=True, min_periods=5).median()
    score = (series - med) / (1.4826 * mad.replace(0, np.nan))
    return (score > z) & (series > ratio * med)
