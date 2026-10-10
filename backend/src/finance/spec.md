# spec: backend/src/finance/

## TODOS

- [x] `revenue_forecast.py` was a naive CAGR extrapolation; now labelled non-predictive in the packet (`naive_extrapolation_next_year` plus a `caveat`).
- [x] `risk_management.py` Altman Z used the latest annual statements only; `altman_z_ttm` uses the latest quarterly balance sheet and trailing-four-quarter EBIT and revenue, and the long-term packet prefers it (`basis` says which).
- [x] Tried extra features in `linear_regression.FEATURES` in walk-forward; none beat the current set, so `FEATURES` is unchanged (see Feature experiment).
- [x] `max_drawdown` unified: `indicators.max_drawdown` is the one implementation; `backtest.max_drawdown` builds the equity curve from 1.0 and calls it. This fixed a bug where a loss in the first period wasn't counted.
- [x] Documented that positioning data (insiders, 13F, short interest) is point-in-time and cannot be backtested (`positioning.py` docstring, Design rules).
- [ ] The regression baseline is *below* always-up on average (see Feature experiment). Keep it as a sanity check, but treat always-up as the bar the personas must clear.

## Purpose

Deterministic numeric code: indicators, ratios, risk measures, the regression
baseline. No LLM calls and no network. Functions take pandas/numpy inputs and
return numbers or small dicts, returning `None` when data is missing.

## Files

| File | Role |
|---|---|
| `indicators.py` | RSI, MACD, ATR, VWAP, volume profile, beta, relative strength, options sentiment, max drawdown, and the flat band |
| `linear_regression.py` | OLS on price features, walk-forward validated; the baseline the personas are scored against. `FEATURE_FUNCTIONS` registry; `FEATURES` is the kept set, `CANDIDATE_FEATURES` were tried and not kept |
| `backtest.py` | Strategy returns with costs; Sharpe, Sortino, max drawdown (of the equity curve), profit factor |
| `fundamentals.py` | Margins, FCF, ROIC, leverage, valuation; Beneish M-score; shared `value` / `ttm` / `ratio` helpers |
| `risk_management.py` | Altman Z-score (annual and TTM); ATR stop distance and fixed-fractional position size |
| `quarter_review_analysis.py` | 10-Q growth, margin trend, EPS surprises |
| `positioning.py` | Insider activity, institutions, short interest, analyst estimates and rating changes (point-in-time) |
| `macro.py` | Yield curve, CPI, unemployment, payrolls summaries |
| `revenue_forecast.py` | Annual revenue trend and a naive extrapolation, labelled as not a forecast |

## Design rules

- Flat band = 0.25 x trailing-1y daily volatility x sqrt(N), defined in `indicators.flat_band`; the personas, regression and scorer all share it.
- Return `None` instead of raising when an input is missing; raise `ValueError` only for invalid arguments.
- Financial-sector companies are excluded from Altman Z and Beneish (`NOT_APPLICABLE_SECTORS`).
- Positioning data is point-in-time: yfinance serves only today's values, so it must never be a regression feature or part of a backtest.
- Change `FEATURES` only on walk-forward evidence across many tickers, scored on identical rows.
- No imports from `ai/`.

## Feature experiment (2026-10-09)

25 tickers (SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, XOM,
JNJ, PG, KO, WMT, UNH, HD, CAT, BA, DIS, NFLX, AMD, INTC, PFE), 5 years of daily
bars, 1- and 5-day horizons. Each candidate was added on its own to `FEATURES`,
and every configuration was scored with `walk_forward` on the same last 20% of
rows (~200 days per ticker), so long-warmup features didn't get a different
test window. Rule to keep a candidate: better mean 3-way accuracy and mean
out-of-sample R^2 at both horizons. None qualified.

| Candidate | Δ accuracy, 1d / 5d (pp) | Δ R^2, 1d / 5d |
|---|---|---|
| `return_63d` | +0.08 / +0.24 | -0.0011 / -0.0015 |
| `return_252d` | -0.58 / -1.62 | -0.0055 / -0.0297 |
| `dist_from_sma200` | +0.28 / -0.08 | -0.0042 / -0.0190 |
| `volatility_ratio_21_63` | -0.32 / -0.40 | -0.0017 / -0.0097 |
| `range_5d` | -0.18 / +0.02 | -0.0024 / -0.0090 |
| `gap_1d` | -0.46 / 0.00 | -0.0052 / -0.0018 |
| `rsi_2` | +0.12 / -0.02 | -0.0000 / -0.0031 |
| `volume_5d_vs_60d` | +0.18 / -0.22 | +0.0005 / -0.0008 |

The current model scored 39.0% (1d) and 40.6% (5d) against always-up's 39.9%
and 41.9%, and beat always-up on 28% / 40% of tickers. Differences of a fraction
of a point are within noise at ~200 test days per ticker. Reproduce one ticker
with `python main.py SPY --backtest --features return_1d,...,return_63d`.
## Input adapter

The regression accepts a pandas daily frame containing `Close` and `Volume`. Database-backed calls pass the frozen per-forecast copy from `database/datasets.py`; this module itself remains numerical and does not connect to PostgreSQL. It computes its existing seven features and forward-return targets from that frame.
