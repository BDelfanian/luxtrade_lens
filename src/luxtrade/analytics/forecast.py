"""Projections: ETS with a seasonal-naive back-test (SOLUTION_DESIGN §5.5).

"We extend the seasonal pattern and the damped trend, check that this beats 'same as last
year', and show how uncertain it is." The fitted parameters (smoothing of level, trend and
season, trend damping), the fitting window and yearly totals with their 80 % ranges (summed
over the simulated paths) are kept, so an answer can say how the projection was made.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from luxtrade.config import FORECAST_MIN_MONTHS

_Z80, _Z95 = 1.2816, 1.96
SIMULATIONS = 500


@dataclass
class ForecastResult:
    """Projection plus the evidence for choosing it."""

    frame: pd.DataFrame  # period, value, kind (actual/projection), lo80, hi80, lo95, hi95
    model: str
    mape_model: float
    mape_naive: float
    horizon: int
    params: dict = field(default_factory=dict)  # alpha, beta, gamma, phi (ETS) or sigma (naive)
    fitted: tuple[str, str, int] = ("", "", 0)  # first and last month fitted, months
    annual: pd.DataFrame = field(default_factory=pd.DataFrame)  # year, months, value, lo80, hi80

    def method_note(self) -> str:
        """One-line method description for the trace: model, parameters, data, back-test."""
        p = self.params
        if "alpha" in p:
            fitted = (
                f"smoothing α (level) {p['alpha']:.2f}, β (trend) {p['beta']:.2f}, "
                f"γ (season) {p['gamma']:.2f}, damping φ {p['phi']:.2f}"
            )
        else:
            fitted = f"σ of the yearly log change {p.get('sigma', 0):.3f}"
        first, last, months = self.fitted
        return (
            f"{self.model}; {fitted}; fitted on {months} months ({first} to {last}); back-test "
            f"on the last 12 months: MAPE {self.mape_model:.1f} % (seasonal-naive "
            f"{self.mape_naive:.1f} %); 80 and 95 % intervals from {SIMULATIONS} simulated paths"
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
            horizon,
            repetitions=SIMULATIONS,
            anchor="end",
            error="add",
            rng=np.random.default_rng(seed),
        ).to_numpy()
        centre = np.exp(fit.forecast(horizon).to_numpy())
        q = np.exp(np.quantile(sims, [0.025, 0.10, 0.90, 0.975], axis=1))
        lo95, lo80, hi80, hi95 = q
        model = "ETS (additive damped trend + monthly seasonality, log values)"
        params = {
            "alpha": float(fit.params["smoothing_level"]),
            "beta": float(fit.params["smoothing_trend"]),
            "gamma": float(fit.params["smoothing_seasonal"]),
            "phi": float(fit.params["damping_trend"]),
        }
        paths = np.exp(sims)  # months × simulations, in values
    else:
        last_year = y.iloc[-12:].to_numpy()
        steps = np.arange(horizon)
        centre = last_year[steps % 12]
        sigma = np.log(y).diff(12).dropna().std()
        scale = np.sqrt(steps // 12 + 1)
        lo80, hi80 = centre * np.exp(-_Z80 * sigma * scale), centre * np.exp(_Z80 * sigma * scale)
        lo95, hi95 = centre * np.exp(-_Z95 * sigma * scale), centre * np.exp(_Z95 * sigma * scale)
        model = "Seasonal-naive (same month last year), because ETS did not beat it"
        params = {"sigma": float(sigma)}
        rng = np.random.default_rng(seed)  # paths for the yearly ranges, as for ETS
        shocks = rng.normal(0.0, 1.0, (horizon, SIMULATIONS)) * (sigma * scale)[:, None]
        paths = centre[:, None] * np.exp(shocks)

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
        frame=frame,
        model=model,
        mape_model=mape_model,
        mape_naive=mape_naive,
        horizon=horizon,
        params=params,
        fitted=(f"{y.index[0]:%b %Y}", f"{y.index[-1]:%b %Y}", len(y)),
        annual=_annual(future, centre, paths),
    )


def _annual(future: pd.DatetimeIndex, centre: np.ndarray, paths: np.ndarray) -> pd.DataFrame:
    """Projected totals per calendar year, with the 80 % range of the summed simulated paths."""
    rows = []
    for year in sorted(set(future.year)):
        idx = np.flatnonzero(future.year == year)
        totals = paths[idx].sum(axis=0)
        rows.append(
            {
                "year": int(year),
                "months": len(idx),
                "value": float(centre[idx].sum()),
                "lo80": float(np.quantile(totals, 0.10)),
                "hi80": float(np.quantile(totals, 0.90)),
            }
        )
    return pd.DataFrame(rows)
