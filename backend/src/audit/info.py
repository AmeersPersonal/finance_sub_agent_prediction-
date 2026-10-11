"""Company info and validation: who the company is, and whether the data behind a
prediction can be trusted. Deterministic; no LLM.
"""

from __future__ import annotations

from typing import Any

from ai.tool import MarketSnapshot
from finance.indicators import TRADING_DAYS

SUMMARY_CHARS = 400
STALE_AFTER_DAYS = 4  # a long weekend is fine, a week-old bar is not
QUOTE_GAP = 0.10  # last price vs last daily close; more suggests a bad quote or a split


def company_overview(snapshot: MarketSnapshot) -> dict[str, Any]:
    info = snapshot.info
    summary = (info.get("longBusinessSummary") or "").strip()
    if len(summary) > SUMMARY_CHARS:
        summary = summary[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "..."
    return {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "quote_type": info.get("quoteType"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
        "summary": summary or None,
    }


def validate(snapshot: MarketSnapshot) -> list[dict[str, Any]]:
    """One entry per check: `ok` is True, False, or None when it couldn't be checked."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    info = snapshot.info
    quote_type = info.get("quoteType")
    check(
        "is_equity",
        None if quote_type is None else quote_type == "EQUITY",
        f"quote type {quote_type}" if quote_type else "quote type unknown (info unavailable)",
    )
    if quote_type not in (None, "EQUITY"):
        checks[-1]["detail"] += "; funds and indices have no statements, so long-term personas see no fundamentals"

    currency = info.get("currency")
    check(
        "us_dollar_listing",
        None if currency is None else currency == "USD",
        f"prices in {currency}" if currency else "currency unknown",
    )

    last_bar = snapshot.daily.index[-1].date()
    age = (snapshot.fetched_at.date() - last_bar).days
    check("fresh_prices", age <= STALE_AFTER_DAYS, f"last daily bar {last_bar}, {age} days old")

    last_close = float(snapshot.daily["Close"].iloc[-1])
    gap = snapshot.last_price / last_close - 1
    check(
        "quote_matches_history",
        abs(gap) <= QUOTE_GAP,
        f"last price {snapshot.last_price:.2f} ({snapshot.quote_source}) vs last close "
        f"{last_close:.2f}: {gap:+.1%}",
    )

    days = len(snapshot.daily)
    check(
        "enough_history",
        days >= TRADING_DAYS,
        f"{days} daily bars; the flat band and regression need at least {TRADING_DAYS}",
    )

    missing = sorted(snapshot.errors)
    check(
        "sources_complete",
        not missing,
        "all sources returned data" if not missing else "unavailable: " + ", ".join(missing),
    )
    return checks
