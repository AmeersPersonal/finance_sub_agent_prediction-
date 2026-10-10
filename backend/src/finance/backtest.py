"""Strategy metrics for backtests on non-overlapping holding periods.

Each period the strategy holds sign(signal) (long, short or flat) over one
horizon and pays `cost` (a fraction, e.g. 0.0005 = 5 bps) per unit of position
change, a simple stand-in for commissions, spread and slippage.
"""

from __future__ import annotations

import numpy as np


def strategy_returns(signal: np.ndarray, forward_returns: np.ndarray, cost: float) -> np.ndarray:
    position = np.sign(signal)
    turnover = np.abs(np.diff(np.concatenate([[0.0], position])))
    return position * forward_returns - cost * turnover


def sharpe(returns: np.ndarray, periods_per_year: float) -> float | None:
    std = returns.std(ddof=1)
    return float(returns.mean() / std * np.sqrt(periods_per_year)) if std > 0 else None


def sortino(returns: np.ndarray, periods_per_year: float) -> float | None:
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2))
    return float(returns.mean() / downside * np.sqrt(periods_per_year)) if downside > 0 else None


def max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1 + returns)
    return float((equity / np.maximum.accumulate(equity) - 1).min())


def profit_factor(returns: np.ndarray) -> float | None:
    losses = -returns[returns < 0].sum()
    return float(returns[returns > 0].sum() / losses) if losses > 0 else None


def summarize(returns: np.ndarray, periods_per_year: float) -> dict:
    return {
        "periods": int(len(returns)),
        "total_return_pct": float(np.prod(1 + returns) - 1) * 100,
        "sharpe": sharpe(returns, periods_per_year),
        "sortino": sortino(returns, periods_per_year),
        "max_drawdown_pct": max_drawdown(returns) * 100,
        "profit_factor": profit_factor(returns),
        "hit_rate": float((returns > 0).mean()),
    }
