"""Convert stored daily prices into validated model input, independent of the model."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

import numpy as np
import pandas as pd

from ai.evaluation import MARKET_TZ


class ModelDataError(ValueError):
    """Stored data cannot safely be used by a numerical model."""


def load_daily_prices(repository, ticker: str, *, cutoff: datetime,
                      start_at: datetime | None = None,
                      end_at: datetime | None = None) -> pd.DataFrame:
    """Load the complete requested history with Close/Volume and a market-time index.

    Never fills gaps with invented data or mixes providers/adjustment bases.
    The regression's own feature builder still enforces usable training history.
    """
    for timestamp in (cutoff, start_at, end_at):
        if timestamp is not None and timestamp.tzinfo is None:
            raise ModelDataError("Model dataset bounds must include a timezone.")
    rows = repository.get_model_price_rows(ticker, cutoff=cutoff, start_at=start_at, end_at=end_at)
    return daily_prices_from_rows(rows)


def load_daily_prices_as_known(repository, ticker: str, *, as_of: datetime,
                               start_at: datetime | None = None,
                               end_at: datetime | None = None) -> pd.DataFrame:
    """Daily prices exactly as the database knew them at `as_of`, corrections made
    since undone from the revision archive (migration 008). `load_daily_prices`
    instead reads the latest corrected values fetched by its cutoff."""
    for timestamp in (as_of, start_at, end_at):
        if timestamp is not None and timestamp.tzinfo is None:
            raise ModelDataError("Model dataset bounds must include a timezone.")
    rows = repository.get_price_history_as_of(ticker, as_of=as_of, interval="1d",
                                              start_at=start_at, end_at=end_at)
    return daily_prices_from_rows(rows)


def daily_prices_from_rows(rows) -> pd.DataFrame:
    """Validate both mutable stored bars and frozen forecast dataset rows."""
    if not rows:
        raise ModelDataError("No saved daily prices match the requested dataset.")
    frame = pd.DataFrame(rows)
    try:
        index = pd.to_datetime(frame.pop("bar_at"), utc=True, errors="raise")
        frame = frame.rename(columns={"close": "Close", "volume": "Volume"})[["Close", "Volume"]]
        frame = frame.apply(pd.to_numeric, errors="raise").astype(float)
    except (ValueError, TypeError, KeyError):
        raise ModelDataError("Saved price rows contain invalid timestamps or numbers.") from None
    frame.index = pd.DatetimeIndex(index).tz_convert(MARKET_TZ)
    frame.index.name = "Date"
    frame = frame.sort_index()
    if frame.index.normalize().duplicated().any():
        raise ModelDataError("Saved daily data contains duplicate market-session dates.")
    if not np.isfinite(frame.to_numpy()).all():
        raise ModelDataError("Saved closing prices and volumes must be present and finite.")
    if (frame["Close"] <= 0).any() or (frame["Volume"] < 0).any():
        raise ModelDataError("Closing prices must be positive and volume non-negative.")
    return frame


def dataset_metadata(frame: pd.DataFrame, *, cutoff: datetime) -> dict:
    return {
        "source": "postgresql", "table": "price_bars", "provider": "yfinance",
        "interval": "1d", "adjustment_basis": "total_return", "rows": len(frame),
        "start_date": str(frame.index[0].date()), "end_date": str(frame.index[-1].date()),
        "cutoff_at": cutoff.isoformat(), "columns": list(frame.columns),
        "sha256": sha256(frame.to_json(orient="split", date_format="iso").encode()).hexdigest(),
    }
