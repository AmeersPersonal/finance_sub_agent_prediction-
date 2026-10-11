"""Walk-forward regression backtest charts: the baseline's equity curve vs buy and hold."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from charts.base import chart, iso, numbers
from charts.price import _frame
from finance import linear_regression

START_VALUE = 100.0


def backtest_charts(
    bars: Sequence[dict[str, Any]], ticker: str, horizon_days: int
) -> list[dict[str, Any]]:
    """Growth of 100 for trading the regression's sign vs holding, plus each period's return.

    Uses the same walk-forward window, non-overlapping periods and 5 bps costs
    as `run_regression`, so the end of the curve matches its summary. Returns
    `[]` when there isn't enough history (about a year and a half of daily bars).
    """
    if len(bars) < 2:
        return []
    daily = _frame(bars).rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    try:
        periods = linear_regression.period_returns(daily, horizon_days)
    except ValueError:
        return []

    x = iso(pd.DatetimeIndex([periods.index[0], *periods["end"]]), daily=True)
    growth = {
        name: START_VALUE * np.concatenate([[1.0], np.cumprod(1 + periods[name].to_numpy())])
        for name in ("strategy", "buy_and_hold")
    }
    labels = iso(periods["end"], daily=True)
    return [
        chart(
            "equity_curve", f"{ticker}: regression vs buy and hold", "line", x,
            [
                {"name": "Regression", "kind": "line", "data": numbers(growth["strategy"], 2)},
                {"name": "Buy and hold", "kind": "line", "data": numbers(growth["buy_and_hold"], 2)},
            ],
            y_label=f"Growth of {START_VALUE:g}",
            caption=f"Out-of-sample, {horizon_days}-day non-overlapping periods, 5 bps costs. "
                    "The regression is a baseline the personas must beat, not a recommendation.",
        ),
        chart(
            "period_returns", "Return per holding period", "bar", labels,
            [
                {"name": "Regression", "kind": "bar", "data": numbers(periods["strategy"] * 100, 2)},
                {"name": "Buy and hold", "kind": "bar", "data": numbers(periods["buy_and_hold"] * 100, 2)},
            ],
            y_label="%", caption="Labelled by the day each period closes.",
        ),
    ]
