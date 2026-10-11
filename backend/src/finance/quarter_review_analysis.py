"""Quarterly (10-Q) review: recent growth, margin trend and earnings surprises.

`quarterly_income` uses yfinance's layout (rows are line items, columns are
quarter ends, newest first); `earnings_history` is yfinance's earnings-dates
table (EPS Estimate, Reported EPS, Surprise(%)), which includes the upcoming
report with no reported EPS yet.
"""

from __future__ import annotations

import pandas as pd

from finance.fundamentals import ratio, value


def quarterly_review(
    quarterly_income: pd.DataFrame | None,
    earnings_history: pd.DataFrame | None,
    quarters: int = 4,
) -> dict | None:
    review: dict = {}
    if quarterly_income is not None and "Total Revenue" in quarterly_income.index:
        q = quarterly_income
        revenue = [value(q, "Total Revenue", i) for i in range(q.shape[1])]
        review["latest_quarter_end"] = str(q.columns[0].date())
        review["revenue_qoq_pct"] = _growth(revenue, 1)
        review["revenue_yoy_pct"] = _growth(revenue, 4)  # same quarter last year
        shown = range(min(quarters, q.shape[1]))
        review["gross_margin_pct_by_quarter"] = [
            _round_pct(ratio(value(q, "Gross Profit", i), revenue[i])) for i in shown
        ]
        review["operating_margin_pct_by_quarter"] = [
            _round_pct(ratio(value(q, "Operating Income", i), revenue[i])) for i in shown
        ]
        review["diluted_eps_by_quarter"] = [value(q, "Diluted EPS", i) for i in shown]

    if earnings_history is not None and "Reported EPS" in earnings_history.columns:
        reported = earnings_history.dropna(subset=["Reported EPS"]).sort_index(ascending=False)
        surprises = [float(s) for s in reported["Surprise(%)"].head(quarters) if pd.notna(s)]
        review["eps_surprise_pct_last_quarters"] = surprises
        review["eps_beats"] = sum(s > 0 for s in surprises)
        review["eps_misses"] = sum(s < 0 for s in surprises)

    return review or None


def _growth(series: list[float | None], lag: int) -> float | None:
    if len(series) <= lag or series[0] is None or not series[lag]:
        return None
    return round((series[0] / series[lag] - 1) * 100, 2)


def _round_pct(fraction: float | None) -> float | None:
    return None if fraction is None else round(fraction * 100, 2)
