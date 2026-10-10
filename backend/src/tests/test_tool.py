from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ai import tool
from ai.evaluation import baselines
from ai.feeds import NewsItem
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


# --- fetch_snapshot against a fake yf.Ticker (recorded shapes, no network) ---------


def _bars(days=300, start=100.0, freq="B"):
    index = pd.date_range(end="2026-10-09", periods=days, freq=freq, tz="America/New_York")
    close = start * np.exp(np.linspace(0, 0.2, days))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(days, 1e6)}, index=index)


class FakeTicker:
    """yfinance.Ticker's surface as fetch_snapshot uses it. `FAIL` symbols have no
    history; `BROKEN` attributes raise like a rate-limited Yahoo endpoint."""

    FAIL = {"NOPE"}
    BROKEN = {"insider_purchases"}

    def __init__(self, symbol):
        self.symbol = symbol

    def __getattr__(self, name):
        if name in self.BROKEN:
            raise RuntimeError("Too Many Requests")
        frames = {"income_stmt", "balance_sheet", "cashflow", "quarterly_income_stmt",
                  "quarterly_balance_sheet", "institutional_holders", "eps_trend", "eps_revisions"}
        if name in frames:
            return pd.DataFrame({"2025-09-30": [1.0]}, index=["Total Revenue"])
        raise AttributeError(name)

    def history(self, period=None, interval="1d", auto_adjust=True, **_):
        if self.symbol in self.FAIL:
            return pd.DataFrame()
        if interval == "5m":
            return _bars(78, freq="5min")
        daily = _bars()
        if self.symbol == "TEST":  # Yahoo's unfinalised last bar: volume but no prices
            daily.loc[daily.index[-1], ["Open", "High", "Low", "Close"]] = np.nan
        return daily

    info = property(lambda self: {"shortName": "Test Corp", "sector": "Technology"})
    fast_info = property(lambda self: {"last_price": 130.0, "previous_close": 128.0})
    upgrades_downgrades = property(lambda self: pd.DataFrame())  # Yahoo often has none
    analyst_price_targets = property(lambda self: {"mean": 140.0})
    calendar = property(lambda self: {"Earnings Date": [date(2026, 10, 20)]})
    options = property(lambda self: ("2026-10-16", "2026-10-23"))
    news = property(lambda self: [{"title": "Fallback headline", "link": "https://example.com/a"}])

    def option_chain(self, expiry):
        chain = pd.DataFrame({"strike": [125.0, 130.0], "volume": [10, 20], "openInterest": [100, 200],
                              "impliedVolatility": [0.3, 0.3]})
        return SimpleNamespace(calls=chain, puts=chain)

    def get_earnings_dates(self, limit=12):
        return pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex(["2026-07-30"]))


@pytest.fixture
def fake_yahoo(monkeypatch):
    monkeypatch.setattr(tool.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(tool, "fetch_bls", lambda: {})
    monkeypatch.setattr(tool, "fetch_news", lambda ticker: [
        NewsItem(title="RSS headline", link="https://example.com/rss", published=None, summary=None, source="Yahoo")])


def test_fetch_snapshot_assembles_every_source(fake_yahoo):
    snapshot = tool.fetch_snapshot("test", max_workers=2)
    assert snapshot.ticker == "TEST" and snapshot.last_price == 130.0 and snapshot.previous_close == 128.0
    # The NaN last bar is filled from the quote, not dropped.
    assert snapshot.daily["Close"].iloc[-1] == 130.0 and snapshot.daily["Close"].notna().all()
    assert snapshot.sector_etf == "XLK" and snapshot.sector_daily is not None
    assert len(snapshot.intraday) == 78 and snapshot.market_daily is not None
    assert set(snapshot.options.calls["expiry"]) == {"2026-10-16", "2026-10-23"}
    assert snapshot.earnings_dates == [date(2026, 10, 20)]
    assert snapshot.headlines == ["RSS headline"] and snapshot.news[0].link == "https://example.com/rss"
    assert set(snapshot.yields) == set(tool.YIELD_TICKERS)
    assert snapshot.price_targets == {"mean": 140.0}


def test_failing_sources_degrade_to_errors(fake_yahoo):
    snapshot = tool.fetch_snapshot("TEST", max_workers=2)
    assert snapshot.insider_purchases is None and "RuntimeError" in snapshot.errors["insiders"]
    assert snapshot.rating_changes is None and snapshot.errors["rating_changes"] == "no data returned"
    assert "daily" not in snapshot.errors


def test_no_price_history_is_an_error(fake_yahoo):
    with pytest.raises(ValueError, match="No price history"):
        tool.fetch_snapshot("NOPE")


def test_news_falls_back_to_yfinance_when_rss_fails(monkeypatch):
    monkeypatch.setattr(tool.yf, "Ticker", FakeTicker)

    def broken_rss(ticker):
        raise OSError("feed down")

    monkeypatch.setattr(tool, "fetch_news", broken_rss)
    assert [item.title for item in tool._news("TEST")] == ["Fallback headline"]


def test_fetch_daily_and_options_shapes(monkeypatch):
    monkeypatch.setattr(tool.yf, "Ticker", FakeTicker)
    assert len(tool.fetch_daily("spy")) == 300
    chain = tool._fetch_options(FakeTicker("TEST"), max_expiries=1)
    assert len(chain.calls) == 2 and set(chain.puts["expiry"]) == {"2026-10-16"}
