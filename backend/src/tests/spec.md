# spec: backend/src/tests/

## TODOS

- [ ] No tests for `ai/modes.py` env override of the strong model beyond `test_pipeline.py`.
- [x] Tests for `ai/llm.py` retry behaviour (`RETRYABLE_STATUS`): `test_llm.py`.
- [x] Tests for `main.py` argument handling and `render`: `test_cli.py`.
- [x] Tests for `audit/` and `oauth/`: `test_audit.py`, `test_oauth.py` (plus `test_api.py`, `test_live.py`).
- [x] Coverage run added to the commands below (`pytest-cov`, settings in `../.coveragerc`).
- [ ] Starlette 1.7 warns that `TestClient` on `httpx` is deprecated in favour of `httpx2`; switch when `httpx2` is pinned.
- [ ] `ai/tool.py`'s network fetchers and `oauth.provider.HttpProvider` are untested offline; cover them with recorded responses (`httpx.MockTransport`, a fake `yf.Ticker`) if they start to break.

## Purpose

Synthetic tests make no external network or Gemini calls. PostgreSQL checks
are opt-in and connect only through a local Unix socket to an isolated test
database. API tests use an in-process client with mocked services.

## Layout

| File | Covers |
|---|---|
| `conftest.py` | `snapshot` fixture (synthetic `MarketSnapshot` with quarterly statements and news), `fake_llm` / `failing_llm` (personas, sentiment, news digest), sample statements and Street data |
| `test_pipeline.py` | `predict()` end to end with the fake LLM, including multi-mode runs; packets; prompt changelog |
| `test_service.py`, `test_sources.py` | Ingestion/evidence orchestration and forecast options in `predict_and_store`; mocked online providers |
| `test_model_data.py` | Stored-row conversion, timezone/session checks, and rejection of missing/invalid values |
| `test_database.py` | Credential-safe configuration, frozen input packets, and opt-in local PostgreSQL persistence/constraints |
| `test_personas.py`, `test_confidence_score.py` | eligibility and aggregation |
| `test_evaluation.py` | baselines, log, scorer (NYSE calendar, splits, pending reasons), derived strategy weights |
| `test_features.py` | feature flattening, `Prediction.features` logged, old log lines still load |
| `test_ml.py` | `ml/`: labels match the scorer, no future data in features or training, metrics, the three models (MLP on CPU), store round trip, model B and `--weights auto` replay, coverage and calibration, `python -m ml` with fetches stubbed |
| `test_llm.py` | `GeminiLLM` retries, backoff and give-up, against a fake genai client |
| `test_live.py` | websocket live quote: first tick, timeout, dropped connection, fallback |
| `test_cli.py` | `main.py`: argument errors, `--weights`, `--backtest`, rendering, predict + log |
| `test_api.py` | The HTTP API with a faked service and LLM: routes, validation, option pass-through, error statuses, `/score`, OAuth mount, CORS |
| `test_oauth.py` | OAuth routes with a fake provider: state/CSRF, PKCE, replay, expiry, sessions |
| `test_audit.py` | company overview, data checks, risk checklist, news digest |
| `test_sentiment.py`, `test_feeds.py`, `test_rag_retrieval.py`, `test_tool.py` | ai helpers, news items, cache pruning, `clean_daily` |
| `test_finance.py`, `test_fundamentals.py`, `test_positioning_macro.py`, `test_backtest.py`, `test_linear_regression.py` | finance modules |

## Rules

- Name files `test_*.py`; never name a module `pytest.py`.
- Use the `snapshot` and `fake_llm` fixtures; `predict()` takes `llm=`, `snapshot=` and `live_feed=`.
- The API and OAuth tests override FastAPI dependencies; never call real providers.
- Keep the real `.env` out of tests: the API loads it only at startup, and CLI
  tests that call `main.main()` stub `load_dotenv`.
- PostgreSQL integration checks skip unless `TEST_DATABASE_URL` points to an
  isolated local Unix socket. They never connect to cloud services and use a
  temporary schema, removed after each test. See `database/SETUP.md`.

## Commands

From `backend/src/`:

```
pytest                                   # everything, offline
pytest --cov --cov-report=term-missing   # with coverage
TEST_DATABASE_URL='postgresql:///TEST_DB?host=/LOCAL_SOCKET_DIRECTORY' pytest   # plus PostgreSQL checks
```

Live smoke checks (`python -m database.smoke TICKER`) are not part of pytest
and do not measure forecast accuracy.
