"""Synthetic market data so tests never hit the network or need an API key."""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from ai.feeds import NewsItem
from ai.schemas import PersonaView
from ai.sentiment import HeadlineScore, HeadlineSentiment
from ai.tool import MarketSnapshot, OptionsChain
from audit.media import ItemSummary, NewsDigest

NY = "America/New_York"


@pytest.fixture(autouse=True)
def _postgres_retrieval_only(monkeypatch):
    """Tests opt into Snowflake retrieval explicitly, whatever the developer's shell sets."""
    monkeypatch.delenv("RAG_BACKEND", raising=False)


def _daily(seed: int, start_price: float, days: int = 1260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end="2026-10-09", periods=days, tz=NY)
    close = start_price * np.exp(np.cumsum(rng.normal(0.0004, 0.015, days)))
    return pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, days).astype(float),
        },
        index=index,
    )


def _intraday(last_close: float) -> pd.DataFrame:
    frames = []
    for day in ("2026-10-08", "2026-10-09"):
        index = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)
        close = last_close * (1 + np.linspace(-0.01, 0.01, 78))
        frames.append(
            pd.DataFrame(
                {"Open": close, "High": close * 1.001, "Low": close * 0.999, "Close": close,
                 "Volume": np.full(78, 20_000.0)},
                index=index,
            )
        )
    return pd.concat(frames)


def _chain(spot: float, expiry: str, volume: float) -> pd.DataFrame:
    strikes = np.arange(round(spot) - 10, round(spot) + 11, 5.0)
    return pd.DataFrame(
        {"strike": strikes, "volume": volume, "openInterest": volume * 10,
         "impliedVolatility": 0.30, "expiry": expiry}
    )


@pytest.fixture
def snapshot() -> MarketSnapshot:
    daily = _daily(seed=0, start_price=100)
    spot = float(daily["Close"].iloc[-1])
    expiries = ("2026-10-12", "2026-10-23")
    return MarketSnapshot(
        ticker="TEST",
        fetched_at=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc),
        daily=daily,
        last_price=spot,
        previous_close=float(daily["Close"].iloc[-2]),
        intraday=_intraday(spot),
        market_daily=_daily(seed=1, start_price=400),
        nasdaq_daily=_daily(seed=3, start_price=500),
        sector_etf="XLK",
        sector_daily=_daily(seed=4, start_price=200),
        vix_daily=_daily(seed=2, start_price=18),
        info={"shortName": "Test Corp", "sector": "Technology", "trailingPE": 30.0,
              "dividendYield": 0.5, "shortPercentOfFloat": 0.02, "marketCap": 500e9,
              "sharesShort": 110e6, "sharesShortPriorMonth": 100e6, "shortRatio": 2.5,
              "heldPercentInstitutions": 0.6, "heldPercentInsiders": 0.02,
              "enterpriseToEbitda": 20.0, "trailingPegRatio": 2.0,
              "marketState": "REGULAR", "bid": spot - 0.05, "ask": spot + 0.05},
        income_stmt=_frame(INCOME, ANNUAL),
        balance_sheet=_frame(BALANCE, ANNUAL[:2]),
        cashflow=_frame(CASHFLOW, ANNUAL[:2]),
        quarterly_income=_frame(QUARTERLY, QUARTERS),
        quarterly_balance=_frame(QUARTERLY_BALANCE, QUARTERS[:2]),
        earnings_history=EARNINGS_HISTORY.copy(),
        insider_purchases=INSIDERS.copy(),
        institutional_holders=INSTITUTIONS.copy(),
        eps_trend=EPS_TREND.copy(),
        eps_revisions=EPS_REVISIONS.copy(),
        price_targets={"current": spot, "mean": spot * 1.1, "low": spot * 0.8, "high": spot * 1.3},
        rating_changes=RATING_CHANGES.copy(),
        options=OptionsChain(
            calls=pd.concat([_chain(spot, e, 100) for e in expiries], ignore_index=True),
            puts=pd.concat([_chain(spot, e, 50) for e in expiries], ignore_index=True),
        ),
        headlines=["Test Corp beats estimates"],
        news=[
            NewsItem(
                title="Test Corp beats estimates",
                link="https://finance.yahoo.com/news/test-corp-beats",
                published="Thu, 08 Oct 2026 20:00:00 +0000",
                summary="Revenue topped forecasts.",
                source="Yahoo Finance",
            )
        ],
        earnings_dates=[date(2026, 10, 14)],  # inside a 5-day horizon from 2026-10-09
        yields={
            "3m": pd.Series(np.full(63, 4.0)),
            "10y": pd.Series(np.linspace(4.5, 5.0, 63)),
        },
        labor=LABOR,
        errors={},
    )


