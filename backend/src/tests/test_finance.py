from datetime import date

import pandas as pd
import pytest

from finance import indicators as ind
from finance.revenue_forecast import revenue_forecast


def series(values, start="2021-01-01", freq="D"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def test_rsi_extremes():
    assert ind.rsi(series(range(1, 40))) == 100.0
    assert ind.rsi(series(range(40, 1, -1))) == pytest.approx(0.0)
    assert ind.rsi(series([5.0] * 30)) == 50.0


def test_cagr_doubles_over_one_year():
    s = pd.Series([100.0, 200.0], index=pd.to_datetime(["2021-01-01", "2022-01-01"]))
    assert ind.cagr(s) == pytest.approx(1.0, rel=1e-2)


def test_max_drawdown():
    assert ind.max_drawdown(series([100, 120, 60, 90])) == pytest.approx(-0.5)


def test_position_and_percentile():
    s = series([10, 20, 15])
    assert ind.position_in_range(s) == pytest.approx(0.5)
    assert ind.percentile_rank(s) == pytest.approx(0.5)


def test_macd_follows_the_trend():
    rising = series([100 + i + (i % 3) for i in range(80)])
    assert ind.macd(rising)["macd"] > 0
    assert ind.macd(series(list(reversed(rising.tolist()))))["macd"] < 0


def test_atr_of_constant_bars():
    close = series([100.0] * 40)
    daily = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close})
    assert ind.atr(daily) == pytest.approx(2.0)


def test_volume_profile_centres_on_the_busiest_price():
    prices = series([100.0] * 30 + [110.0] * 5 + [90.0] * 5, freq="5min")
    bars = pd.DataFrame({"High": prices + 0.5, "Low": prices - 0.5, "Close": prices,
                         "Volume": [1000.0] * 30 + [10.0] * 10})
    profile = ind.volume_profile(bars)
    assert profile["point_of_control"] == pytest.approx(100.0, abs=1.0)
    assert profile["value_area_low"] <= 100.0 <= profile["value_area_high"]
    assert profile["value_area_high"] < 110.0  # thin volume up there stays outside


def test_flat_band_scales_with_volatility_and_horizon(snapshot):
    close = snapshot.daily["Close"]
    one_day = ind.flat_band(close, 1)
    assert one_day > 0
    assert ind.flat_band(close, 4) == pytest.approx(2 * one_day)  # sqrt(4) x
    calmer = close.iloc[0] * (close / close.iloc[0]) ** 0.5  # half the log-volatility
    assert ind.flat_band(calmer, 1) == pytest.approx(one_day / 2)


def test_outcome_base_rates_count_only_finished_windows():
    rising = series([100 * 1.01 ** k for k in range(300)])
    rates = ind.outcome_base_rates(rising, 5)
    assert rates["up"] == 1.0 and rates["flat"] == rates["down"] == 0.0
    assert rates["windows"] == 300 - 21 - 5  # the band needs 21 returns; the last 5 are unknown
    assert ind.outcome_base_rates(rising, 5, lookback=50)["windows"] == 50
    with pytest.raises(ValueError):
        ind.outcome_base_rates(series([100, 101, 102]), 5)


def test_flat_band_needs_some_history():
    with pytest.raises(ValueError):
        ind.flat_band(series([100, 101, 102]), 5)


def test_total_return_needs_enough_history():
    with pytest.raises(ValueError):
        ind.total_return(series([1, 2]), 5)


def test_options_sentiment_picks_expiry_a_week_out(snapshot):
    result = ind.options_sentiment(
        snapshot.options.calls, snapshot.options.puts, snapshot.last_price, date(2026, 10, 9)
    )
    assert result["put_call_volume_ratio"] == pytest.approx(0.5)
    assert result["atm_iv_expiry"] == "2026-10-23"
    assert result["atm_implied_volatility"] == pytest.approx(0.30)


def test_revenue_forecast(snapshot):
    result = revenue_forecast(snapshot.income_stmt)
    assert result["latest_fiscal_year_end"] == "2025-09-30"
    assert result["yoy_growth_pct"] == [10.0, 9.09, 8.33]
    assert result["naive_extrapolation_next_year"] > 130e9
    assert result["caveat"].startswith("Not a forecast")


def test_revenue_forecast_missing_data():
    assert revenue_forecast(None) is None
    assert revenue_forecast(pd.DataFrame(index=["Net Income"])) is None
