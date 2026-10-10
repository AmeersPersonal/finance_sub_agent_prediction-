# spec: backend/src/

## TODOS

- [ ] Remove `ai/test.py` (empty; pytest only collects `tests/test_*.py`). Still open: run `git rm backend/src/ai/test.py`.
- [x] Expose `predict()` over HTTP (`api/`), with OAuth routes; `uvicorn` pinned.
- [x] Expose database-backed predictions and dashboard reads through `api/`.
- [x] Include source digest and educational risk explanations in database-backed predictions.
- [x] Wire `audit/` into the CLI (`--audit`) and `Prediction` (`Prediction.audit`, also `"audit": true` on prediction requests).
- [x] Add a `--weights` CLI flag: `--weights long_term=2,day_trader=0.5`, or `--weights auto` to derive them from the scored log.
- [x] Give the regression walk-forward backtest its own CLI entry: `python main.py SPY --backtest [--features ...]` (no LLM, not logged).
- [ ] Require a signed-in user (`oauth.routes.current_user`) on prediction requests before the API is reachable from the internet: every call spends Gemini quota. Then rate-limit it per user.

## Purpose

Application source root. `main.py` is the CLI and `api/` the HTTP API; both run
the same pipeline (the API always through `database.service`). Everything else is a package.

## Layout

| Path | Role |
|---|---|
| `main.py` | CLI: predict + log, `--score`, `--backtest`; `--weights`, `--live`, `--audit` |
| `api/` | The one FastAPI app (`api.main`): database-backed forecasts and dashboard reads, `/score`, plus `oauth/` routes (`api/spec.md`) |
| `ai/` | LLM pipeline: fetch, sentiment, personas, aggregation, evaluation, live quotes (`ai/spec.md`) |
| `audit/` | Explains a prediction: company overview, data checks, risk checklist, news digest; source digest and learning explanations (`audit/spec.md`) |
| `finance/` | Pure numeric functions, no LLM, no network (`finance/spec.md`) |
| `ml/` | Learned models (price classifier, persona stacker, calibration) behind walk-forward gates; `python -m ml` (`ml/spec.md`) |
| `sources/` | Online evidence: Yahoo/Google News RSS, Hacker News, optional SEC filings and press releases (`sources/spec.md`) |
| `oauth/` | Google OIDC sign-in routes and in-memory sessions (`oauth/spec.md`) |
| `database/` | PostgreSQL migrations and prediction/source persistence (`database/spec.md`, `database/SETUP.md`) |
| `tests/` | Offline test suite (`tests/spec.md`) |
| `requirements.txt` | Direct dependencies, pinned (`==`) |
| `requirements.lock` | Every transitive dependency for every platform, pinned with hashes (`uv pip compile --universal` output) |
| `pytest.ini` | `pythonpath = .`, `testpaths = tests` |
| `.coveragerc` | Coverage source and report settings for `pytest --cov` |
| `CLAUDE.md` | Rules and conventions for AI coding agents |

## Data flow

Database-backed CLI and API:

```
main.py (JSONL path)
  fetch_snapshot (ai/tool.py)            yfinance + feeds -> MarketSnapshot
  -> ai.main.predict()
       apply_live_quote (ai/live.py)     optional: websocket price replaces the REST one
       score_headlines (ai/sentiment.py) 1 Gemini call
       build_context (ai/agents.py)      per-strategy packet, numbers from finance/
       run_persona x N (ai/agents.py)    parallel Gemini calls via ai/llm.py
       aggregate (ai/confidence_score.py) strategy-balanced vote, optional strategy weights
       run_regression + baselines        finance/linear_regression.py, ai/evaluation.py
  -> audit_prediction (audit/analysis.py) optional: overview, checks, risk, 1 Gemini call for news
  -> Prediction (ai/schemas.py) -> data/predictions.jsonl

main.py --database / api.main
  -> database.service
     -> ai.tool + sources                 fetch market data and online evidence
     -> database.repository               store bars, snapshots, documents/chunks
     -> database.datasets                 freeze the snapshot's daily rows for regression
     -> dated keyword retrieval           choose per-strategy evidence, mixed by role
     -> ai.main.predict                   personas + separate regression
     -> audit                             source digest and learning context
     -> database.repository               save forecast, outputs, and evidence
```

The CLI without database persistence retains `ai.main.predict -> Prediction ->
data/predictions.jsonl`. `--no-log` skips persistence. Scoring reads forecasts,
fetches actual closes, and saves outcomes without rerunning the LLM.

## Dependency direction

`main.py, api/ -> database.service -> ai/sources/audit/repository`,
`main.py, api/ -> audit -> ai -> finance`, `ml -> ai, finance`, and
`api/ -> oauth`. `finance/` never imports `ai/`; `ai/` never imports `audit/`
or `ml/`; nothing imports `ml/` until a model passes its gate; `oauth/`
imports nothing from the pipeline. Only `ai/llm.py` talks to the model provider.
External source fetching belongs in `ai/tool.py`, `ai/feeds.py` and `sources/`,
not SQL repository functions. `tests/` may import everything.