# --- Synthetic statements and Street data (yfinance layouts) -------------------

ANNUAL = pd.to_datetime(["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30"])
QUARTERS = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])

INCOME = {  # newest year first; only Total Revenue goes back four years
    "Total Revenue": [130e9, 120e9, 110e9, 100e9],
    "Cost Of Revenue": [70e9, 66e9],
    "Gross Profit": [60e9, 54e9],
    "Operating Income": [39e9, 34e9],
    "EBIT": [40e9, 35e9],
    "Net Income": [30e9, 26e9],
    "Net Income From Continuing Operation Net Minority Interest": [30e9, 26e9],
    "Tax Rate For Calcs": [0.2, 0.2],
    "Interest Expense": [2e9, 2e9],
    "Selling General And Administration": [21e9, 20e9],
    "Reconciled Depreciation": [5e9, 4.8e9],
}
BALANCE = {
    "Total Assets": [200e9, 190e9],
    "Current Assets": [80e9, 75e9],
    "Current Liabilities": [50e9, 48e9],
    "Working Capital": [30e9, 27e9],
    "Retained Earnings": [60e9, 50e9],
    "Total Liabilities Net Minority Interest": [120e9, 115e9],
    "Total Debt": [40e9, 42e9],
    "Stockholders Equity": [80e9, 75e9],
    "Invested Capital": [120e9, 117e9],
    "Accounts Receivable": [20e9, 18e9],
    "Net PPE": [50e9, 48e9],
    "Long Term Debt": [35e9, 37e9],
}
CASHFLOW = {"Free Cash Flow": [28e9, 25e9], "Operating Cash Flow": [35e9, 31e9]}
QUARTERLY = {
    "Total Revenue": [110e9, 105e9, 100e9, 102e9, 100e9],
    "Gross Profit": [50e9, 47e9, 45e9, 46e9, 44e9],
    "Operating Income": [30e9, 28e9, 27e9, 27e9, 26e9],
    "EBIT": [11e9, 10.5e9, 10e9, 10.2e9, 10e9],
    "Diluted EPS": [1.5, 1.4, 1.3, 1.35, 1.3],
}
QUARTERLY_BALANCE = {
    "Total Assets": [210e9, 205e9],
    "Working Capital": [32e9, 31e9],
    "Retained Earnings": [65e9, 62e9],
    "Total Liabilities Net Minority Interest": [125e9, 122e9],
}


def _frame(rows: dict[str, list[float]], columns) -> pd.DataFrame:
    padded = {k: v + [np.nan] * (len(columns) - len(v)) for k, v in rows.items()}
    return pd.DataFrame.from_dict(padded, orient="index", columns=columns)


