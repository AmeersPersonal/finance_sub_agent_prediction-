# AGENTS.md: Hackknight 2026 Market Moves

Guidance for AI coding agents (Codex, Claude Code, Cursor and others) working anywhere
in this repo. `CLAUDE.md` imports this file. Backend-specific rules are in
[`backend/src/CLAUDE.md`](backend/src/CLAUDE.md); read it before changing anything
under `backend/`.

## Repo map

| Path | What it is |
|---|---|
| `frontend/` | React 19 + Vite app: landing, sign-in/sign-up, the market dashboard (`src/features/market-dashboard`), scenarios |
| `backend/` | Python 3.12 FastAPI app (`backend/src/api/main.py`), AI trader personas, PostgreSQL storage, optional Snowflake retrieval |
| `template.yaml`, `deploy/aws/` | AWS deployment: SAM template (API as a container-image Lambda, frontend on S3 + CloudFront) and the build/deploy scripts; see `deploy/aws/README.md` |
| `.github/workflows/` | CI: `backend.yml` (pytest incl. PostgreSQL, Docker image), `frontend.yml` (Vitest, eslint, build) |

Every folder under `backend/src/` has a `spec.md` (TODOs, purpose, files, rules). Keep
them current when you change a folder.

## After pulling new code

Run these before using or testing the new code. They are safe to repeat.

```bash
# from backend/ (inside its virtualenv)
pip install -r src/requirements.txt
# from backend/src/ — applies only migrations this database hasn't had yet
python -m database.migrate
# from frontend/
npm install
```

`python -m database.migrate` changes the database `DATABASE_URL` points at, and each
database (the team's Tiger Cloud service, a local PostgreSQL) needs it once. It creates
tables, it never copies data. On a shared database, re-run `database/roles.sql` after a
new migration (`backend/src/database/docs/retention-and-access.md`).

## Running it

1. **Backend API** (port 8000), from `backend/src/`: `uvicorn api.main:app --reload`.
   It reads `backend/.env` (names in `backend/.env.example`): `DATABASE_URL`,
   `GEMINI_API_KEY`, `API_REQUIRE_SIGN_IN=false` to run forecasts without signing in,
   and optionally `RAG_BACKEND=snowflake` with the `SNOWFLAKE_*` settings.
2. **Frontend** (port 5173), from `frontend/`: `npm run dev`, then open
   http://localhost:5173/Dashboard. The dev server proxies `/api/*` to the API
   (`frontend/vite.config.js`; `API_TARGET` points it elsewhere), so there is no CORS setup.

The team database is a Tiger Cloud (PostgreSQL + TimescaleDB) service with an IP allow
list. Campus Wi-Fi silently drops PostgreSQL traffic to it (`timeout expired`); use
another network such as a phone hotspot, and allow-list your public IP. Never commit
hostnames, IPs or credentials; `backend/src/database/docs/tiger-cloud-migration.md`
explains how to connect.

## Tests

| What | Command | Notes |
|---|---|---|
| Backend | `pytest` from `backend/src/` | Offline. PostgreSQL tests run only with `TEST_DATABASE_URL` pointing at a local Unix-socket database (`backend/src/tests/spec.md`); CI runs them |
| Frontend | `npm test` from `frontend/` | Vitest + jsdom, a few seconds, no backend: `src/test/fakeBackend.js` answers `/api` |
| Frontend lint | `npx eslint src/features src/lib src/test src/pages/auth-pages.test.jsx vite.config.js` | What CI lints. `npm run lint` still fails on the unrendered `LearningMode` and `Honesty` sections in `src/pages/Landing.jsx` |
| Frontend build | `npm run build` | |

Run the tests for whichever side you changed, and both sides if you touched the API.

## Rules that cross the frontend/backend line

- **The API is a contract.** The dashboard and sign-in pages read specific fields
  (`backend/src/api/spec.md`, "For the frontend team"). If you rename, remove or retype
  one, update the frontend, its fake backend (`frontend/src/test/fakeBackend.js`) and
  `backend/src/tests/test_frontend_contract.py` in the same change. That test fails when
  the backend drifts.
- **The ticker rule exists twice**: `normalize_ticker` in `backend/src/database/service.py`
  and `TICKER_PATTERN` in `frontend/src/features/market-dashboard/lib/assets.js`. The
  contract test compares them; change both.
- **Confidence is "signal strength", never a probability**, and "flat" (expected to stay
  in the band) is not "unclear" (no call). Keep the UI wording consistent with the backend.
- **Schema changes are new numbered files** in `backend/src/database/migrations/`. Never
  edit an applied migration (they're checksummed), and add new ones to `CORE_MIGRATIONS`
  in `backend/src/tests/test_database.py`.
- **Sign-in** is email/password (`POST /signup`, `POST /login`, `backend/src/api/accounts.py`)
  or Google (`/oauth/*`). Both create the same HttpOnly session cookie; the frontend
  calls them through `frontend/src/lib/auth.js` with `credentials: 'include'`.
  Sessions live in API memory unless `OAUTH_SESSION_STORE=database`.

## Secrets and data

- Never read, print, log or commit `.env` files, database passwords, API keys or the
  Snowflake private key. Refer to settings by variable name.
- `node_modules/`, `dist/`, `backend/data/` and `.env` are gitignored; don't force-add them.
- Prices are saved from Yahoo Finance and refreshed on demand (`POST /stocks/{ticker}/refresh`);
  there is no live feed. After bulk refreshes, `python -m snowflake_rag sync` indexes
  the new passages for Snowflake retrieval.

## Known gaps

- Two landing-page sections (`LearningMode`, `Honesty`) are written but not rendered.
- No password reset or email verification; the Scenarios page uses illustrative data.
