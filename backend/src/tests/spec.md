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

Fast, fully offline test suite. Nothing here may touch the network or Gemini.

## Layout

| File | Covers |
|---|---|
| `conftest.py` | `snapshot` fixture (synthetic `MarketSnapshot` with quarterly statements and news), `fake_llm` / `failing_llm` (personas, sentiment, news digest), sample statements and Street data |
| `test_pipeline.py` | `predict()` end to end with the fake LLM, including multi-mode runs; packets; prompt changelog |
| `test_personas.py`, `test_confidence_score.py` | eligibility and aggregation |
| `test_evaluation.py` | baselines, log, scorer, stock splits, derived strategy weights |
| `test_llm.py` | `GeminiLLM` retries, backoff and give-up, against a fake genai client |
| `test_live.py` | websocket live quote: first tick, timeout, dropped connection, fallback |
| `test_cli.py` | `main.py`: argument errors, `--weights`, `--backtest`, rendering, predict + log |
| `test_api.py` | HTTP API with dependency overrides: `/predict`, validation, errors, `/score` |
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

## Commands

From `backend/src/`:

```
pytest                                   # everything, offline
pytest --cov --cov-report=term-missing   # with coverage (92% of non-test code at last count)
```