EARNINGS_HISTORY = pd.DataFrame(
    {
        "EPS Estimate": [1.6, 1.43, 1.42, 1.28, 1.34, 1.25],
        "Reported EPS": [np.nan, 1.50, 1.39, 1.32, 1.35, 1.30],
        "Surprise(%)": [np.nan, 5.0, -2.0, 3.0, 1.0, 4.0],
    },
    index=pd.DatetimeIndex(
        ["2026-10-14 16:00", "2026-07-30 16:00", "2026-04-30 16:00",
         "2026-01-29 16:00", "2025-10-30 16:00", "2025-07-31 16:00"],
        tz=NY, name="Earnings Date",
    ),
)
INSIDERS = pd.DataFrame(
    {
        "Insider Purchases Last 6m": ["Purchases", "Sales", "Net Shares Purchased (Sold)",
                                      "Total Insider Shares Held", "% Net Shares Purchased (Sold)"],
        "Shares": [800_000.0, 500_000.0, 300_000.0, 200e6, 0.0015],
        "Trans": [12, 17, 29, np.nan, np.nan],
    }
)
INSTITUTIONS = pd.DataFrame(
    {
        "Date Reported": pd.to_datetime(["2026-06-30"] * 3),
        "Holder": ["A", "B", "C"],
        "pctHeld": [0.08, 0.06, 0.04],
        "Shares": [1e9, 8e8, 5e8],
        "Value": [1e11, 8e10, 5e10],
        "pctChange": [0.02, -0.01, 0.005],
    }
)
EPS_TREND = pd.DataFrame(
    {"current": [1.6, 1.7, 6.0, 6.6], "7daysAgo": [1.6, 1.7, 6.0, 6.6],
     "30daysAgo": [1.58, 1.69, 5.88, 6.5], "60daysAgo": [1.55, 1.68, 5.8, 6.4],
     "90daysAgo": [1.5, 1.66, 5.7, 6.0]},
    index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"),
)
EPS_REVISIONS = pd.DataFrame(
    {"upLast7days": [1, 0, 1, 0], "upLast30days": [5, 1, 6, 4],
     "downLast30days": [2, 1, 1, 0], "downLast7Days": [0, 0, 0, 0]},
    index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"),
)
RATING_CHANGES = pd.DataFrame(
    {"Firm": ["X", "Y", "Z", "W"], "ToGrade": ["Buy", "Hold", "Buy", "Sell"],
     "FromGrade": ["Hold", "Buy", "Buy", "Hold"], "Action": ["up", "down", "main", "down"],
     "priceTargetAction": ["Raises", "Lowers", "Raises", "Lowers"],
     "currentPriceTarget": [120.0, 90.0, 130.0, 80.0], "priorPriceTarget": [110.0, 100.0, 125.0, 90.0]},
    index=pd.DatetimeIndex(["2026-10-01", "2026-09-25", "2026-09-20", "2026-07-01"], name="GradeDate"),
)
_MONTHS = pd.date_range("2025-06-01", "2026-09-01", freq="MS")
LABOR = {
    "cpi": pd.Series(np.linspace(100.0, 104.0, len(_MONTHS)), index=_MONTHS),
    "unemployment_rate": pd.Series(np.linspace(4.0, 4.3, len(_MONTHS)), index=_MONTHS),
    "payrolls_thousands": pd.Series(158_000 + 100.0 * np.arange(len(_MONTHS)), index=_MONTHS),
}


class FakeLLM:
    """Answers `up` for every persona except day traders, who answer `down`,
    scores every headline +0.5, and summarises news item 1."""

    model = "fake-model"

    def __init__(self, fail_for: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []  # persona calls only
        self.call_options: list[tuple[str | None, float | None]] = []  # (model, temperature)
        self.down_above: float | None = None  # temperatures above this answer down
        self.sentiment_calls = 0
        self.digest_prompts: list[str] = []
        self.fail_for = fail_for

    async def generate_json(self, system, prompt, schema, *, temperature=None, model=None):
        if schema is HeadlineSentiment:
            self.sentiment_calls += 1
            return HeadlineSentiment(
                scores=[HeadlineScore(headline="h", score=0.5)], overall=0.4, summary="Beat."
            )
        if schema is NewsDigest:
            self.digest_prompts.append(prompt)
            return NewsDigest(
                # item 99 doesn't exist and must be dropped, not turned into a link
                items=[ItemSummary(item=1, tldr="Beat on revenue.", relevance="high"),
                       ItemSummary(item=99, tldr="Invented.", relevance="low")],
                summary="Results beat.",
            )
        self.calls.append((system, prompt))
        self.call_options.append((model, temperature))
        if self.fail_for and self.fail_for in system:
            raise RuntimeError("simulated API failure")
        direction = "down" if "day trader" in system else "up"
        if self.down_above is not None and (temperature or 0) > self.down_above:
            direction = "down"
        return PersonaView(direction=direction, conviction=0.6, rationale="test", key_factors=[])


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def failing_llm() -> FakeLLM:
    """Fails every 55-65 persona."""
    return FakeLLM(fail_for="55-65-year-old")
