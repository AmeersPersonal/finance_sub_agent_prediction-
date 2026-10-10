"""Financial health, valuation and earnings-quality metrics from annual statements.

Statements use yfinance's layout: rows are line items, columns are fiscal year
ends, newest first. Any metric whose inputs are missing comes back as None.
"""

from __future__ import annotations

import pandas as pd

# Beneish (1999): M above this suggests a likely earnings manipulator.
BENEISH_THRESHOLD = -1.78
# Ratio-based scores built for industrial companies don't apply to banks and insurers.
NOT_APPLICABLE_SECTORS = {"Financial Services"}


def value(frame: pd.DataFrame | None, item: str, year: int = 0) -> float | None:
    """One line item, `year` fiscal years back (0 = latest)."""
    if frame is None or item not in frame.index or year >= frame.shape[1]:
        return None
    raw = frame.loc[item].iloc[year]
    return float(raw) if pd.notna(raw) else None


def ttm(frame: pd.DataFrame | None, item: str, quarters: int = 4) -> float | None:
    """Trailing-twelve-month total of a quarterly flow item (revenue, EBIT): the sum
    of the latest `quarters` quarters, or None if any of them is missing."""
    values = [value(frame, item, q) for q in range(quarters)]
    return None if any(v is None for v in values) else sum(values)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _pct(fraction: float | None) -> float | None:
    return None if fraction is None else fraction * 100


def financial_health(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    info: dict,
) -> dict:
    """Profitability, cash flow, leverage and valuation for the latest fiscal year."""
    revenue, revenue_prior = value(income, "Total Revenue"), value(income, "Total Revenue", 1)
    ebit, net_income = value(income, "EBIT"), value(income, "Net Income")
    tax_rate = value(income, "Tax Rate For Calcs")
    interest = value(income, "Interest Expense")
    fcf, ocf = value(cashflow, "Free Cash Flow"), value(cashflow, "Operating Cash Flow")
    market_cap = info.get("marketCap")

    nopat = ebit * (1 - tax_rate) if ebit is not None and tax_rate is not None else None
    return {
        "fiscal_year_end": str(income.columns[0].date()) if income is not None else None,
        "gross_margin_pct": _pct(ratio(value(income, "Gross Profit"), revenue)),
        "gross_margin_prior_year_pct": _pct(ratio(value(income, "Gross Profit", 1), revenue_prior)),
        "operating_margin_pct": _pct(ratio(value(income, "Operating Income"), revenue)),
        "operating_margin_prior_year_pct": _pct(
            ratio(value(income, "Operating Income", 1), revenue_prior)
        ),
        "net_margin_pct": _pct(ratio(net_income, revenue)),
        "fcf_yield_pct": _pct(ratio(fcf, market_cap)),
        "price_to_fcf": ratio(market_cap, fcf) if fcf and fcf > 0 else None,
        "ocf_to_net_income": ratio(ocf, net_income),
        "roic_pct": _pct(ratio(nopat, value(balance, "Invested Capital"))),
        "debt_to_equity": ratio(value(balance, "Total Debt"), value(balance, "Stockholders Equity")),
        "interest_coverage": ratio(ebit, abs(interest)) if interest else None,
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "peg_ratio": info.get("trailingPegRatio") or info.get("pegRatio"),
    }


def beneish_m_score(
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    sector: str | None = None,
) -> dict | None:
    """Beneish M-score (8-variable model) comparing the last two fiscal years.

    Flags patterns typical of earnings manipulation: receivables outgrowing
    sales, slipping margins, asset quality decline, accruals. A screen, not
    proof. None when the sector doesn't fit or any input is missing.
    """
    if sector in NOT_APPLICABLE_SECTORS:
        return None

    def both(frame, item):
        return value(frame, item, 0), value(frame, item, 1)

    sales, sales1 = both(income, "Total Revenue")
    cogs, cogs1 = both(income, "Cost Of Revenue")
    sga, sga1 = both(income, "Selling General And Administration")
    dep, dep1 = both(income, "Reconciled Depreciation")
    receivables, receivables1 = both(balance, "Accounts Receivable")
    current_assets, current_assets1 = both(balance, "Current Assets")
    ppe, ppe1 = both(balance, "Net PPE")
    assets, assets1 = both(balance, "Total Assets")
    current_liab, current_liab1 = both(balance, "Current Liabilities")
    lt_debt, lt_debt1 = both(balance, "Long Term Debt")
    net_income = value(income, "Net Income From Continuing Operation Net Minority Interest")
    if net_income is None:
        net_income = value(income, "Net Income")
    cfo = value(cashflow, "Operating Cash Flow")

    inputs = (sales, sales1, cogs, cogs1, sga, sga1, dep, dep1, receivables, receivables1,
              current_assets, current_assets1, ppe, ppe1, assets, assets1, current_liab,
              current_liab1, lt_debt, lt_debt1, net_income, cfo)
    if any(v is None for v in inputs) or 0 in (sales, sales1, assets, assets1):
        return None

    try:
        dsri = (receivables / sales) / (receivables1 / sales1)
        gmi = ((sales1 - cogs1) / sales1) / ((sales - cogs) / sales)
        aqi = (1 - (current_assets + ppe) / assets) / (1 - (current_assets1 + ppe1) / assets1)
        sgi = sales / sales1
        depi = (dep1 / (ppe1 + dep1)) / (dep / (ppe + dep))
        sgai = (sga / sales) / (sga1 / sales1)
        lvgi = ((current_liab + lt_debt) / assets) / ((current_liab1 + lt_debt1) / assets1)
        tata = (net_income - cfo) / assets
    except ZeroDivisionError:
        return None

    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    return {
        "m_score": m,
        "threshold": BENEISH_THRESHOLD,
        "above_threshold_possible_manipulation": m > BENEISH_THRESHOLD,
    }
