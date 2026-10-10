"""Revenue trend and a naive one-year projection from annual income statements."""

from __future__ import annotations

import pandas as pd


def revenue_forecast(income_stmt: pd.DataFrame | None) -> dict | None:
    """Summarise annual revenue (yfinance `income_stmt` layout: rows are line items,
    columns are fiscal year ends). Returns None when revenue isn't available."""
    if income_stmt is None or "Total Revenue" not in income_stmt.index:
        return None
    revenue = income_stmt.loc["Total Revenue"].dropna().sort_index()
    if len(revenue) < 2 or revenue.iloc[0] <= 0:
        return None

    years = len(revenue) - 1
    growth_rate = (revenue.iloc[-1] / revenue.iloc[0]) ** (1 / years) - 1
    return {
        "latest_fiscal_year_end": str(pd.Timestamp(revenue.index[-1]).date()),
        "latest_revenue": float(revenue.iloc[-1]),
        "yoy_growth_pct": [round(float(g) * 100, 2) for g in revenue.pct_change().dropna()],
        "revenue_cagr_pct": round(float(growth_rate) * 100, 2),
        "next_year_projection": round(float(revenue.iloc[-1] * (1 + growth_rate))),
        "method": f"{years}-year revenue CAGR extrapolated one year",
    }
