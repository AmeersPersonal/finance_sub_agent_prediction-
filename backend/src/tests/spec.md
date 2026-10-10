# spec: backend/src/tests/

## TODOS

- [ ] No tests for `ai/llm.py` retry behaviour (`RETRYABLE_STATUS`).
- [ ] No tests for `main.py` argument handling or `render`.
- [ ] Add focused audit explanation tests and OAuth tests once authentication is implemented.
- [ ] Add a coverage run to the commands below.

## Purpose

Synthetic tests make no external network or Gemini calls. PostgreSQL checks
are opt-in and connect only through a local Unix socket to an isolated test
database. API tests use an in-process client with mocked services.

## Layout

| File | Covers |
|---|---|
| `conftest.py` | `snapshot` fixture (synthetic `MarketSnapshot`), `fake_llm` / `failing_llm`, sample statements and Street data |
| `test_pipeline.py` | `predict()` end to end with the fake LLM |
| `test_api.py`, `test_service.py`, `test_sources.py` | Dashboard validation/error handling, ingestion/evidence orchestration, and mocked online providers |
| `test_model_data.py` | Stored-row conversion, timezone/session checks, and rejection of missing/invalid values |
| `test_database.py` | Credential-safe configuration, frozen input packets, and opt-in local PostgreSQL persistence/constraints |
| `test_personas.py`, `test_confidence_score.py` | eligibility and aggregation |
| `test_evaluation.py` | baselines, log, scorer |
| `test_sentiment.py`, `test_feeds.py`, `test_rag_retrieval.py`, `test_tool.py` | ai helpers |
| `test_finance.py`, `test_fundamentals.py`, `test_positioning_macro.py`, `test_backtest.py`, `test_linear_regression.py` | finance modules |

## Rules

- Name files `test_*.py`; never name a module `pytest.py`.
- Use the `snapshot` and `fake_llm` fixtures; `predict()` takes `llm=` and `snapshot=`.
- Run from `backend/src/` with `pytest`.
- PostgreSQL integration checks skip unless `TEST_DATABASE_URL` points to an
  isolated local Unix socket. They never connect to cloud services and use a
  temporary schema, removed after each test. See `database/SETUP.md`.


## Latest verification

153 tests passed with local PostgreSQL integration enabled. Separately, a real
Nvidia forecast was saved and read back with market data and online source
links; the running API returned charts/news/forecast/pending evaluations. Those
live smoke checks are not part of pytest and do not measure forecast accuracy.
