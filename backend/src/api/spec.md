# spec: backend/src/api/

## TODOS

- [ ] Connect the Frontend branch to these routes (see "For the frontend team"). Frontend work, not this folder's.
- [x] Creating forecasts requires a signed-in user (`prediction_caller`; `API_REQUIRE_SIGN_IN=false` turns it off for local development) and is rate-limited per caller (`API_PREDICTIONS_PER_HOUR`, default 10; a 429 with `Retry-After`).
- [x] Background forecasts: `POST /prediction-jobs` returns a job id at once; poll `GET /prediction-jobs/{job_id}`. `POST /predictions` still holds the request open.
- [x] `GET /score` and `/score/charts` share a cached report (`API_SCORE_CACHE_SECONDS`, default 300); `?refresh=true` recomputes, and `POST /predictions/{id}/evaluate` clears it.
- [x] Account preferences behind sign-in: `GET`, `PUT` and `DELETE /me/preferences`, keyed by the provider's subject id.
- [ ] Rate limits, jobs and the score cache are per process (`state.py`), so the API runs as one worker. Move them to PostgreSQL before running several workers; sign-in sessions already can be (`OAUTH_SESSION_STORE=database`).

## Purpose

The one HTTP API: database-backed forecasts and dashboard reads, plus OAuth
sign-in. Every forecast goes through `database.service.predict_and_store`, so
it is stored with its market data, retrieved evidence and learning context.
There is no JSONL path in the API; the CLI keeps that for offline use.

Run from `backend/src`:

```bash
../.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The backend loads its private `backend/.env`. `DATABASE_URL` is required for
database operations and `GEMINI_API_KEY` for predictions; `OAUTH_*` enables
sign-in. No credentials go to the browser. Interactive route documentation:
<http://127.0.0.1:8000/docs>.

| File | Role |
| --- | --- |
| `main.py` | The FastAPI app: routes, request models, sign-in and quota checks |
| `state.py` | In-process state: the per-caller rate limiter, background prediction jobs, the score cache |

## Routes

| Route | Purpose |
| --- | --- |
| `GET /health` | Verify a database connection |
| `GET /stocks/{ticker}/history?interval=1d&limit=500` | Saved price bars; `1d` or `5m` |
| `GET /stocks/{ticker}/news?limit=20` | Latest saved document versions, excerpt previews, and source metadata |
| `POST /stocks/{ticker}/refresh` | Fetch/store prices, company data, and available documents; no Gemini calls |
| `POST /predictions` | Generate and store a forecast (options below). Signed-in, rate-limited |
| `POST /prediction-jobs` | The same, in the background: 202 with `job_id` and `poll` |
| `GET /prediction-jobs/{job_id}` | `status` queued, running, succeeded (with `prediction`) or failed (with `error`); the creator only, kept an hour |
| `GET /predictions?ticker=AAPL&limit=20` | Most recent saved forecasts |
| `GET /predictions/{id}` | One saved forecast |
| `GET /predictions/{id}/evaluation` | Saved evaluations, or `"status": "pending"` (no price fetch) |
| `POST /predictions/{id}/evaluate` | Fetch closes and score it if its horizon has passed; when still pending, says why (`pending_reason`, `pending_detail`, `retry_after`) |
| `GET /score?refresh=false` | Accuracy of all saved forecasts vs the baselines, by strategy, age band, mode, model, strength and stability; accuracy relative to SPY (`relative`); suggested strategy weights; why each pending forecast waits. Appends newly available outcomes (idempotent). Cached; `computed_at` says when |
| `GET /stocks/{ticker}/charts?interval=1d&limit=250` | Chart-ready series from saved bars: candles + SMA, volume, RSI, MACD, drawdown (`charts/spec.md`) |
| `GET /stocks/{ticker}/charts/backtest?horizon_days=5` | Regression equity curve vs buy and hold and return per period; empty `charts` with under ~1.5 years of saved daily bars |
| `GET /predictions/{id}/charts` | Chart-ready series for one forecast: votes, conviction, strategy scores, flat band, baselines |
| `GET /score/charts` | `/score` as chart-ready series, plus rolling accuracy over time (same price fetch and append as `/score`) |
| `GET /oauth/login`, `/oauth/callback`, `/oauth/me`, `POST /oauth/logout` | Google sign-in (code + PKCE), session cookie (`oauth/spec.md`) |
| `GET`, `PUT`, `DELETE /me/preferences` | The signed-in user's age band, strategy, experience level and up to 4 KB of UI settings; always needs sign-in |

Prediction request (only `ticker` is required):

```json
{
  "ticker": "AAPL",
  "horizon_days": 5,
  "strategies": ["long_term", "day_trader"],
  "age_bands": ["18-24", "25-39"],
  "strategy_weights": {"long_term": 2, "day_trader": 0.5},
  "modes": "default",
  "live": false,
  "audit": false
}
```

- Horizons are 1-252 trading days. Strategies are `long_term`, `day_trader`,
  `index_options`. Age bands are the adult bands `18-24`, `25-39`, `40-54`,
  `55-65` (the 16-17 band is CLI-only). Defaults: all strategies, all adult bands.
- `strategy_weights`: per-strategy weights (missing ones weigh 1), or `"auto"`
  to derive them from saved persona evaluations.
- `modes`: a preset (`default`, `temps`, `models`, `full`, and `providers` when a
  second LLM provider is configured) or comma-separated mode names; each mode
  runs every persona again (more model calls).
- `live`: take the last price from the live feed (`LIVE_FEED`: Yahoo's websocket
  by default, or Finnhub); falls back to the REST quote with a warning.
- `audit`: add a company overview, data checks, risk flags and a news digest
  (one extra Gemini call) in `Prediction.audit`.

Confidence is signal strength, not a calibrated probability. Empty history/news
means no records have been saved; it does not imply an upstream fetch occurred.

Errors: invalid input is a 422 (including unknown tickers and option
combinations with no eligible personas, with a readable `detail`); creating a
forecast without signing in is a 401 and over the hourly limit a 429 with
`Retry-After`; a missing `GEMINI_API_KEY` or live-feed setting is a 503;
database failures a sanitized 503; upstream market or model failures a
sanitized 502; unknown forecasts or jobs a 404. Rejected requests (401, 422,
503) don't count against the limit. Database operations run
in worker threads; transactions are not held open while awaiting external
services.

## Forecast response and provenance

`Prediction` includes the aggregate call, persona rationales (one per persona
per mode, with `mode`, `model` and `temperature`), `by_mode` and `stability`,
a separate regression result, numerical/headline input packets, warnings,
`sources`, `learning` and, when requested, `audit`. Each source has a `role`
(`company_info`, `public_opinion`, `product_event`). Persona `source_ids`
contain only IDs from provided passages. Each source lists strategies that
received it and personas that cited it. Inclusion is not independent
verification that a source supports every claim.

## For the frontend team

The `Frontend` branch doesn't call the API yet. These decisions were made when
the database and backend branches were merged (2026-10-10); build against them,
and tell your coding agent to read this section:

- **One API, `api.main:app`, on port 8000.** The backend branch's `api/app.py`
  (`POST /predict`, `GET /score` over a JSONL file) was folded into it and
  removed. There is no `POST /predict` alias: create forecasts with
  `POST /predictions` (201 Created). Every forecast is saved, so lists and
  detail pages read the same records.
- **Base URL** in development: `http://localhost:8000`. Allowed browser origins
  default to `http://localhost:5173` (Vite) and `http://localhost:3000`; set
  `API_CORS_ORIGINS` on the backend to change them. CORS allows credentials, so
  send `credentials: "include"` on requests that need the sign-in cookie. A
  Vite dev proxy (`/api` -> `http://localhost:8000`) also works and avoids CORS.
