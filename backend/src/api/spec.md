# spec: backend/src/api/

## TODOS

- [ ] Require `oauth.routes.current_user` on `POST /predict` before exposing the API publicly (each call spends Gemini quota), then rate-limit per user.
- [ ] `POST /predict` holds the request open for the whole run (10-60 s on the free tier). If a frontend needs it, return a job id and poll instead.
- [ ] `GET /score` refetches closes for every logged ticker on each call; cache the report for a few minutes if it gets called often.

## Purpose

The CLI's prediction pipeline over HTTP, plus the OAuth sign-in routes.

```
uvicorn api.app:app --reload        # from backend/src; interactive docs at /docs
```

## Files

| File | Role |
|---|---|
| `app.py` | FastAPI app. `POST /predict` (same options as the CLI: horizon, strategies, age bands, weights or `"auto"`, modes, `live`, `audit`, `log`), `GET /score` (the `--score` report without per-outcome detail), `GET /health`; mounts `oauth/` routes |

## Design rules

- Same pipeline as `main.py`: fetch the snapshot, `predict()`, optional
  `audit_prediction()`, append to the same log. Don't fork the logic.
- The LLM, the snapshot fetcher and the log path are FastAPI dependencies
  (`get_llm`, `get_fetcher`, `get_log_path`); tests override them, so no test
  touches the network or Gemini.
- One shared `GeminiLLM`, so its concurrency cap and backoff cover all requests.
- Bad input (ticker format, unknown strategy, age band or mode, no eligible
  personas, unknown ticker) is a 422; every persona failing is a 502; a missing
  `GEMINI_API_KEY` is a 503.
- `.env` is loaded at startup (lifespan), not at import, so importing the app in
  tests doesn't read it.
## Purpose

Local FastAPI interface over database storage and the existing prediction engine.
Prices and source metadata are read from saved records. Refreshing market data and
creating predictions explicitly request upstream services. These operations may
take time; a prediction request completes after its result has been saved.

Run from `backend/src`:

```bash
../.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The backend loads its private `backend/.env`. `DATABASE_URL` is required for
database operations and `GEMINI_API_KEY` for predictions. No credentials go to
the browser. Interactive route documentation: <http://127.0.0.1:8000/docs>.

| Route | Purpose |
| --- | --- |
| `GET /health` | Verify a database connection |
| `GET /stocks/{ticker}/history?interval=1d&limit=500` | Saved price bars; `1d` or `5m` |
| `GET /stocks/{ticker}/news?limit=20` | Latest saved document versions, excerpt previews, and source metadata |
| `POST /stocks/{ticker}/refresh` | Fetch/store prices, company data, and available documents; no Gemini calls |
| `POST /predictions` | Generate and store an agent/regression forecast |
| `GET /predictions?ticker=AAPL&limit=20` | Most recent saved forecasts |
| `GET /predictions/{id}` | One saved forecast |
| `GET /predictions/{id}/evaluation` | Saved evaluations or pending status |
| `POST /predictions/{id}/evaluate` | Check outcome if enough price history exists |

Example prediction request:

```json
{"ticker":"AAPL","horizon_days":5,"strategies":["long_term"],"age_bands":["18-24"]}
```

Horizons are 1–252 trading days. Strategies are `long_term`, `day_trader`, and
`index_options`. Adult age bands are `18-24`, `25-39`, `40-54`, and `55-65`.
The default includes all strategies and all adult bands. Confidence is signal
strength, not a calibrated probability. Empty history/news means no records
have been saved; it does not imply an upstream fetch occurred.

Database failures return a sanitized 503, upstream failures a sanitized 502,
unknown forecasts a 404, and invalid input a 422. Missing outcomes stay pending.
Database operations run in worker threads; transactions are not held open while
awaiting external services.

This demo has no authentication: bind only to loopback. Browser CORS origins
default to `http://localhost:5173` and `http://localhost:3000`; configure the
comma-separated `API_CORS_ORIGINS` environment variable if needed. CORS is not
authentication. User-preference tables are not exposed. Add authentication,
authorization, quotas, and background jobs before any public deployment.


## Forecast response and provenance

`Prediction` includes the aggregate call, persona rationales, a separate
regression result, numerical/headline input packets, warnings, `sources`, and
`learning`. Persona `source_ids` contain only IDs from provided passages. Each
source lists strategies that received it and personas that cited it. Inclusion
is not independent verification that a source supports every claim.

The API service is enabled on this development computer as
`hack-knight-api.service`. Its generated unit is gitignored; teammates start
Uvicorn using the command above. Restart the service after environment changes.

## Remaining work

- [ ] Connect the Frontend branch to these routes.
- [ ] Add authenticated accounts before exposing user preferences.
- [ ] Introduce background jobs if forecast requests become too slow.
