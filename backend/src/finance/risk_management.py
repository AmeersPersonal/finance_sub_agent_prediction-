"""Risk measures: company credit risk (Altman Z-score) and position risk (ATR).

Altman Z-score
--------------
In corporate finance, banking, and debt underwriting, this predictive
classification equation is used to gauge credit risk and forecast the
probability that a company will go bankrupt within two years.

    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 0.999*X5

- X1: Working Capital / Total Assets (Liquidity)
- X2: Retained Earnings / Total Assets (Cumulative Profitability)
- X3: EBIT / Total Assets (Operating Efficiency)
- X4: Market Value of Equity / Total Liabilities (Leverage)
- X5: Sales / Total Assets (Asset Turnover)
- Interpretation: a score below 1.81 predicts a high probability of bankruptcy
  ("Distress Zone"); 1.81-2.99 is the grey zone; above 2.99 is safe.

The model was built on public manufacturers; it isn't meaningful for banks and
insurers, so it returns None for the Financial Services sector.

Annual statements can be up to a year old, so `altman_z_ttm` runs the same
model on the latest quarterly balance sheet and the trailing four quarters of
EBIT and revenue. Callers prefer it and fall back to the annual version.
"""

from __future__ import annotations

import pandas as pd

from finance.fundamentals import NOT_APPLICABLE_SECTORS, ratio, ttm, value

DISTRESS_BELOW = 1.81
SAFE_ABOVE = 2.99
LIABILITIES = "Total Liabilities Net Minority Interest"


def _z_score(
    balance: pd.DataFrame | None,
    ebit: float | None,
    revenue: float | None,
    market_cap: float | None,
) -> dict | None:
    """Balance items come from the newest column of `balance`; the flows are passed in."""
    assets = value(balance, "Total Assets")
    x = (
        ratio(value(balance, "Working Capital"), assets),
        ratio(value(balance, "Retained Earnings"), assets),
        ratio(ebit, assets),
        ratio(market_cap, value(balance, LIABILITIES)),
        ratio(revenue, assets),
    )
    if any(v is None for v in x):
        return None
    z = 1.2 * x[0] + 1.4 * x[1] + 3.3 * x[2] + 0.6 * x[3] + 0.999 * x[4]
    zone = "distress" if z < DISTRESS_BELOW else "grey" if z <= SAFE_ABOVE else "safe"
    return {"z_score": z, "zone": zone}


def altman_z(
    balance: pd.DataFrame | None,
    income: pd.DataFrame | None,
    market_cap: float | None,
    sector: str | None = None,
) -> dict | None:
    """From the latest annual statements."""
    if sector in NOT_APPLICABLE_SECTORS:
        return None
    result = _z_score(balance, value(income, "EBIT"), value(income, "Total Revenue"), market_cap)
    return None if result is None else {**result, "basis": "annual"}


def altman_z_ttm(
    quarterly_balance: pd.DataFrame | None,
    quarterly_income: pd.DataFrame | None,
    market_cap: float | None,
    sector: str | None = None,
) -> dict | None:
    """From the latest quarterly balance sheet and trailing-four-quarter EBIT and revenue."""
    if sector in NOT_APPLICABLE_SECTORS:
        return None
    result = _z_score(
        quarterly_balance,
        ttm(quarterly_income, "EBIT"),
        ttm(quarterly_income, "Total Revenue"),
        market_cap,
    )
    if result is None:
        return None
    as_of = str(pd.Timestamp(quarterly_balance.columns[0]).date())
    return {**result, "basis": "ttm", "balance_sheet_as_of": as_of}


def atr_stop_distance(atr: float, price: float, multiple: float = 2.0) -> float:
    """How far (as a fraction of price) a stop `multiple` ATRs away sits."""
    if price <= 0:
        raise ValueError("price must be positive")
    return multiple * atr / price


def max_position_fraction(risk_fraction: float, stop_distance: float) -> float:
    """Fixed-fractional sizing: the largest share of an account to put in one
    position so that hitting the stop loses at most `risk_fraction` of the account."""
    if stop_distance <= 0:
        raise ValueError("stop distance must be positive")
    return min(1.0, risk_fraction / stop_distance)
