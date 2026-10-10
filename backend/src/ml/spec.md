# spec: backend/src/ml/

Status: built. Model A was evaluated on 2026-10-09 and **failed its gate**
(see Results), so nothing is integrated. Model B and the persona-call levers
are coded and tested offline, but they are blocked on data: no live
prediction has resolved yet (`data/predictions.jsonl` doesn't exist).

Estimated 5-day 3-way accuracy (estimates, not measurements; nothing is scored
live yet): today ~39-44%; after Phase 2 levers 1-4 ~42-46%; with a passing
stacker ~43-48%; realistic ceiling ~47-50%. Anything far above that is leakage.

## TODOS

- [x] **Phase 0, capture training data first.** `Prediction.features` (`ai/schemas.py`) is filled in `ai/main.py` by `ai/features.extract_features` from the strategy packets, regression output and sentiment. Optional field, so old log lines still load; no prompt change, so no `PROMPT_VERSION` bump. Every prediction logged from now on carries its training row.
- [x] **Framework: PyTorch with CUDA.** `model.get_device()` picks CUDA when it's available and CPU otherwise. `python ml/model.py` prints the device. TensorFlow was dropped because it has no GPU support on native Windows. For the GPU on Windows, run `pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu130 --force-reinstall --no-deps` after the requirements; the PyPI wheel is CPU-only.
- [ ] **Phase 1, collect live predictions (no code).** Run 25+ tickers daily at the 1-day and 5-day horizons until about 300 predictions have resolved, then `python main.py --score`, `python -m ml coverage` and `python -m ml stacker`. Until then every accuracy figure for the personas is an estimate. Expected: 38-43% (1d) and 39-44% (5d) 3-way, against always-up at 39.9% / 41.9%.
- [x] **Phase 2 levers: all built.** Each one is still to be judged against always-up on held-out dates once Phase 1 has data.
  1. [x] Accuracy at coverage: the top 50% and 30% of calls by strength, and calls where all strategies agree, each beside always-up on the same rows. It also reports the strength threshold to abstain below. See `calibration.accuracy_at_coverage` and `python -m ml coverage`.
  2. [x] Strength calibrated into P(call right), isotonic or Platt, and scored walk-forward by Brier against a constant hit rate (`calibration.StrengthCalibrator`, `evaluate_calibration`).
  3. [x] Per-persona, strategy and mode weights, learned by model B (logistic). `python -m ml stacker` prints the largest weights and lists the persona columns that add little. Blocked on 300 scored predictions.
  4. [x] Relative-return target for model A: `python -m ml price --target relative` (vs SPY, with a flat band sized from the relative series). This was the closest model A came to passing (Results).
  5. [x] Earnings-window split in the coverage report (`earnings inside the horizon` / `no earnings`).
  6. [x] Cross-sectional ranking for model A: each period, long the top fifth of tickers by P(up) - P(down) and short the bottom fifth (`walkforward.rank_spread`, the `rank spread` column).
  7. [x] Longer horizons: `python -m ml price --horizon 20 --horizon 60` (Results).
- [x] **Model comparators, simplest first:** `LogisticModel`, `BoostedTreesModel` (LightGBM) and `MLPModel` (PyTorch, GPU) behind one interface in `model.py`, all trained on the same rows. LSTM, CNN and GNN stay out of scope.
- [x] **Model A, pooled price network:** built and evaluated. **Failed the gate** at 1 and 5 days with both targets (Results). Not integrated.
- [ ] **Model B, persona stacker:** built (`dataset.stacker_rows`, `walkforward.evaluate_stacker`, `python -m ml stacker`) and tested on synthetic outcomes. Blocked until about 300 predictions have resolved.
- [x] Walk-forward evaluation with a purge gap (`walkforward.py`), reported against always-up, momentum and the linear regression, plus `--weights auto` for B.
- [ ] Integration, only for a model that passed its gate (see Integration). None has.
- [x] Added `ml/` to the layout tables in `src/spec.md` and `src/CLAUDE.md`, pinned `scikit-learn` and `lightgbm`, and regenerated `requirements.lock`.
- [ ] Re-run `python -m ml price` and `--target relative` each quarter. The current test window is one year (2025-10 to 2026-10) of a rising market (equal-weight buy-and-hold +25%), so it covers a single regime.
- [ ] Relative target for model B and the scorer. This needs SPY closes at resolution time, in `ai/evaluation.resolve`.
- [ ] Lever 5, second half: split out calls with insider-buying clusters inside the horizon (`long_term.insiders.*` in `Prediction.features`).
- [ ] Lever 6 for the personas: rank tickers predicted on the same day. This needs Phase 1 runs over many tickers per day.
- [ ] Only if a model passes the model A gate: re-test it with whole tickers held out of training, the stricter reading of "held-out tickers".
- [ ] A FinBERT-style per-headline score, tried as a *feature*, not as a predictor.

## Purpose

Improve accuracy by learning from outcomes instead of hand-set rules.

- **Model B** learns how much to trust the personas. It replaces the
  hand-built strategy-balanced vote and `--weights auto`'s shrinkage if it does
  better on held-out dates, and turns "strength" (not a probability) into a
  measured probability.
- **Model A** is a separate price-only predictor that sits beside the personas
  as one more baseline. It is never blended into the call and never shown to
  the personas, so it can't lower the persona call's accuracy.

## Files

| File | Role |
|---|---|
| `__main__.py` | CLI: `python -m ml price` (model A plus the gate verdict), `stacker` (model B), `coverage` (levers 1, 2, 5). `--save` stores fitted models |
| `dataset.py` | `Dataset` rows, labelled like the scorer (`CLASSES` = down, flat, up). `price_rows` / `pooled_price_rows` reuse `linear_regression.FEATURE_FUNCTIONS`, `forward_return` and `flat_band_series`, with an optional relative-to-benchmark target. `stacker_rows` turns scored `Outcome`s into per-persona votes (collapsed across modes) plus each strategy's and mode's net score. Every row has `known_on`, the day its label became known |
| `model.py` | `LogisticModel`, `BoostedTreesModel`, `MLPModel` and `PriorModel` (class frequencies). Each has `fit(X, y)` and `predict_proba(X)`, returning (n, 3). `get_device()`. The MLP trains on CUDA when there is a GPU and is pickled on CPU |
| `walkforward.py` | `schedule` (expanding window, refit per block of dates, trains only on rows with `known_on <= block start`), `walk_forward`, the metrics (accuracy, log-loss, Brier, reliability), `evaluate_price_models` (baselines, per-ticker beat share, trading through `finance.backtest`, rank spread, gate) and `evaluate_stacker` (persona call, logged baselines, `--weights auto` replayed walk-forward, gate) |
| `calibration.py` | Levers 1, 2 and 5 on scored persona calls: `accuracy_at_coverage`, `coverage_report`, `StrengthCalibrator` (isotonic or Platt) and `evaluate_calibration` (walk-forward Brier) |
| `store.py` | `save` / `load` / `latest` under `backend/data/models/` (gitignored): `<name>-<UTC time>.joblib` plus a sidecar `.json` holding the training date, rows, tickers, features or columns, walk-forward scores and the git revision |

## Commands

From `backend/src/`, with the project venv active:

```
python ml/model.py                              # which device the MLP will use
python -m ml price                              # model A: 25 tickers, 1- and 5-day, gate verdict
python -m ml price --target relative            # lever 4: return vs SPY
python -m ml price --horizon 20 --horizon 60    # lever 7 (not a gate run)
python -m ml price AAPL MSFT NVDA --models logistic --save
python -m ml stacker [--save]                   # model B, once 300 predictions have resolved
python -m ml coverage                           # levers 1, 2, 5 on the scored log
```

`price` downloads about 5 years of daily bars per ticker from Yahoo; `stacker`
and `coverage` fetch closes to score the log. None of them call the LLM.

## Gates

A model goes no further until it passes its gate. A failed gate is a result:
record the numbers here and stop.

- **Model A:** pooled out-of-sample 3-way accuracy beats always-up by more than
  the noise, at both the 1-day and 5-day horizons. "The noise" is
  `walkforward.GATE_MARGIN` = 2.5 points, about 2-3 points at ~200 test days
  per ticker. It must also beat always-up on more than half of the held-out
  tickers. That is implemented as each ticker's own rows on the held-out
  dates; every ticker is also in training.
- **Model B:** better log-loss and accuracy than `--weights auto` on held-out
  dates, with at least 300 scored predictions and `--score` showing it beside
  the baselines. `--weights auto` is replayed walk-forward: weights come from
  outcomes known before each block, and its call gets the probability that its
  weighted calls were right in training.

## Results: model A (2026-10-09)

25 tickers (SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, XOM,
JNJ, PG, KO, WMT, UNH, HD, CAT, BA, DIS, NFLX, AMD, INTC, PFE), 5 years of
daily bars and `linear_regression.FEATURES`. The test window is the last 20%
of dates (2025-10 to 2026-10, ~6,000 rows per horizon), refit every 21 dates.
Every model and baseline is scored on the same rows.

3-way accuracy, %. Model cells show accuracy (points vs always-up, share of
tickers where the model beat always-up):

| Target, horizon | always-up | momentum | regression | logistic | LightGBM | MLP |
|---|---|---|---|---|---|---|
| absolute, 1d | 39.6 | 38.5 | 38.4 | 40.0 (+0.4, 44%) | 39.5 (-0.1, 44%) | 39.4 (-0.2, 40%) |
| absolute, 5d | 41.4 | 38.0 | 40.1 | 41.0 (-0.3, 4%) | 40.5 (-0.8, 28%) | 40.6 (-0.8, 36%) |
| relative, 1d | 38.1 | 38.7 | 38.3 | 39.3 (+1.3, 54%) | 39.6 (+1.6, 67%) | 39.0 (+0.9, 63%) |
| relative, 5d | 39.3 | 38.7 | 41.6 | 40.8 (+1.5, 50%) | 41.5 (+2.1, 63%) | 42.1 (+2.8, 54%) |
| absolute, 20d | 43.5 | 37.4 | 42.1 | 43.2 (-0.3, 0%) | 41.1 (-2.4, 24%) | 44.1 (+0.6, 64%) |
| absolute, 60d | 49.9 | 41.1 | 45.7 | 49.9 (0.0, 0%) | 48.2 (-1.7, 36%) | 50.2 (+0.3, 32%) |

- **Gate: every model fails.** No model clears 2.5 points at 1 day with
  either target. The relative-target MLP clears it at 5 days (+2.8 points, 54%
  of tickers), but the relative regression baseline is also at 41.6% there, so
  the MLP is only 0.5 points above the simplest price model.
- **Log-loss** is within 0.004 of the class-frequency prior in every run. The
  probabilities carry almost no information beyond the base rates, and the
  reliability tables show the rare confident (>50%) calls aren't more often
  right.
- **Trading:** equal-weight buy-and-hold returned +25-26% (Sharpe ~1.8) over the
  test year. No model's long/short signal beat it at 1 or 5 days, after 5 bps
  costs.
- **20 and 60 days:** the labels overlap, so the year-long test window holds
  only ~12 and ~4 independent periods. Treat those rows as anecdotes.
- MLP numbers can move by a few tenths of a point between GPU runs and against
  CPU. That is well inside the noise.

## Integration (only after a gate passes)

- Model A becomes a fourth entry in the `baselines` dict
  (`ai/evaluation.py`), so `score()` reports it with no scorer change.
- Model B adds an optional `Prediction.calibrated` and a line in `render`
  (`main.py`).
- Models are retrained by an explicit command (`python -m ml ... --save`),
  never at request time. Load them with `store.load`, which unpickles, so
  load only files this code wrote.

## Design rules

- Purge gap equal to the horizon between train and test: targets overlap, so
  adjacent rows leak. `known_on` enforces it, for mixed horizons too. No random
  splits; walk-forward blocks group rows by date.
- Always-up is the bar in every report, not 33%.
- Every model and baseline in a report is scored on identical rows.
- Only live-logged predictions may train or score model B. Replaying history
  through the LLM leaks outcomes it saw in training.
- Point-in-time data (insiders, 13F, options, short interest) is a feature only
  from Phase 0 onward, never a historical one.
- Model A stays out of persona prompts, like the regression, so the two
  predictions stay independent.
- Tests are offline (`tests/test_ml.py`): synthetic prices, fixed seeds, the MLP
  on CPU, no downloads. Two guards: features use no future data, and training
  never sees targets that weren't known yet.
- Models and their outputs live in `backend/data/` (gitignored); never commit
  them.
- Prefer the simplest model that ties. Ship the MLP only if it clearly wins.
- `ml/` imports `ai/` and `finance/`; nothing imports `ml/` until a model is
  integrated.
