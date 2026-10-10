"""Who owns the stock and what the Street expects: insiders (Form 4), institutions
(13F), short sellers and analysts. Inputs are yfinance tables; see tool.py."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def _count(raw) -> int | None:
    return None if pd.isna(raw) else int(raw)


def insider_activity(purchases: pd.DataFrame | None) -> dict | None:
    """Last 6 months of insider buying and selling (yfinance `insider_purchases`)."""
    if purchases is None or purchases.empty:
        return None
    rows = purchases.set_index(purchases.columns[0])

    def cell(label: str, column: str) -> float | None:
        if label not in rows.index or pd.isna(rows.loc[label, column]):
            return None
        return float(rows.loc[label, column])

    net_pct = cell("% Net Shares Purchased (Sold)", "Shares")
    buys, sells = cell("Purchases", "Trans"), cell("Sales", "Trans")
    return {
        "buy_transactions": None if buys is None else int(buys),
        "sell_transactions": None if sells is None else int(sells),
        "net_shares": cell("Net Shares Purchased (Sold)", "Shares"),
        "net_pct_of_insider_holdings": None if net_pct is None else net_pct * 100,
    }


def institutional_activity(holders: pd.DataFrame | None, info: dict) -> dict | None:
    """Ownership levels plus how the top holders changed their stakes last quarter."""
    summary: dict = {}
    if info.get("heldPercentInstitutions") is not None:
        summary["institutions_pct_held"] = info["heldPercentInstitutions"] * 100
    if info.get("heldPercentInsiders") is not None:
        summary["insiders_pct_held"] = info["heldPercentInsiders"] * 100
    if holders is not None and not holders.empty and "pctChange" in holders.columns:
        change = holders["pctChange"].dropna()
        summary["top_holders_avg_stake_change_pct"] = float(change.mean()) * 100
        summary["top_holders_increasing"] = int((change > 0).sum())
        summary["top_holders_decreasing"] = int((change < 0).sum())
        summary["as_of"] = str(pd.Timestamp(holders["Date Reported"].max()).date())
    return summary or None


def short_interest(info: dict) -> dict | None:
    shares, prior = info.get("sharesShort"), info.get("sharesShortPriorMonth")
    summary = {
        "short_pct_of_float": None
        if info.get("shortPercentOfFloat") is None
        else info["shortPercentOfFloat"] * 100,
        "days_to_cover": info.get("shortRatio"),
        "change_vs_prior_month_pct": (shares / prior - 1) * 100 if shares and prior else None,
    }
    return summary if any(v is not None for v in summary.values()) else None


def analyst_estimates(
    eps_trend: pd.DataFrame | None,
    eps_revisions: pd.DataFrame | None,
    price_targets: dict | None,
    price: float,
) -> dict | None:
    """EPS estimate drift, revision counts and price targets vs the current price."""
    summary: dict = {}
    if eps_trend is not None and "0y" in eps_trend.index:
        current_year = eps_trend.loc["0y"]
        if current_year.get("30daysAgo"):
            summary["eps_this_year_change_30d_pct"] = (
                float(current_year["current"] / current_year["30daysAgo"] - 1) * 100
            )
        if "+1y" in eps_trend.index and eps_trend.loc["+1y"].get("90daysAgo"):
            next_year = eps_trend.loc["+1y"]
            summary["eps_next_year_change_90d_pct"] = (
                float(next_year["current"] / next_year["90daysAgo"] - 1) * 100
            )
    if eps_revisions is not None and "0y" in eps_revisions.index:
        summary["eps_revisions_up_30d"] = _count(eps_revisions.loc["0y", "upLast30days"])
        summary["eps_revisions_down_30d"] = _count(eps_revisions.loc["0y", "downLast30days"])
    if price_targets and price_targets.get("mean"):
        summary["price_target_mean"] = float(price_targets["mean"])
        summary["price_target_upside_pct"] = (float(price_targets["mean"]) / price - 1) * 100
        summary["price_target_low"] = price_targets.get("low")
        summary["price_target_high"] = price_targets.get("high")
    return summary or None


def rating_changes(changes: pd.DataFrame | None, as_of: date, days: int = 30) -> dict | None:
    """Analyst upgrades, downgrades and target moves in the last `days` (catalysts)."""
    if changes is None or changes.empty:
        return None
    graded = pd.to_datetime(changes.index)
    if graded.tz is not None:
        graded = graded.tz_localize(None)
    recent = changes[graded >= pd.Timestamp(as_of - timedelta(days=days))]
    return {
        "days": days,
        "upgrades": int((recent["Action"] == "up").sum()),
        "downgrades": int((recent["Action"] == "down").sum()),
        "target_raises": int((recent["priceTargetAction"] == "Raises").sum()),
        "target_cuts": int((recent["priceTargetAction"] == "Lowers").sum()),
    }
