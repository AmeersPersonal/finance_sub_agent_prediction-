"""Linear regression on price features: the statistical bar the personas must clear.

Predicts the forward N-trading-day return from features known at each day's
close (momentum, RSI, volatility, trend, volume), fit by ordinary least squares
on standardized features.

Evaluation is walk-forward over the most recent 20% of history: the model is
refit every N days on an expanding window that holds only targets already
known on that day, never on a random split that would leak the future. Trading
the signal is then measured on non-overlapping N-day periods with transaction
costs, against buy-and-hold over the same periods.

Expect an out-of-sample R^2 near zero or below: daily price features carry
little linear signal. That's the point of a baseline. It is deliberately kept
out of the persona prompts so the two predictions stay independent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from finance.backtest import strategy_returns, summarize
from finance.indicators import TRADING_DAYS, flat_band_series, rsi_series

FEATURES = (
    "return_1d",
    "return_5d",
    "return_21d",
    "rsi_14",
    "volatility_21d",
    "dist_from_sma50",
    "volume_vs_20d",
)


def build_features(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per day, using only data up to and including that day's close."""
    close, volume = daily["Close"], daily["Volume"]
    features = pd.DataFrame(
        {
            "return_1d": close.pct_change(1),
            "return_5d": close.pct_change(5),
            "return_21d": close.pct_change(21),
            "rsi_14": rsi_series(close) / 100,
            "volatility_21d": np.log(close).diff().rolling(21).std(),
            "dist_from_sma50": close / close.rolling(50).mean() - 1,
            "volume_vs_20d": volume / volume.rolling(20).mean(),
        },
        columns=FEATURES,
    )
    return features.replace([np.inf, -np.inf], np.nan)


def forward_return(close: pd.Series, horizon_days: int) -> pd.Series:
    return close.shift(-horizon_days) / close - 1


@dataclass(frozen=True)
class LinearModel:
    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray  # [intercept, one weight per standardized feature]

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.coef[0] + ((X - self.mean) / self.std) @ self.coef[1:]


def fit(X: np.ndarray, y: np.ndarray) -> LinearModel:
    mean, std = X.mean(axis=0), X.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    design = np.column_stack([np.ones(len(X)), (X - mean) / std])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return LinearModel(mean, std, coef)


def walk_forward(
    X: np.ndarray, y: np.ndarray, start: int, horizon_days: int
) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-sample predictions for rows start..end, plus the historical-mean
    benchmark forecast for each (for R^2).

    Row j's target uses prices up to day j + horizon_days, so on day i only rows
    j <= i - horizon_days have known targets. The model is refit every
    `horizon_days` rows on exactly those.
    """
    predictions, benchmarks = np.empty(len(X) - start), np.empty(len(X) - start)
    model: LinearModel | None = None
    for k, i in enumerate(range(start, len(X))):
        known_end = i - horizon_days + 1
        if model is None or k % horizon_days == 0:
            model = fit(X[:known_end], y[:known_end])
        predictions[k] = model.predict(X[i : i + 1])[0]
        benchmarks[k] = y[:known_end].mean()
    return predictions, benchmarks


@dataclass(frozen=True)
class RegressionResult:
    horizon_days: int
    predicted_return_pct: float
    features_as_of: str
    coefficients: dict[str, float]  # return change (in %) per 1 std move in the feature
    oos_r2: float
    oos_accuracy: float  # sign call vs actual up/flat/down, walk-forward window
    always_up_accuracy: float  # same window, same scoring
    n_train: int  # rows in the first walk-forward fit
    n_test: int
    test_start: str
    cost_bps: float
    strategy: dict  # trading the sign of the prediction, non-overlapping periods, after costs
    buy_and_hold: dict  # same periods


def run_regression(
    daily: pd.DataFrame, horizon_days: int, test_fraction: float = 0.2, cost_bps: float = 5.0
) -> RegressionResult:
    close = daily["Close"]
    features = build_features(daily)
    target = forward_return(close, horizon_days)
    band = flat_band_series(close, horizon_days)

    has_features = features.notna().all(axis=1)
    known = has_features & target.notna() & band.notna()
    X, y, b = features[known].to_numpy(), target[known].to_numpy(), band[known].to_numpy()
    if len(X) < 100:
        raise ValueError(f"Need at least 100 usable days for the regression, have {len(X)}")

    split = int(len(X) * (1 - test_fraction))
    predicted, benchmark = walk_forward(X, y, split, horizon_days)
    actual = y[split:]
    outcome = np.where(actual > b[split:], "up", np.where(actual < -b[split:], "down", "flat"))
    call = np.where(predicted > 0, "up", "down")
    oos_r2 = 1 - np.sum((actual - predicted) ** 2) / np.sum((actual - benchmark) ** 2)

    periods = slice(None, None, horizon_days)  # non-overlapping holding periods
    cost, per_year = cost_bps / 10_000, TRADING_DAYS / horizon_days
    traded = strategy_returns(predicted[periods], actual[periods], cost)
    held = strategy_returns(np.ones_like(actual[periods]), actual[periods], cost)

    final = fit(X, y)
    latest = features[has_features].iloc[[-1]]
    return RegressionResult(
        horizon_days=horizon_days,
        predicted_return_pct=round(float(final.predict(latest.to_numpy())[0]) * 100, 3),
        features_as_of=str(latest.index[0].date()),
        coefficients={f: round(float(c) * 100, 4) for f, c in zip(FEATURES, final.coef[1:])},
        oos_r2=round(float(oos_r2), 4),
        oos_accuracy=round(float((call == outcome).mean()), 4),
        always_up_accuracy=round(float((outcome == "up").mean()), 4),
        n_train=split - horizon_days + 1,
        n_test=len(actual),
        test_start=str(features[known].index[split].date()),
        cost_bps=cost_bps,
        strategy=summarize(traded, per_year),
        buy_and_hold=summarize(held, per_year),
    )
