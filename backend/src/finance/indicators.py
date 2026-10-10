"""Price, volatility and options metrics.

Agents receive these computed numbers rather than raw price rows: LLMs do
arithmetic over long tables badly, and 5 years of daily bars wastes tokens.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# P(|Z| < 0.25) is about 20%, so with a band of 0.25 standard deviations of the
# horizon's move, roughly one outcome in five counts as "flat" for any stock.
# A fixed +/-1% band was flat 38% of the time for SPY but 10% for TSLA.
FLAT_BAND_K = 0.25


def rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (0-100) at every bar."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    values = 100 - 100 / (1 + gain / loss)
    return values.where(loss != 0, np.where(gain > 0, 100.0, 50.0))


def rsi(close: pd.Series, period: int = 14) -> float:
    return float(rsi_series(close, period).iloc[-1])


def flat_band_series(
    close: pd.Series, horizon_days: int, lookback: int = TRADING_DAYS
) -> pd.Series:
    """Point-in-time flat band (a fraction, e.g. 0.0087) from trailing daily volatility."""
    daily_vol = np.log(close).diff().rolling(lookback, min_periods=21).std()
    return FLAT_BAND_K * daily_vol * np.sqrt(horizon_days)


def flat_band(close: pd.Series, horizon_days: int) -> float:
    band = float(flat_band_series(close, horizon_days).iloc[-1])
    if not np.isfinite(band):
        raise ValueError("Not enough price history to size the flat band")
    return band


def classify_move(ret: float, band: float) -> str:
    """'up' / 'down' if the return clears the band, otherwise 'flat'."""
    return "up" if ret > band else "down" if ret < -band else "flat"


def sma(close: pd.Series, window: int) -> float:
    if len(close) < window:
        raise ValueError(f"need {window} bars, have {len(close)}")
    return float(close.iloc[-window:].mean())


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, float]:
    """MACD line, signal line and histogram at the last two bars (price units)."""
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    histogram = line - line.ewm(span=signal, adjust=False).mean()
    return {
        "macd": float(line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "histogram_prev": float(histogram.iloc[-2]),
    }


def atr(daily: pd.DataFrame, period: int = 14) -> float:
    """Wilder's average true range at the last bar (price units)."""
    prev_close = daily["Close"].shift(1)
    true_range = pd.concat(
        [
            daily["High"] - daily["Low"],
            (daily["High"] - prev_close).abs(),
            (daily["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return float(true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().iloc[-1])


def volume_profile(
    intraday: pd.DataFrame, bins: int = 24, value_area: float = 0.7
) -> dict[str, float]:
    """Volume at price: the point of control (busiest price bucket) and the value area,
    the contiguous range around it holding `value_area` of the volume.

    Yahoo's intraday volumes don't sum to real daily totals, but the relative
    distribution across prices is what matters here.
    """
    low, high = float(intraday["Low"].min()), float(intraday["High"].max())
    if high <= low or intraday["Volume"].sum() == 0:
        raise ValueError("no price range or no volume")
    typical = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
    edges = np.linspace(low, high, bins + 1)
    volume, _ = np.histogram(typical, bins=edges, weights=intraday["Volume"])

    lo = hi = int(np.argmax(volume))
    covered, target = volume[lo], value_area * volume.sum()
    while covered < target:
        below = volume[lo - 1] if lo > 0 else -1.0
        above = volume[hi + 1] if hi < bins - 1 else -1.0
        if above >= below:
            hi += 1
            covered += volume[hi]
        else:
            lo -= 1
            covered += volume[lo]
    poc = int(np.argmax(volume))
    return {
        "point_of_control": float((edges[poc] + edges[poc + 1]) / 2),
        "value_area_low": float(edges[lo]),
        "value_area_high": float(edges[hi + 1]),
    }


def latest_session(intraday: pd.DataFrame) -> pd.DataFrame:
    """Rows of the most recent trading day in an intraday frame."""
    return intraday[intraday.index.date == intraday.index[-1].date()]


def vwap(session: pd.DataFrame) -> float:
    typical = (session["High"] + session["Low"] + session["Close"]) / 3
    volume = session["Volume"].sum()
    if volume == 0:
        raise ValueError("session has no volume")
    return float((typical * session["Volume"]).sum() / volume)


def total_return(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        raise ValueError(f"need more than {days} bars, have {len(close)}")
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1)


def cagr(close: pd.Series) -> float:
    years = (close.index[-1] - close.index[0]).days / 365.25
    if years <= 0:
        raise ValueError("series spans no time")
    return float((close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1)


def max_drawdown(close: pd.Series) -> float:
    """Worst peak-to-trough fall, as a negative fraction."""
    return float((close / close.cummax() - 1).min())


def annualized_volatility(close: pd.Series) -> float:
    return float(np.log(close).diff().std() * np.sqrt(TRADING_DAYS))


def position_in_range(close: pd.Series) -> float:
    """Where the last close sits between the series low (0) and high (1)."""
    low, high = close.min(), close.max()
    return float((close.iloc[-1] - low) / (high - low)) if high > low else 0.5


def percentile_rank(series: pd.Series) -> float:
    """Share of observations below the latest value (0-1)."""
    return float((series.iloc[:-1] < series.iloc[-1]).mean())


def relative_strength(asset_close: pd.Series, benchmark_close: pd.Series, days: int) -> float:
    """Asset return minus benchmark return over the same `days` (a fraction)."""
    return total_return(asset_close, days) - total_return(benchmark_close, days)


def beta(asset_close: pd.Series, market_close: pd.Series) -> float:
    returns = pd.concat(
        [asset_close.pct_change(), market_close.pct_change()], axis=1, join="inner"
    ).dropna()
    asset, market = returns.iloc[:, 0], returns.iloc[:, 1]
    return float(asset.cov(market) / market.var())


def options_sentiment(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float, as_of: date, min_days: int = 7
) -> dict[str, float | str | None]:
    """Put/call ratios across all supplied expiries, plus at-the-money implied vol.

    ATM IV uses the first expiry at least `min_days` out (very short-dated IV is
    noisy), falling back to the furthest expiry supplied. Frames need `strike`,
    `volume`, `openInterest`, `impliedVolatility` and `expiry` (YYYY-MM-DD) columns.
    """
    call_volume, put_volume = calls["volume"].fillna(0).sum(), puts["volume"].fillna(0).sum()
    call_oi, put_oi = calls["openInterest"].fillna(0).sum(), puts["openInterest"].fillna(0).sum()

    expiries = sorted(set(calls["expiry"]) | set(puts["expiry"]))
    iv_expiry = next(
        (e for e in expiries if (date.fromisoformat(e) - as_of).days >= min_days), expiries[-1]
    )

    def atm_iv(chain: pd.DataFrame) -> float | None:
        usable = chain[(chain["expiry"] == iv_expiry) & chain["impliedVolatility"].between(0.01, 5)]
        if usable.empty:
            return None
        return float(usable.loc[(usable["strike"] - spot).abs().idxmin(), "impliedVolatility"])

    ivs = [iv for iv in (atm_iv(calls), atm_iv(puts)) if iv is not None]
    return {
        "put_call_volume_ratio": float(put_volume / call_volume) if call_volume else None,
        "put_call_open_interest_ratio": float(put_oi / call_oi) if call_oi else None,
        "atm_implied_volatility": float(np.mean(ivs)) if ivs else None,
        "atm_iv_expiry": iv_expiry,
    }
