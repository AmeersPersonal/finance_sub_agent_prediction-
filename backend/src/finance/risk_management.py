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
"""

from __future__ import annotations

import pandas as pd

from finance.fundamentals import NOT_APPLICABLE_SECTORS, ratio, value

DISTRESS_BELOW = 1.81
SAFE_ABOVE = 2.99


def altman_z(
    balance: pd.DataFrame | None,
    income: pd.DataFrame | None,
    market_cap: float | None,
    sector: str | None = None,
) -> dict | None:
    if sector in NOT_APPLICABLE_SECTORS:
        return None
    assets = value(balance, "Total Assets")
    x = (
        ratio(value(balance, "Working Capital"), assets),
        ratio(value(balance, "Retained Earnings"), assets),
        ratio(value(income, "EBIT"), assets),
        ratio(market_cap, value(balance, "Total Liabilities Net Minority Interest")),
        ratio(value(income, "Total Revenue"), assets),
    )
    if any(v is None for v in x):
        return None
    z = 1.2 * x[0] + 1.4 * x[1] + 3.3 * x[2] + 0.6 * x[3] + 0.999 * x[4]
    zone = "distress" if z < DISTRESS_BELOW else "grey" if z <= SAFE_ABOVE else "safe"
    return {"z_score": z, "zone": zone}


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
