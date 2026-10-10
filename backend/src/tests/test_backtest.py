import numpy as np
import pytest

from finance.backtest import max_drawdown, profit_factor, sharpe, sortino, strategy_returns, summarize
from finance.linear_regression import run_regression, walk_forward


def test_strategy_returns_charge_costs_on_position_changes():
    returns = strategy_returns(np.array([1.0, 2.0, -0.5]), np.array([0.01, 0.02, -0.01]), 0.001)
    # long (enter: 1 unit), long (no change), short (flip: 2 units)
    np.testing.assert_allclose(returns, [0.009, 0.02, 0.008])


def test_metrics():
    r = np.array([0.02, -0.01, 0.03, -0.02])
    assert max_drawdown(np.array([0.1, -0.5, 0.2])) == pytest.approx(-0.5)
    assert profit_factor(r) == pytest.approx(0.05 / 0.03)
    assert profit_factor(np.array([0.01, 0.02])) is None  # no losing periods
    assert sharpe(np.full(5, 0.01), 52) is None  # zero volatility
    assert sharpe(r, 52) == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(52))
    assert sortino(r, 52) > sharpe(r, 52)  # upside volatility isn't penalised
    assert summarize(r, 52)["hit_rate"] == 0.5


def test_walk_forward_never_trains_on_unknown_targets():
    rng = np.random.default_rng(1)
    X, y = rng.normal(size=(300, 4)), rng.normal(size=300)
    start, horizon, changed_from = 100, 5, 150
    before, _ = walk_forward(X, y, start, horizon)
    y_later = y.copy()
    y_later[changed_from:] += 100  # rewrite the future
    after, _ = walk_forward(X, y_later, start, horizon)
    # On day i only targets of rows <= i - horizon are known.
    unaffected = changed_from + horizon - start
    np.testing.assert_array_equal(before[:unaffected], after[:unaffected])
    assert not np.allclose(before[unaffected:], after[unaffected:])


def test_regression_reports_strategy_and_buy_and_hold(snapshot):
    result = run_regression(snapshot.daily, horizon_days=5)
    periods = -(-result.n_test // 5)  # one per non-overlapping 5-day period
    assert result.strategy["periods"] == result.buy_and_hold["periods"] == periods
    assert result.cost_bps == 5.0
