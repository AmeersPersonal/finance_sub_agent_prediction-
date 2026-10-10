# spec: backend/src/

## TODOS

- [ ] Remove `ai/test.py` (empty; pytest only collects `tests/test_*.py`). Still open: run `git rm backend/src/ai/test.py`.
- [x] Expose `predict()` over HTTP: `api/app.py` (`POST /predict`, `GET /score`, `GET /health`, OAuth routes); `uvicorn` pinned.
- [x] Wire `audit/` into the CLI (`--audit`) and `Prediction` (`Prediction.audit`, also `"audit": true` on `POST /predict`).
- [x] Add a `--weights` CLI flag: `--weights long_term=2,day_trader=0.5`, or `--weights auto` to derive them from the scored log.
- [x] Give the regression walk-forward backtest its own CLI entry: `python main.py SPY --backtest [--features ...]` (no LLM, not logged).
- [ ] Require a signed-in user (`oauth.routes.current_user`) on `POST /predict` before the API is reachable from the internet: every call spends Gemini quota. Then rate-limit it per user.

## Purpose

Application source root. `main.py` is the CLI and `api/` the HTTP API; both run
the same pipeline. Everything else is a package.

## Layout

| Path | Role |
|---|---|
| `main.py` | CLI: predict + log, `--score`, `--backtest`; `--weights`, `--live`, `--audit` |
| `api/` | FastAPI app: `/predict`, `/score`, `/health`, plus `oauth/` routes (`api/spec.md`) |
| `ai/` | LLM pipeline: fetch, sentiment, personas, aggregation, evaluation, live quotes (`ai/spec.md`) |
| `audit/` | Explains a prediction: company overview, data checks, risk checklist, news digest (`audit/spec.md`) |
| `finance/` | Pure numeric functions, no LLM, no network (`finance/spec.md`) |
| `oauth/` | Google OIDC sign-in routes and in-memory sessions (`oauth/spec.md`) |
| `tests/` | Offline test suite (`tests/spec.md`) |
| `requirements.txt` | Direct dependencies, pinned (`==`) |
| `requirements.lock` | Every transitive dependency, pinned with hashes (`pip-compile` output) |
| `pytest.ini` | `pythonpath = .`, `testpaths = tests` |
| `.coveragerc` | Coverage source and report settings for `pytest --cov` |
| `CLAUDE.md` | Rules and conventions for AI coding agents |

## Data flow

```
main.py / api/app.py
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
```

## Dependency direction

`main.py, api/ -> audit -> ai -> finance`, and `api/ -> oauth`. `finance/`
never imports `ai/`; `ai/` never imports `audit/`; `oauth/` imports nothing
from the pipeline. Only `ai/llm.py` talks to the model provider. `tests/` may
import everything.
