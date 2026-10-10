# spec: backend/src/

## TODOS

- [ ] Remove or fill `ai/test.py` (empty; pytest only collects `tests/test_*.py`).
- [ ] Expose `predict()` over HTTP (FastAPI app in `oauth/` or a new `api/`), then add `fastapi` and `uvicorn` to `requirements.txt`.
- [ ] Wire `audit/` into the CLI and `Prediction` once it has real code.
- [ ] Add a `--weights` CLI flag; `predict()` already accepts `strategy_weights`.
- [ ] Give the regression walk-forward backtest (`finance/linear_regression.py`) its own CLI entry.

## Purpose

Application source root. `main.py` is the CLI; everything else is a package.

## Layout

| Path | Role |
|---|---|
| `main.py` | CLI: predict + log, or `--score` to score the log against baselines |
| `ai/` | LLM pipeline: fetch, sentiment, personas, aggregation, evaluation (`ai/spec.md`) |
| `finance/` | Pure numeric functions, no LLM, no network (`finance/spec.md`) |
| `audit/` | Planned: news digests and investment risk (`audit/spec.md`) |
| `oauth/` | Planned: auth routes (`oauth/spec.md`) |
| `tests/` | Offline test suite (`tests/spec.md`) |
| `requirements.txt` | Pinned dependencies (`==`) |
| `pytest.ini` | `pythonpath = .`, `testpaths = tests` |
| `CLAUDE.md` | Rules and conventions for AI coding agents |

## Data flow

```
main.py -> ai.main.predict()
  fetch_snapshot (ai/tool.py)            yfinance + feeds -> MarketSnapshot
  score_headlines (ai/sentiment.py)      1 Gemini call
  build_context (ai/agents.py)           per-strategy packet, numbers from finance/
  run_persona x N (ai/agents.py)         parallel Gemini calls via ai/llm.py
  aggregate (ai/confidence_score.py)     strategy-balanced vote
  run_regression + baselines             finance/linear_regression.py, ai/evaluation.py
  -> Prediction (ai/schemas.py) -> data/predictions.jsonl
```

## Dependency direction

`main.py -> ai -> finance`. `finance/` never imports `ai/`. Only `ai/llm.py`
talks to the model provider. `tests/` may import everything.
