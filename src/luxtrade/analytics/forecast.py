"""Projections: ETS with a seasonal-naive back-test (SOLUTION_DESIGN §5.5).

"We extend the seasonal pattern and the damped trend, check that this beats 'same as last
year', and show how uncertain it is."
"""

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from luxtrade.config import FORECAST_MIN_MONTHS

_Z80, _Z95 = 1.2816, 1.96


@dataclass
class ForecastResult:
    """Projection plus the evidence for choosing it."""

    frame: pd.DataFrame  # period, value, kind (actual/projection), lo80, hi80, lo95, hi95
    model: str
    mape_model: float
    mape_naive: float
    horizon: int

    def method_note(self) -> str:
        """One-line method description for the trace."""
        return (
            f"{self.model}; back-test on last 12 months: MAPE {self.mape_model:.1f} % "
            f"(seasonal-naive {self.mape_naive:.1f} %); 80/95 % intervals"
        )


def eligibility(series: pd.Series) -> str | None:
    """Return None if the series can be projected, else the reason it can't."""
    if len(series) < FORECAST_MIN_MONTHS:
        return f"needs at least {FORECAST_MIN_MONTHS} complete months, has {len(series)}"
    if (series.iloc[-24:] <= 0).sum() > 2:
        return "too many months without trade in the last two years"
    return None


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    mask = actual > 0
    return float(100 * np.mean(np.abs(pred[mask] - actual[mask]) / actual[mask]))


def _fit_ets(log_y: pd.Series):  # noqa: ANN202 - statsmodels results type
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ExponentialSmoothing(
            log_y,
            trend="add",
            damped_trend=True,
            seasonal="add",
            seasonal_periods=12,
            initialization_method="estimated",
        ).fit()


def project(series: pd.Series, horizon: int, seed: int = 0) -> ForecastResult:
    """Project a monthly series (DatetimeIndex, values > 0) ``horizon`` months ahead."""
    y = series.astype(float).clip(lower=1.0)
    log_y = np.log(y).asfreq("MS")
    actual_tail = y.iloc[-12:].to_numpy()

    back = _fit_ets(log_y.iloc[:-12])
    mape_model = _mape(actual_tail, np.exp(back.forecast(12).to_numpy()))
    mape_naive = _mape(actual_tail, y.iloc[-24:-12].to_numpy())

    future = pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    if mape_model <= mape_naive:
        fit = _fit_ets(log_y)
        sims = fit.simulate(
            horizon, repetitions=500, anchor="end", error="add", rng=np.random.default_rng(seed)
        ).to_numpy()
        centre = np.exp(fit.forecast(horizon).to_numpy())
        q = np.exp(np.quantile(sims, [0.025, 0.10, 0.90, 0.975], axis=1))
        lo95, lo80, hi80, hi95 = q
        model = "ETS (additive damped trend + monthly seasonality, log values)"
    else:
        last_year = y.iloc[-12:].to_numpy()
        steps = np.arange(horizon)
        centre = last_year[steps % 12]
        sigma = np.log(y).diff(12).dropna().std()
        scale = np.sqrt(steps // 12 + 1)
        lo80, hi80 = centre * np.exp(-_Z80 * sigma * scale), centre * np.exp(_Z80 * sigma * scale)
        lo95, hi95 = centre * np.exp(-_Z95 * sigma * scale), centre * np.exp(_Z95 * sigma * scale)
        model = "Seasonal-naive (same month last year), because ETS did not beat it"

    hist = pd.DataFrame({"period": y.index, "value": series.to_numpy(), "kind": "actual"})
    proj = pd.DataFrame(
        {
            "period": future,
            "value": centre,
            "kind": "projection",
            "lo80": lo80,
            "hi80": hi80,
            "lo95": lo95,
            "hi95": hi95,
        }
    )
    frame = pd.concat([hist, proj], ignore_index=True)
    return ForecastResult(
        frame=frame, model=model, mape_model=mape_model, mape_naive=mape_naive, horizon=horizon
    )
