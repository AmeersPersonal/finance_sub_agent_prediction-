"""Price-history charts from saved bars (`DatabaseRepository.get_price_history`)."""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from charts.base import chart, iso, num, numbers
from finance import indicators

MIN_BARS = 2
EXCHANGE_TZ = "America/New_York"  # daily bars are stored at midnight here; sessions end here too


def _frame(bars: Sequence[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(bars))
    frame["bar_at"] = pd.to_datetime(frame["bar_at"], utc=True).dt.tz_convert(EXCHANGE_TZ)
    columns = ["open", "high", "low", "close", "volume"]
    frame[columns] = frame[columns].apply(pd.to_numeric, errors="coerce")  # Decimal -> float
    return frame.set_index("bar_at").sort_index().dropna(subset=["close"])


def _intraday_charts(frame: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """A session VWAP line for the price chart, and the volume-at-price chart."""
    ohlc = frame.rename(columns={"high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    vwap = {"name": "VWAP", "kind": "line", "data": numbers(indicators.vwap_series(ohlc))}
    try:
        edges, volume = indicators.volume_by_price(ohlc)
        profile = indicators.volume_profile(ohlc)
    except ValueError:  # no price range or no volume
        return [vwap], []
    middles = (edges[:-1] + edges[1:]) / 2
    return [vwap], [chart(
        "volume_profile", "Volume at price", "bar", [round(float(m), 2) for m in middles],
        [{"name": "Volume", "kind": "bar", "data": numbers(volume, 0)}],
        y_label="Shares",
        reference_lines=[
            {"label": "Point of control", "value": num(profile["point_of_control"], 2), "axis": "x"},
            {"label": "Value area low", "value": num(profile["value_area_low"], 2), "axis": "x"},
            {"label": "Value area high", "value": num(profile["value_area_high"], 2), "axis": "x"},
        ],
        caption="Where trading happened across the bars shown. The value area holds about "
                "70% of the volume. Intraday volumes are indicative, not exchange totals.",
    )]


def price_charts(
    bars: Sequence[dict[str, Any]], ticker: str, interval: str = "1d"
) -> list[dict[str, Any]]:
    """Candles with moving averages, volume, RSI, MACD and drawdown; for `5m` bars also
    the session VWAP and a volume profile.

    Indicators are computed over the supplied bars, so the first values of a
    short series are `null` rather than guessed.
    """
    if len(bars) < MIN_BARS:
        return []
    frame = _frame(bars)
    if len(frame) < MIN_BARS:
        return []
    x, close = iso(frame.index, daily=interval == "1d"), frame["close"]
    macd = indicators.macd_series(close)
    drawdown = (close / close.cummax() - 1) * 100

    overlays, extra = [], []
    if interval != "1d":
        overlays, extra = _intraday_charts(frame)

    return [
        chart(
            "price", f"{ticker} price", "candlestick", x,
            [
                {"name": "Price", "kind": "candlestick",
                 "data": [numbers(row) for row in frame[["open", "high", "low", "close"]].to_numpy()]},
                {"name": "SMA 20", "kind": "line", "data": numbers(close.rolling(20).mean())},
                {"name": "SMA 50", "kind": "line", "data": numbers(close.rolling(50).mean())},
                *overlays,
            ],
            y_label="Price", caption="Total-return adjusted closes saved by the backend.",
        ),
        chart("volume", "Volume", "bar", x,
              [{"name": "Volume", "kind": "bar", "data": numbers(frame["volume"], 0)}],
              y_label="Shares"),
        chart(
            "rsi", "RSI (14)", "line", x,
            [{"name": "RSI", "kind": "line", "data": numbers(indicators.rsi_series(close), 2)}],
            reference_lines=[{"label": "Overbought", "value": 70}, {"label": "Oversold", "value": 30}],
            caption="Above 70 is often read as stretched, below 30 as depressed. Neither is a signal on its own.",
        ),
        chart(
            "macd", "MACD (12, 26, 9)", "line", x,
            [
                {"name": "MACD", "kind": "line", "data": numbers(macd["macd"])},
                {"name": "Signal", "kind": "line", "data": numbers(macd["signal"])},
                {"name": "Histogram", "kind": "bar", "data": numbers(macd["histogram"])},
            ],
            y_label="Price units",
        ),
        chart("drawdown", "Drawdown from peak", "line", x,
              [{"name": "Drawdown", "kind": "line", "data": numbers(drawdown, 2)}],
              y_label="%", caption="How far the price sits below its highest close in this window."),
        *extra,
    ]