- **Sign-in**: send the browser to `GET /oauth/login`; after Google it returns to
  `OAUTH_POST_LOGIN_REDIRECT` (set it to the frontend's page). `GET /oauth/me`
  returns the user or 401. Creating forecasts needs sign-in (send
  `credentials: "include"`); on a 401, send the user to sign in. Reads don't.
  For local work without OAuth, the backend sets `API_REQUIRE_SIGN_IN=false`.
- **Slow requests**: a forecast takes 10-60 s (more with modes). Prefer
  `POST /prediction-jobs` and poll `GET /prediction-jobs/{job_id}` every few
  seconds until `status` is `succeeded` or `failed`; show progress and don't
  retry automatically. On a 429, show the `detail` and wait `Retry-After`
  seconds. Prefer `modes: "default"` in the UI unless the user opts in.
- **Preferences**: `GET /me/preferences` returns `null` until the user saves
  some with `PUT` (`age_band`, `strategy`, `experience_level`, `preferences`);
  `DELETE` forgets them. They aren't a suitability assessment.
- **Pending outcomes**: show `pending_detail` from `POST /predictions/{id}/evaluate`
  (or `pending_details[].detail` from `GET /score`) as-is; it explains holidays,
  early closes and data gaps in plain words.
- **Charts**: the `/charts` routes return data, not images, all in one
  shape (`id`, `title`, `kind`, `x`, `series`, `y_label`, `reference_lines`,
  `caption`; see `charts/base.py`). Write one renderer and loop over
  `charts`; show `caption` under each chart. Series `data` aligns with `x`,
  `null` means no value, candlestick points are `[open, high, low, close]`, and
  the `persona_conviction` series carries a parallel `group` (strategy) list.
  A reference line with `"axis": "x"` is vertical (the volume profile's price
  levels); others are horizontal. `interval=5m` adds a VWAP series to `price`
  and a `volume_profile` chart.
- **Wording**: present confidence as "signal strength", never as a probability;
  "flat" (expected to stay in the band) differs from "unclear" (no call).
- Field names are stable; new fields may be added. Don't parse `detail`
  messages for logic, only display them.

## Operations

The API service is enabled on this development computer as
`hack-knight-api.service`. Its generated unit is gitignored; teammates start
Uvicorn using the command above, or `docker compose up --build` from `backend/`
(PostgreSQL, migrations and the API; see `backend/README.md`). Restart the
service after environment changes.

Run one worker: rate limits, prediction jobs and the score cache live in this
process (`state.py`), and a restart forgets running jobs. Sign-in, quotas and
background jobs are in place; before a public deployment, also put it behind
HTTPS, use the least-privilege `finance_api` database role
(`database/roles.sql`), and set `API_CORS_ORIGINS` to the real frontend.
