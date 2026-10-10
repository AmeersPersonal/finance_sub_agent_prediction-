"""Market data tools: everything the agents see is fetched here.

Sources: yfinance (prices, options, statements, ownership, analysts, yields),
Yahoo Finance RSS (headlines) and the BLS (inflation, jobs); see feeds.py.

yfinance is free but unofficial. Quotes are near-real-time at best and Yahoo
rate-limits hard, so every source except the daily history degrades to None
(recorded in `errors`) instead of failing the whole prediction. Sources are
fetched in parallel, each through its own yf.Ticker so threads share no state.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from ai.feeds import fetch_bls, fetch_headlines
from finance.macro import YIELD_TICKERS

SP500_PROXY = "SPY"
NASDAQ_PROXY = "QQQ"
VIX = "^VIX"
SECTOR_ETFS = {  # yfinance sector name -> SPDR sector ETF
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@dataclass
class OptionsChain:
    calls: pd.DataFrame  # one row per contract, with an `expiry` column
    puts: pd.DataFrame


@dataclass
class MarketSnapshot:
    ticker: str
    fetched_at: datetime
    daily: pd.DataFrame  # ~5y of daily OHLCV, split/dividend adjusted
    last_price: float
    previous_close: float | None = None
    intraday: pd.DataFrame | None = None  # last 5 sessions of 5-minute bars
    market_daily: pd.DataFrame | None = None  # S&P 500 (SPY), same span as `daily`
    nasdaq_daily: pd.DataFrame | None = None  # QQQ
    sector_etf: str | None = None
    sector_daily: pd.DataFrame | None = None
    vix_daily: pd.DataFrame | None = None
    info: dict[str, Any] = field(default_factory=dict)
    income_stmt: pd.DataFrame | None = None  # annual statements, newest column first
    balance_sheet: pd.DataFrame | None = None
    cashflow: pd.DataFrame | None = None
    quarterly_income: pd.DataFrame | None = None
    earnings_history: pd.DataFrame | None = None  # EPS estimate / reported / surprise
    insider_purchases: pd.DataFrame | None = None  # Form 4 summary, last 6 months
    institutional_holders: pd.DataFrame | None = None  # 13F top holders
    eps_trend: pd.DataFrame | None = None
    eps_revisions: pd.DataFrame | None = None
    price_targets: dict[str, Any] = field(default_factory=dict)
    rating_changes: pd.DataFrame | None = None
    options: OptionsChain | None = None
    headlines: list[str] = field(default_factory=list)
    earnings_dates: list[date] = field(default_factory=list)
    yields: dict[str, pd.Series] = field(default_factory=dict)  # "3m"/"5y"/"10y" -> percent
    labor: dict[str, pd.Series] = field(default_factory=dict)  # BLS monthly series
    errors: dict[str, str] = field(default_factory=dict)  # source -> why it's missing


def fetch_snapshot(
    ticker: str, years: int = 5, max_expiries: int = 6, max_workers: int = 6
) -> MarketSnapshot:
    ticker = ticker.upper()
    period = f"{years}y"
    errors: dict[str, str] = {}

    def attempt(source: str, fetch: Callable[[], Any]) -> Any:
        try:
            value = fetch()
        except Exception as exc:
            errors[source] = f"{type(exc).__name__}: {exc}"
            return None
        if isinstance(value, pd.DataFrame) and value.empty:
            errors[source] = "no data returned"
            return None
        return value

    stock = yf.Ticker(ticker)
    daily = attempt("daily", lambda: stock.history(period=period, interval="1d", auto_adjust=True))
    if daily is None:
        raise ValueError(f"No price history for {ticker!r} ({errors['daily']})")
    info = attempt("info", lambda: stock.info) or {}
    sector_etf = SECTOR_ETFS.get(info.get("sector"))

    def history(symbol: str) -> Callable[[], pd.DataFrame]:
        return lambda: yf.Ticker(symbol).history(period=period, auto_adjust=True)

    def own(attribute: str) -> Callable[[], Any]:
        return lambda: getattr(yf.Ticker(ticker), attribute)

    tasks: dict[str, Callable[[], Any]] = {
        # fast_info is lazy: the request happens on field access, so read it in the task.
        "quote": lambda: {
            k: yf.Ticker(ticker).fast_info[k] for k in ("last_price", "previous_close")
        },
        "intraday": lambda: yf.Ticker(ticker).history(period="5d", interval="5m"),
        "sp500": history(SP500_PROXY),
        "nasdaq": history(NASDAQ_PROXY),
        "vix": history(VIX),
        "income_stmt": own("income_stmt"),
        "balance_sheet": own("balance_sheet"),
        "cashflow": own("cashflow"),
        "quarterly_income": own("quarterly_income_stmt"),
        "earnings_history": lambda: yf.Ticker(ticker).get_earnings_dates(limit=12),
        "insiders": own("insider_purchases"),
        "institutions": own("institutional_holders"),
        "eps_trend": own("eps_trend"),
        "eps_revisions": own("eps_revisions"),
        "price_targets": own("analyst_price_targets"),
        "rating_changes": own("upgrades_downgrades"),
        "options": lambda: _fetch_options(yf.Ticker(ticker), max_expiries),
        "news": lambda: _news(ticker),
        "calendar": lambda: _earnings_dates(yf.Ticker(ticker).calendar),
        "yields": _yields,
        "labor": fetch_bls,
    }
    if sector_etf:
        tasks["sector"] = history(sector_etf)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {name: pool.submit(attempt, name, fetch) for name, fetch in tasks.items()}
        got = {name: future.result() for name, future in futures.items()}

    quote = got["quote"] or {}
    return MarketSnapshot(
        ticker=ticker,
        fetched_at=datetime.now(timezone.utc),
        daily=daily,
        last_price=_price(quote.get("last_price")) or float(daily["Close"].iloc[-1]),
        previous_close=_price(quote.get("previous_close")),
        intraday=got["intraday"],
        market_daily=got["sp500"],
        nasdaq_daily=got["nasdaq"],
        sector_etf=sector_etf,
        sector_daily=got.get("sector"),
        vix_daily=got["vix"],
        info=info,
        income_stmt=got["income_stmt"],
        balance_sheet=got["balance_sheet"],
        cashflow=got["cashflow"],
        quarterly_income=got["quarterly_income"],
        earnings_history=got["earnings_history"],
        insider_purchases=got["insiders"],
        institutional_holders=got["institutions"],
        eps_trend=got["eps_trend"],
        eps_revisions=got["eps_revisions"],
        price_targets=got["price_targets"] or {},
        rating_changes=got["rating_changes"],
        options=got["options"],
        headlines=got["news"] or [],
        earnings_dates=got["calendar"] or [],
        yields=got["yields"] or {},
        labor=got["labor"] or {},
        errors=errors,
    )


def _price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _fetch_options(stock: yf.Ticker, max_expiries: int) -> OptionsChain | None:
    expiries = list(stock.options)[:max_expiries]
    if not expiries:
        return None
    calls, puts = [], []
    for expiry in expiries:
        chain = stock.option_chain(expiry)
        calls.append(chain.calls.assign(expiry=expiry))
        puts.append(chain.puts.assign(expiry=expiry))
    return OptionsChain(pd.concat(calls, ignore_index=True), pd.concat(puts, ignore_index=True))


def _yields() -> dict[str, pd.Series]:
    yields = {}
    for tenor, symbol in YIELD_TICKERS.items():
        close = yf.Ticker(symbol).history(period="3mo")["Close"].dropna()
        if len(close):
            yields[tenor] = close
    if not yields:
        raise ValueError("no Treasury yields returned")
    return yields


def _news(ticker: str) -> list[str]:
    """Yahoo Finance RSS first; yfinance's news endpoint (often empty) as a fallback."""
    try:
        headlines = fetch_headlines(ticker)
    except Exception:
        headlines = []
    return headlines or _headlines(yf.Ticker(ticker).news)


def _earnings_dates(calendar: Any) -> list[date]:
    """yfinance's calendar holds one date, or a two-date window when the day isn't confirmed."""
    raw = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
    if raw is None:
        return []
    raw = raw if isinstance(raw, (list, tuple)) else [raw]
    return sorted(d.date() if isinstance(d, datetime) else d for d in raw if isinstance(d, date))


def _headlines(news: list[dict] | None, limit: int = 8) -> list[str]:
    # yfinance has shipped two news layouts: a flat `title`, and `content.title`.
    titles = [item.get("title") or (item.get("content") or {}).get("title") for item in news or []]
    return [t for t in titles if t][:limit]
