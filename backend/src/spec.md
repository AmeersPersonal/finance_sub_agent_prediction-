# spec: backend/src/

## TODOS

- [ ] Remove or fill `ai/test.py` (empty; pytest only collects `tests/test_*.py`).
- [x] Expose database-backed predictions and dashboard reads through `api/`.
- [x] Include source digest and educational risk explanations in database-backed predictions.
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
| `audit/` | Source digest and educational forecast/risk explanations (`audit/spec.md`) |
| `sources/` | Online RSS evidence and optional SEC filing collection (`sources/spec.md`) |
| `api/` | Local FastAPI dashboard routes (`api/spec.md`) |
| `oauth/` | Planned: auth routes (`oauth/spec.md`) |
| `database/` | PostgreSQL migrations and optional prediction/source persistence (`database/spec.md`, `database/SETUP.md`) |
| `tests/` | Offline test suite (`tests/spec.md`) |
| `requirements.txt` | Pinned dependencies (`==`) |
| `pytest.ini` | `pythonpath = .`, `testpaths = tests` |
| `CLAUDE.md` | Rules and conventions for AI coding agents |

## Data flow

Database-backed CLI and API:

```
main.py --database / api.main
  -> database.service
     -> ai.tool + sources                 fetch market data and online evidence
     -> database.repository               store bars, snapshots, documents/chunks
     -> database.datasets                 freeze the snapshot's daily rows for regression
     -> dated keyword retrieval           choose per-strategy evidence
     -> ai.main.predict                   personas + separate regression
     -> audit                             source digest and learning context
     -> database.repository               save forecast, outputs, and evidence
```

The CLI without database persistence retains `ai.main.predict -> Prediction ->
data/predictions.jsonl`. `--no-log` skips persistence. Scoring reads forecasts,
fetches actual closes, and saves outcomes without rerunning the LLM.

## Dependency direction

`api/main -> database.service -> ai/sources/audit/repository`; `ai -> finance`.
`finance/` remains numerical and never imports `ai/`. Gemini provider calls go
only through `ai/llm.py`. External source fetching belongs in `ai/tool.py`,
`ai/feeds.py`, and `sources/`, not SQL repository functions.
