from datetime import date, datetime

from ai.tool import _earnings_dates, _headlines


def test_earnings_dates_handles_yfinance_shapes():
    assert _earnings_dates({"Earnings Date": [date(2026, 11, 2)]}) == [date(2026, 11, 2)]
    window = {"Earnings Date": [datetime(2026, 11, 5, 16), date(2026, 11, 2)]}
    assert _earnings_dates(window) == [date(2026, 11, 2), date(2026, 11, 5)]
    assert _earnings_dates({"Earnings Date": date(2026, 11, 2)}) == [date(2026, 11, 2)]
    assert _earnings_dates({}) == [] and _earnings_dates(None) == []


def test_headlines_handles_both_news_layouts():
    news = [{"title": "Flat"}, {"content": {"title": "Nested"}}, {"content": {}}]
    assert _headlines(news) == ["Flat", "Nested"]
    assert _headlines(None) == []
