"""Macro backdrop: Treasury yields and inflation / labour-market data.

Yields come from yfinance (^IRX 13-week, ^FVX 5-year, ^TNX 10-year, all in
percent). The 2-year isn't on Yahoo, so the curve uses the 10y-3m spread, the
New York Fed's preferred recession indicator. Inflation and jobs come from the
BLS as monthly series indexed by month start.
"""

from __future__ import annotations

import pandas as pd

YIELD_TICKERS = {"3m": "^IRX", "5y": "^FVX", "10y": "^TNX"}


def yield_summary(yields: dict[str, pd.Series]) -> dict | None:
    if not yields:
        return None
    summary: dict = {f"yield_{k}_pct": float(s.iloc[-1]) for k, s in yields.items() if len(s)}
    ten, three = yields.get("10y"), yields.get("3m")
    if ten is not None and three is not None and len(ten) and len(three):
        spread = float(ten.iloc[-1] - three.iloc[-1])
        summary["spread_10y_3m_pct_points"] = spread
        summary["curve_inverted"] = spread < 0
    if ten is not None and len(ten) > 21:
        summary["yield_10y_change_1m_pct_points"] = float(ten.iloc[-1] - ten.iloc[-22])
    return summary


def labor_inflation_summary(bls: dict[str, pd.Series]) -> dict | None:
    """CPI year-over-year, unemployment and payroll trend from monthly BLS series."""
    summary: dict = {}
    cpi = bls.get("cpi")
    if cpi is not None and len(cpi):
        latest = cpi.index[-1]
        year_ago = latest - pd.DateOffset(years=1)
        if year_ago in cpi.index:
            summary["cpi_yoy_pct"] = float(cpi.iloc[-1] / cpi[year_ago] - 1) * 100
            summary["cpi_as_of"] = latest.strftime("%Y-%m")
    unemployment = bls.get("unemployment_rate")
    if unemployment is not None and len(unemployment):
        summary["unemployment_rate_pct"] = float(unemployment.iloc[-1])
        summary["unemployment_as_of"] = unemployment.index[-1].strftime("%Y-%m")
        if len(unemployment) > 3:
            summary["unemployment_change_3m_pct_points"] = float(
                unemployment.iloc[-1] - unemployment.iloc[-4]
            )
    payrolls = bls.get("payrolls_thousands")
    if payrolls is not None and len(payrolls) > 3:
        summary["payrolls_avg_monthly_change_3m_thousands"] = float(payrolls.diff().iloc[-3:].mean())
    return summary or None
