# spec: backend/src/finance/

## TODOS

- [ ] `revenue_forecast.py` is a naive CAGR extrapolation; replace it or label it clearly as non-predictive in the packet.
- [ ] `risk_management.py` Altman Z uses the latest annual statements only; consider quarterly data.
- [ ] Try extra features in `linear_regression.FEATURES` and keep only those that beat the baselines in walk-forward.
- [ ] `max_drawdown` exists in both `indicators.py` (price series) and `backtest.py` (returns); decide whether to unify.
- [ ] Document that positioning data (insiders, 13F, short interest) is point-in-time and cannot be backtested.

## Purpose

Deterministic numeric code: indicators, ratios, risk measures, the regression
baseline. No LLM calls and no network. Functions take pandas/numpy inputs and
return numbers or small dicts, returning `None` when data is missing.

## Files

| File | Role |
|---|---|
| `indicators.py` | RSI, MACD, ATR, VWAP, volume profile, beta, relative strength, options sentiment, and the flat band |
| `linear_regression.py` | OLS on price features, walk-forward validated; the baseline the personas are scored against |
| `backtest.py` | Strategy returns with costs; Sharpe, Sortino, max drawdown, profit factor |
| `fundamentals.py` | Margins, FCF, ROIC, leverage, valuation; Beneish M-score; shared `value`/`ratio` helpers |
| `risk_management.py` | Altman Z-score; ATR stop distance and fixed-fractional position size |
| `quarter_review_analysis.py` | 10-Q growth, margin trend, EPS surprises |
| `positioning.py` | Insider activity, institutions, short interest, analyst estimates and rating changes |
| `macro.py` | Yield curve, CPI, unemployment, payrolls summaries |
| `revenue_forecast.py` | Annual revenue trend and one-year projection |

## Design rules

- Flat band = 0.25 x trailing-1y daily volatility x sqrt(N), defined in `indicators.flat_band`; the personas, regression and scorer all share it.
- Return `None` instead of raising when an input is missing; raise `ValueError` only for invalid arguments.
- Financial-sector companies are excluded from Altman Z and Beneish (`NOT_APPLICABLE_SECTORS`).
- No imports from `ai/`.
