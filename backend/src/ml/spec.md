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
- [ ] **Phase 1, collect live predictions (no code).** Run 25+ tickers daily at the 1-day and 5-day horizons until about 300 predictions have resolved, then `python main.py --score`, `python -m ml coverage` and `python -m ml stacker`. Since the database merge, collect them in **one** store: either the database (`python main.py TICKERS --database`, or the API, which only saves there) and then add `--database` to all three commands, or the JSONL log without it. Predictions in one store are invisible to commands reading the other. Until then every accuracy figure for the personas is an estimate. Expected: 38-43% (1d) and 39-44% (5d) 3-way, against always-up at 39.9% / 41.9%.
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
- [ ] Re-run `python -m ml price` and `--target relative` each quarter. The current test window is one year (2025-10 to 2026-10) of a rising market (equal-weight buy-and-hold +25%), so it covers a single regime. Next due 2027-01.
- [x] Relative target for model B and the scorer: scoring fetches SPY too, and each `Outcome` carries the return relative to SPY over the same sessions, classified with the prediction's flat band (`relative_actual`; `Report.relative`). `python -m ml stacker --target relative` trains and scores model B on it; its baselines are scored on the same relative label. The band is the stock's own, not one sized from the relative series as in model A, since that history isn't logged.
- [x] Lever 5, second half: `python -m ml coverage` splits calls made during an insider-buying cluster (`calibration.insider_buying_cluster`: at least 3 purchases and net buying over yfinance's trailing 6 months, from `long_term.insiders_last_6m.*`; Yahoo gives no dates, so "inside the horizon" isn't available). Forecasts without insider data fall in neither table.
- [x] Lever 6 for the personas: `calibration.persona_rank_spread`, printed by `python -m ml coverage`: on each day with 5+ tickers predicted at one horizon, long the top fifth by net score, short the bottom fifth. Results need Phase 1 runs over many tickers per day.
- [ ] Only if a model passes the model A gate: re-test it with whole tickers held out of training, the stricter reading of "held-out tickers". Not started on purpose: none has passed.
- [x] **Bias check** (`python -m ml bias`, 2026-10-10 on the 500-forecast replay): the call mix matches the outcome mix (5d: up 41% called vs 36% actual, flat 24% vs 24%), so no prior correction. long_term voted flat 73% of the time and was right on 24-27% of those votes: it treated "horizon too short for my style" as flat. Flat calls were the worst row (1d 25%, 5d 15%). Fixed in prompt version 7 (past outcome shares in `horizon`, flat is not a way to pass). 5d up calls ended down 47% of the time, but momentum scored 28.8% on the same rows: a 10-day reversal, not a persona bias.
- [x] Replay (`python -m ml replay`, `ml/replay.py`), prompt version 7: personas are **behind always-up** at both horizons. Against version 6 on the same rows version 7 is worse at 1 day (-6.2 points, interval excludes 0) and not better at 5, because its unclear calls went up (Results: replay).
- [x] Prompt version 8 = v7's base rates with v6's system prompt (v7's flat instruction reverted). Level with v6 on the replay (-2.1 / -0.7 points, intervals around zero), +4 to +5 points over v7 (not significant alone). Prompt wording hasn't moved accuracy; don't tune it further without live data.
- [x] Flat vote: forcing personas off flat (v7) made accuracy worse, so it was reverted in v8. Flat calls are right at the base rate (24-26%), so they neither help nor hurt; the lever is elsewhere (regression as the default call).
- [ ] Persona up/down calls trail the price-only regression by 19-24 points on the replay. Test the regression as the default call, or as a stacker column, once Phase 1 data exists.
- [x] **Call policy** (`calibration.fit_call_policy`, `ai/policy.py`, `main.py --policy`): abstain below the strength keeping the strongest half of calls, per horizon, enabled only if the kept calls beat always-up by `GATE_MARGIN` on held-out later calls (30+ kept, 100+ scored); strength -> P(right) curve, enabled only if its walk-forward Brier beats a constant. Dry run on the replay, not saved: 1d would abstain below 0.32 (44.1% vs 35.3% always-up, n=34); 5d had 29 held-out calls, one short.
- [ ] Fit the call policy on Phase 1 data (`python -m ml coverage --save`, plus `--database` if that's the store) and only then use `--policy`. The API doesn't apply the policy yet.
- [x] **Model A as a stacker column:** `main.py --price-model` logs model A's probabilities in `Prediction.price_model`; `stacker_features` adds `price_model.edge` (P(up) - P(down), NaN unless the forecast is after the model's `trained_through`) and `regression.predicted_return_pct`. Collect Phase 1 with `--price-model` so model B can judge it.
- [ ] A FinBERT-style per-headline score, tried as a *feature*, not as a predictor. Blocked on data like model B: headlines can't be backfilled, so the feature can only be judged on scored live forecasts (and it adds `transformers` plus a model download).

## Notes from the database merge (2026-10-10)

For whoever builds the "mimic live data" run. What changed under `ml/`:

- **Scorer.** `ai/evaluation.py` now uses the database branch's scorer: outcome
  dates come from the NYSE calendar (holidays and early closes handled), a bar
  is final 30 min after the close, and a missing bar, unverified split history
  or unknown exchange leaves a prediction pending instead of scoring another
  day. `fetch_history` is gone: `fetch_closes` returns closes whose split
  history travels in `series.attrs`. `resolve()` keeps its Outcome-or-None
  contract; `assess()` also says *why* one is pending (`Report.pending_details`).
  Per-mode/per-model accuracy and `derive_strategy_weights` are unchanged.
- **Prompt version 6** = the database branch's changes: personas get retrieved
  news/filing passages labelled by role. Direct `predict()` without
  `documents_by_strategy` falls back to `ai/docs/`, which is empty.
- **Where predictions live.** The API saves only to PostgreSQL. `python -m ml
  stacker --database` / `coverage --database` read those; without the flag
  they read the JSONL log. Don't mix the two stores in one training set.
- **Persona rows per mode** are stored as `persona:<id>:<mode>` (default mode
  keeps `persona:<id>`).

If you train model B on backdated (replayed) predictions instead of live ones,
these are the traps we found while checking the same idea:

- Only **prices** can be cut back to a past date (`database/smoke.py`'s
  `backdated()` shows how: daily, market, Nasdaq, sector and VIX frames,
  `intraday=None`, `last_price`, `previous_close`, `fetched_at`). Fundamentals,
  analyst targets and rating changes, insiders, institutions, options, short
  interest and the earnings calendar are **today's values**; headlines and the
  stored documents are too (the database only has documents from 2026-10-09).
  Left in, they leak the outcome into the persona call *and* into
  `Prediction.features` (so `--include-packet` would learn from them). Null
  them or list them as unavailable.
- Keep backdated runs in their own JSONL file with a warning in
  `data_warnings`; never save them to the database, where they would mix with
  live forecasts and their evaluations.
- Check the Gemini model's training cutoff against the replayed dates, and
  freeze the prompt version and modes for the whole run (the stacker doesn't
  separate prompt versions).
- 25 tickers on the same days are strongly correlated: a few weeks of replay
  is far fewer independent samples than its row count. Report it as a
  backtest, not live accuracy, and keep always-up as the bar.
- Quota: each forecast costs one Gemini call per persona per mode, plus one
  for headline sentiment. 25 tickers x 2 horizons x 13 personas is ~700 calls
  per replayed day.

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
| `__main__.py` | CLI: `python -m ml price` (model A plus the gate verdict), `stacker` (model B), `coverage` (levers 1, 2, 5; `--save` fits `data/call_policy.json`), `bias` (calls vs outcomes). `--save` stores fitted models |
| `dataset.py` | `Dataset` rows, labelled like the scorer (`CLASSES` = down, flat, up). `price_rows` / `pooled_price_rows` reuse `linear_regression.FEATURE_FUNCTIONS`, `forward_return` and `flat_band_series`, with an optional relative-to-benchmark target. `stacker_rows` turns scored `Outcome`s into per-persona votes (collapsed across modes) plus each strategy's and mode's net score. Every row has `known_on`, the day its label became known |
| `model.py` | `LogisticModel`, `BoostedTreesModel`, `MLPModel` and `PriorModel` (class frequencies). Each has `fit(X, y)` and `predict_proba(X)`, returning (n, 3). `get_device()`. The MLP trains on CUDA when there is a GPU and is pickled on CPU |
| `walkforward.py` | `schedule` (expanding window, refit per block of dates, trains only on rows with `known_on <= block start`), `walk_forward`, the metrics (accuracy, log-loss, Brier, reliability), `evaluate_price_models` (baselines, per-ticker beat share, trading through `finance.backtest`, rank spread, gate) and `evaluate_stacker` (persona call, logged baselines, `--weights auto` replayed walk-forward, gate) |
| `calibration.py` | Levers 1, 2 and 5 on scored persona calls: `accuracy_at_coverage`, `coverage_report`, `StrengthCalibrator` (isotonic or Platt) and `evaluate_calibration` (walk-forward Brier). `fit_call_policy` (the abstain threshold and calibration curve `ai/policy.py` applies, each enabled only after a held-out check) and `bias_report` (confusion of calls vs outcomes, persona votes per strategy, rationales citing missing data). A call the policy withheld counts as made (`raw_call`) |
| `replay.py` | `python -m ml replay`: backdated forecasts through the real `predict()`, scored on the closes that followed. `replay_sessions` (every Nth settled NYSE session), `PriceBook` / `as_of_view` (raw split-adjusted closes, restated to the share units of the forecast day so the scorer doesn't count a split twice), `blind_snapshot` (price-derived inputs only; `BLIND_SOURCES` listed as unavailable), `run_replay` (resumable, stops after N failures in a row), `cluster_ci` / `compare` / `verdict` (accuracy and the edge over always-up with intervals that resample whole dates), `compare_runs` (two replays paired on ticker, date and horizon, for `--against`) |
| `price_signal.py` | `price_signal(horizon)`: the latest saved model A for that horizon as a function of daily bars, for `main.py --price-model`. Logged in `Prediction.price_model`, never shown to personas |
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
python -m ml coverage --save                    # also fit data/call_policy.json (main.py --policy)
python -m ml bias                               # calls and persona votes vs outcomes, per horizon
python -m ml stacker --database                 # the same on forecasts saved in PostgreSQL
python -m ml coverage --database
python -m ml replay --dry-run                   # the plan: forecasts and Gemini calls, nothing spent
python -m ml replay [TICKERS] [--dates 12 --step 5 --horizon 1 --horizon 5 --after YYYY-MM-DD --age 25-39]
python -m ml replay --report-only [--out FILE]  # score a finished replay file again
python -m ml replay --report-only --out NEW --against OLD   # the change on the rows both scored
```

`replay` is the only command here that calls the LLM (one call per persona per
forecast; 12 tickers x 12 dates x 2 horizons is 3,744 calls). It writes
`data/replay-v<prompt version>.jsonl`, resumes from it, and stops after 5
forecasts in a row fail. See "Results: replay" for how to read it.

Never fit the call policy or the stacker on a replay file: it is prices only, and
the LLM may have seen the period (see the database-merge notes). `replay` prints
the policy those rows would give for information and doesn't save it.

`price` downloads about 5 years of daily bars per ticker from Yahoo; `stacker`
and `coverage` fetch closes to score the log (or, with `--database`, the saved
forecasts, appending any new outcomes to the `evaluations` table). None of them
call the LLM. `Prediction.features` is stored in the database payload too, so
`--include-packet` works either way.

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

## Results: replay (2026-10-11, prompt version 7)

`python -m ml replay`: 12 stocks (AAPL MSFT NVDA AMZN JPM XOM JNJ PG KO CAT
NFLX AMD) x 12 forecast dates (every 5 sessions, 2026-07-16 to 2026-10-02) x
1- and 5-day horizons = 288 forecasts, all 13 personas, `gemini-3.5-flash-lite`.
Prices only: fundamentals, analysts, options, news and earnings dates were
withheld and listed as unavailable. The model's training cutoff is unknown, so
the dates may overlap what it has seen. 144 forecasts per horizon on 12 dates,
one rising market: treat the intervals as the real size of the claim.

3-way accuracy, % (95% interval resampling whole dates):

| Horizon | personas | always-up | momentum | regression | personas - always-up |
|---|---|---|---|---|---|
| 1d | 27.8 [22.9, 32.6] | 37.5 [29.9, 45.8] | 37.5 | 46.5 [37.5, 54.2] | -9.7 pts [-20.1, -0.7] |
| 5d | 20.8 [13.2, 28.5] | 40.3 [34.7, 46.5] | 32.6 | 44.4 [39.6, 50.7] | -19.4 pts [-27.1, -11.8] |

- **Behind always-up and the regression at both horizons**, and against SPY
  at 5 days. At 1 day against SPY it can't be told apart from always-up.
- **Flat is never called** (0 calls of 288). Version 7 cut long_term's flat
  votes from 73% to 8-12%, but every strategy followed, so the 24-25% of
  outcomes that are flat are all misses. Unclear is 19% (1d) and 28% (5d).
- **Up calls** are right 38% (1d) and 33% (5d), about the up share of outcomes.
  **Down calls** are right 28% and 17%, worse than guessing the base rate.
- Citing missing data didn't lower accuracy (34-35% vs 34-36%), so the
  blinding itself isn't what's hurting. The version 6 replay, which still saw
  today's fundamentals, scored 35% and 24% on other dates: more data didn't
  rescue it there either.
- The call policy has nothing to fit: 18-22 held-out calls kept, 30 needed.

A floor for the live app (which has fundamentals and news), not live accuracy.
Phase 1 stays the real measurement.

### Version 6 against version 7, same rows (2026-10-11)

The committed version 6 prompt on the same 12 tickers, 12 dates, horizons and
blinding (`data/replay-v6-blinded.jsonl`; run through a launcher that loads
`ai/agents.py` from git, the working tree untouched). `python -m ml replay
--report-only --out replay-v7.jsonl --against replay-v6-blinded.jsonl`:

| Horizon | v6 | v7 | v7 - v6 | always-up |
|---|---|---|---|---|
| 1d | 34.0 [27.1, 39.6] | 27.8 [22.9, 32.6] | **-6.2 pts [-11.1, -1.4]** | 37.5 |
| 5d | 26.4 [18.1, 34.7] | 20.8 [13.2, 28.5] | -5.6 pts [-12.5, +2.1] | 40.3 |

- **Version 7 is worse at 1 day, and not better at 5.** Both versions are behind
  always-up; v6 is behind it at 5 days by 13.9 points [-23.6, -4.2] and at 1 day
  can't be told apart.
- **Where v7 loses:** "unclear" went from 3.5% / 6.2% of calls to 19.4% / 27.8%,
  and an unclear call is always a miss. With flat votes gone, a split panel
  has no flat mass to land on, so `confidence_score.aggregate` falls through to
  unclear. v6's flat calls were right 25-26% of the time, the base rate, so
  they cost nothing.
- **Blinding changed little:** v6 blinded (34.0% / 26.4%) is close to the
  leaky v6 replay on other dates (35.2% / 24.0%).
- v7 changed two things at once (base rates in the packet, and the prompt's
  flat instruction), so this doesn't say which hurt. Version 8 is the
  ablation: v7's base rates with v6's system prompt.

| Horizon | v8 | v8 - v6 | v8 - v7 | always-up |
|---|---|---|---|---|
| 1d | 31.9 [24.3, 39.6] | -2.1 pts [-5.6, +2.8] | +4.2 pts [-0.7, +9.7] | 37.5 |
| 5d | 25.7 [18.1, 34.0] | -0.7 pts [-2.8, +1.4] | +4.9 pts [-2.8, +11.8] | 40.3 |

- **The flat instruction was what hurt.** Unclear is back to 6.2% / 4.9% of
  calls, and v8 is level with v6.
- **The base rates have no measurable effect**: -2.1 and -0.7 points against
  v6, both intervals around zero. Kept because they're harmless and cost
  nothing, not because they help.
- **Still behind always-up at 5 days** (-14.6 points [-23.6, -4.9]) and
  behind the regression at both horizons. Flat is called 30% (1d) and 41%
  (5d) of the time and is right about 24-26%, the base rate.
- Three prompt versions all land within a few points of each other on 144
  forecasts per horizon: wording isn't the lever.

## Integration (only after a gate passes)

- Model A becomes a fourth entry in the `baselines` dict
  (`ai/evaluation.py`), so `score()` reports it with no scorer change.
- Model B adds an optional `Prediction.calibrated` and a line in `render`
  (`main.py`). The persona strength's own calibration is already
  `Prediction.p_correct` (`ai/policy.py`).
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
