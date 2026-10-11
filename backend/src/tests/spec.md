# spec: backend/src/tests/

## TODOS

- [x] `ai/modes.py` reads the environment: `GEMINI_MODEL_STRONG` and the `alt` mode (`test_llm.py`).
- [x] Tests for `ai/llm.py` retry behaviour (`RETRYABLE_STATUS`): `test_llm.py`.
- [x] Tests for `main.py` argument handling and `render`: `test_cli.py`.
- [x] Tests for `audit/` and `oauth/`: `test_audit.py`, `test_oauth.py` (plus `test_api.py`, `test_live.py`).
- [x] Coverage run added to the commands below (`pytest-cov`, settings in `../.coveragerc`).
- [x] `httpx2==2.13.1` is pinned (a test dependency); Starlette's `TestClient` uses it and the deprecation warning is gone.
- [x] `ai/tool.py`'s fetchers run against a fake `yf.Ticker` (`test_tool.py`); `HttpProvider`, the second LLM provider and Finnhub against `httpx.MockTransport` (`test_oauth.py`, `test_llm.py`, `test_live.py`).

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
| `test_database.py` | Credential-safe configuration, frozen input packets, opt-in local PostgreSQL persistence/constraints, title search across historical upgrades/new RSS ingestion, the combined keyword/fallback passage cap, shared sessions, preferences, price revisions |
| `test_personas.py`, `test_confidence_score.py` | eligibility and aggregation |
| `test_evaluation.py` | baselines, log, scorer (NYSE calendar, splits, pending reasons), derived strategy weights |
| `test_features.py` | feature flattening, `Prediction.features` logged, old log lines still load |
| `test_ml.py` | `ml/`: labels match the scorer, no future data in features or training, metrics, the three models (MLP on CPU), store round trip, model B and `--weights auto` replay, coverage and calibration, the bias report, call-policy fitting (on and off), model A's logged signal and its leak guard, `python -m ml` with fetches stubbed |
| `test_replay.py` | `ml/replay.py`: forecast dates, the as-of view (a later split restated, nothing after the date), the blinded snapshot, resume and abort, a replayed forecast scored through a split, date-clustered intervals, `python -m ml replay` dry run and report |
| `test_policy.py` | `ai/policy.py`: only passed rules apply, a weak call is withheld with its numbers kept, `p_correct`, other horizons untouched; model A's signal logged and never in prompts; `same_forecast` accepts payloads saved before new fields; `main.py --policy` / `--price-model` |
| `test_llm.py` | `GeminiLLM` retries, backoff and give-up, against a fake genai client; the OpenAI-compatible provider and routing; modes from the environment |
| `test_live.py` | websocket live quote: first tick, timeout, dropped connection, fallback; Finnhub's quote; `LIVE_FEED` |
| `test_cli.py` | `main.py`: argument errors, `--weights`, `--backtest`, rendering, predict + log |
| `test_api.py` | The HTTP API with a faked service and LLM: routes, validation, option pass-through, error statuses, `/score`, OAuth mount, CORS |
| `test_api_access.py` | Sign-in on forecasts, per-user rate limits, background prediction jobs, the score cache, `/me/preferences` |
| `test_lambda_jobs.py` | Durable (Lambda) prediction jobs: event signing, submit/claim/finish with a fake store, the refused internal route |
| `test_accounts.py` | Email/password accounts: `/signup`, `/login`, scrypt hashing, same 401 for wrong email or password, attempt limits, sessions shared with Google sign-in |
| `test_frontend_contract.py` | The API fields, ordering and error bodies the dashboard and sign-in pages read, through the real repository (PostgreSQL checks need `TEST_DATABASE_URL`); the frontend's ticker rule equals the API's |
| `test_backup.py` | `database.backup`: retention schedule, pruning, credentials kept out of pg_dump's arguments |
| `test_charts.py` | `charts/` builders (alignment, JSON-safe nulls, thin data, 5m VWAP and volume profile, equity curve matching `run_regression`, accuracy over time) and the `/charts` routes |
| `test_paper.py` | Paper-trading arithmetic (buy, average cost, sell, P&L, rejections) and `/paper/*` routes with a faked service; the PostgreSQL round trip is in `test_database.py` |
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

## Retrieval regressions

The PostgreSQL tests recreate the pre-title-index schema inside a disposable
per-test schema, insert historical summary-only evidence, then apply migration
`005` and verify that document/chunk records are unchanged. Both that historical
document and a newly parsed RSS item must match a title-only keyword with
positive relevance; a newer unrelated document must not replace them.

Six parameterized cases cover zero, one, and two keyword hits with result limits
of four and six. They verify the combined two-passages-per-document cap, unique
chunks, keyword-first ordering, recency fallback, and filling from other
documents. Existing tests cover source versions, future exclusion, and roles.
Without `TEST_DATABASE_URL`, integration tests are skipped, not counted as passed.

## Commands

From `backend/src/`:

```
pytest                                   # everything, offline
pytest --cov --cov-report=term-missing   # with coverage
TEST_DATABASE_URL='postgresql:///TEST_DB?host=/LOCAL_SOCKET_DIRECTORY' pytest   # plus PostgreSQL checks
```

Live smoke checks (`python -m database.smoke TICKER`) are not part of pytest
and do not measure forecast accuracy.
