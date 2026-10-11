import numpy as np
import pandas as pd
import pytest

from finance.linear_regression import FEATURES, build_features, fit, forward_return, run_regression


def test_fit_recovers_a_linear_relationship():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 3)) * [1.0, 5.0, 0.1]
    y = 0.5 + 2 * X[:, 0] - 0.3 * X[:, 1] + 10 * X[:, 2]
    model = fit(X, y)
    X_new = rng.normal(size=(20, 3))
    np.testing.assert_allclose(
        model.predict(X_new), 0.5 + 2 * X_new[:, 0] - 0.3 * X_new[:, 1] + 10 * X_new[:, 2],
        atol=1e-8,
    )


def test_forward_return_looks_ahead_only_in_the_target():
    close = pd.Series([100.0, 110.0, 121.0])
    np.testing.assert_allclose(forward_return(close, 1).to_numpy()[:2], [0.1, 0.1])
    assert np.isnan(forward_return(close, 1).iloc[-1])


def test_features_use_no_future_data(snapshot):
    daily = snapshot.daily
    changed = daily.copy()
    changed.iloc[-10:, changed.columns.get_loc("Close")] *= 2  # rewrite the last 10 days
    before, after = build_features(daily), build_features(changed)
    pd.testing.assert_frame_equal(before.iloc[:-10], after.iloc[:-10])


def test_run_regression_on_a_random_walk(snapshot):
    result = run_regression(snapshot.daily, horizon_days=5)
    assert set(result.coefficients) == set(FEATURES)
    assert result.features_as_of == "2026-10-09"
    assert result.n_test > 200 and result.n_train > 800
    assert 0 <= result.oos_accuracy <= 1 and 0 <= result.always_up_accuracy <= 1
    assert result.oos_r2 < 0.1  # a random walk has nothing to find


def test_too_little_history_raises(snapshot):
    with pytest.raises(ValueError, match="100 usable days"):
        run_regression(snapshot.daily.iloc[-120:], horizon_days=5)
