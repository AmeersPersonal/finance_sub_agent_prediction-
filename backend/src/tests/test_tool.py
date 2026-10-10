from datetime import date, datetime

import numpy as np
import pandas as pd

from ai.evaluation import baselines
from ai.tool import _earnings_dates, _news_items, clean_daily


def _unfinalised(daily: pd.DataFrame) -> pd.DataFrame:
    """The latest bar as Yahoo sometimes serves it: volume, but NaN prices."""
    daily = daily.copy()
    daily.loc[daily.index[-1], ["Open", "High", "Low", "Close"]] = np.nan
    return daily


def test_clean_daily_fills_an_unfinalised_last_bar_from_the_quote(snapshot):
    raw = _unfinalised(snapshot.daily)
    assert baselines(raw["Close"], 5, None)["momentum"] == "down"  # the bug: NaN >= x is False
    cleaned = clean_daily(raw, last_price=123.0)
    assert len(cleaned) == len(raw) and cleaned.index[-1] == raw.index[-1]
    assert cleaned.iloc[-1][["Open", "High", "Low", "Close"]].tolist() == [123.0] * 4
    assert cleaned["Volume"].iloc[-1] == raw["Volume"].iloc[-1]


def test_clean_daily_drops_bars_it_cannot_fill(snapshot):
    raw = _unfinalised(snapshot.daily)
    raw.loc[raw.index[10], "Close"] = np.nan
    cleaned = clean_daily(raw)  # no quote
    assert len(cleaned) == len(raw) - 2 and cleaned["Close"].notna().all()
    pd.testing.assert_frame_equal(clean_daily(snapshot.daily, 1.0), snapshot.daily)  # clean data untouched


def test_earnings_dates_handles_yfinance_shapes():
    assert _earnings_dates({"Earnings Date": [date(2026, 11, 2)]}) == [date(2026, 11, 2)]
    window = {"Earnings Date": [datetime(2026, 11, 5, 16), date(2026, 11, 2)]}
    assert _earnings_dates(window) == [date(2026, 11, 2), date(2026, 11, 5)]
    assert _earnings_dates({"Earnings Date": date(2026, 11, 2)}) == [date(2026, 11, 2)]
    assert _earnings_dates({}) == [] and _earnings_dates(None) == []


def test_news_items_handle_both_yfinance_layouts():
    news = [
        {"title": "Flat", "link": "https://a.example/1", "publisher": "Reuters",
         "providerPublishTime": 1760000000},
        {"content": {"title": "Nested", "summary": "More.", "pubDate": "2026-10-09T12:00:00Z",
                     "canonicalUrl": {"url": "https://b.example/2"},
                     "provider": {"displayName": "Yahoo Finance"}}},
        {"content": {}},
    ]
    flat, nested = _news_items(news)
    assert (flat.title, flat.link, flat.source, flat.published) == (
        "Flat", "https://a.example/1", "Reuters", "1760000000"
    )
    assert (nested.title, nested.link, nested.summary, nested.source) == (
        "Nested", "https://b.example/2", "More.", "Yahoo Finance"
    )
    assert _news_items(None) == []
