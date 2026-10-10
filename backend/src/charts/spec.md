# spec: backend/src/charts/

## TODOS

- [x] Equity curve of the regression walk-forward vs buy and hold (`backtest.py`; `linear_regression.period_returns` exposes the per-period returns, and a test checks the curve ends where `run_regression`'s summary does).
- [x] Accuracy over time: rolling hit rate of the personas and each baseline (`score.accuracy_over_time`; needs 10 scored forecasts).
- [x] VWAP and volume profile for `5m` bars (`price.py`).

## Purpose

Turns data the backend already has (saved price bars, a forecast, the score
report) into chart-ready JSON for the frontend. The backend sends data, not
images: the frontend picks the library and gets hover, zoom and theming for free.
Pure functions with no network, database or LLM access; `api/` does the reads.

## Files

| File | Role |
|---|---|
| `base.py` | The one chart shape (`chart()`), JSON-safe number helpers |
| `price.py` | `price_charts(bars, ticker, interval)`: candles + SMA 20/50, volume, RSI, MACD, drawdown; `5m` adds session VWAP and a volume profile |
| `prediction.py` | `prediction_charts(prediction)`: votes, signed conviction, strategy and mode scores, signal summary, flat-band price range, regression vs buy and hold, baselines |
| `backtest.py` | `backtest_charts(bars, ticker, horizon_days)`: regression equity curve vs buy and hold, return per holding period |
| `score.py` | `score_charts(report, outcomes)`: accuracy vs baselines, relative to SPY, over time, by strategy / age band / mode / model / strength, suggested weights |

## Routes (in `api/main.py`)

| Route | Builder |
|---|---|
| `GET /stocks/{ticker}/charts?interval=1d&limit=250` | `price_charts` |
| `GET /stocks/{ticker}/charts/backtest?horizon_days=5` | `backtest_charts` (reads up to 2000 daily bars) |
| `GET /predictions/{id}/charts` | `prediction_charts` |
| `GET /score/charts` | `score_charts` (same fetch as `/score`) |

Each returns `{"charts": [...]}` plus the ticker or prediction id.

## Design rules

- Every chart has `id`, `title`, `kind`, `x`, `series`, `y_label`, `reference_lines`, `caption` (`base.py`); series `data` lines up index for index with `x`.
- Missing or non-finite values are `null`, never NaN (invalid JSON).
- Daily bars are stored at midnight New York time: convert to that zone before labelling, or every date lands on the wrong day.
- Indicators come from `finance/indicators.py` and `finance/linear_regression.py`; don't re-implement them here.
- Captions repeat the project's wording rules: signal strength is not a probability, flat is not unclear, always-up is the bar.
- Builders return `[]` when there isn't enough data; they don't raise.
- Can import `ai.schemas` and `finance/`; nothing imports `charts/` except `api/`.
