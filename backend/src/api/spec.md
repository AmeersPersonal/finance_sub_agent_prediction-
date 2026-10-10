# spec: backend/src/api/

## TODOS

- [ ] Connect the Frontend branch to these routes (see "For the frontend team").
- [ ] Require `oauth.routes.current_user` on `POST /predictions` before exposing the API publicly (each call spends Gemini quota), then rate-limit per user.
- [ ] `POST /predictions` holds the request open for the whole run (10-60 s on the free tier, longer with several modes). If the frontend needs it, return a job id and poll instead.
- [ ] `GET /score` refetches closes for every saved ticker on each call; cache the report for a few minutes if it gets called often.
- [ ] Add authenticated accounts before exposing user preferences.

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

## Routes

| Route | Purpose |
| --- | --- |
| `GET /health` | Verify a database connection |
| `GET /stocks/{ticker}/history?interval=1d&limit=500` | Saved price bars; `1d` or `5m` |
| `GET /stocks/{ticker}/news?limit=20` | Latest saved document versions, excerpt previews, and source metadata |
| `POST /stocks/{ticker}/refresh` | Fetch/store prices, company data, and available documents; no Gemini calls |
| `POST /predictions` | Generate and store a forecast (options below) |
| `GET /predictions?ticker=AAPL&limit=20` | Most recent saved forecasts |
| `GET /predictions/{id}` | One saved forecast |
| `GET /predictions/{id}/evaluation` | Saved evaluations, or `"status": "pending"` (no price fetch) |
| `POST /predictions/{id}/evaluate` | Fetch closes and score it if its horizon has passed; when still pending, says why (`pending_reason`, `pending_detail`, `retry_after`) |
| `GET /score` | Accuracy of all saved forecasts vs the baselines, by strategy, age band, mode and model; suggested strategy weights; why each pending forecast waits. Appends newly available outcomes (idempotent) |
| `GET /oauth/login`, `/oauth/callback`, `/oauth/me`, `POST /oauth/logout` | Google sign-in (code + PKCE), session cookie (`oauth/spec.md`) |

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
- `modes`: a preset (`default`, `temps`, `models`, `full`) or comma-separated
  mode names; each mode runs every persona again (more Gemini calls).
- `live`: take the last price from Yahoo's websocket (falls back with a warning).
- `audit`: add a company overview, data checks, risk flags and a news digest
  (one extra Gemini call) in `Prediction.audit`.

Confidence is signal strength, not a calibrated probability. Empty history/news
means no records have been saved; it does not imply an upstream fetch occurred.

Errors: invalid input is a 422 (including unknown tickers and option
combinations with no eligible personas, with a readable `detail`); a missing
`GEMINI_API_KEY` is a 503; database failures a sanitized 503; upstream market or
model failures a sanitized 502; unknown forecasts a 404. Database operations run
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
  returns the user or 401. Forecast routes don't require sign-in yet.
- **Slow requests**: a forecast takes 10-60 s (more with modes); show progress
  and don't retry automatically. Prefer `modes: "default"` in the UI unless the
  user opts in.
- **Pending outcomes**: show `pending_detail` from `POST /predictions/{id}/evaluate`
  (or `pending_details[].detail` from `GET /score`) as-is; it explains holidays,
  early closes and data gaps in plain words.
- **Wording**: present confidence as "signal strength", never as a probability;
  "flat" (expected to stay in the band) differs from "unclear" (no call).
- Field names are stable; new fields may be added. Don't parse `detail`
  messages for logic, only display them.

## Operations

The API service is enabled on this development computer as
`hack-knight-api.service`. Its generated unit is gitignored; teammates start
Uvicorn using the command above. Restart the service after environment changes.
Keep it bound to loopback: add authentication, authorization, quotas and
background jobs before any public deployment.
