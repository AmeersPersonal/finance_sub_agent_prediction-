# Hackknight 2026 — Market Moves

Educational market app for Hackknight 2026. The site explains what happened to a price, why it moved, and what a set of trader personas thinks might happen next. It has a **paper-trading** practice page with virtual cash, but it never places real trades, and it is not financial advice.

The repo has two apps that are merged on `main` and still run separately:

| App | Stack | What it does today |
|---|---|---|
| [`frontend/`](frontend/) | React 19, Vite, React Router, Tailwind 4 | Landing page, sign-in and sign-up screens, market dashboard, and a hypothetical scenarios page. The dashboard reads the backend API; scenarios use illustrative data. |
| [`backend/`](backend/) | Python 3.12, FastAPI, PostgreSQL, Gemini | Thirteen trader personas (strategy × age band) vote on a ticker over the next N trading days: **up**, **down**, **flat**, or **unclear**. Calls are stored beside naive baselines and a linear regression, then scored after the horizon passes. |

## Frontend

From `frontend/`:

```bash
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
npm test          # Vitest: dashboard, sign-in pages and API client against a fake backend
```

| Route | Page |
|---|---|
| `/` | Landing page (Money Moves) |
| `/Signin` | Sign-in with email and password (`POST /login`); goes to the dashboard once the backend accepts it. |
| `/Signup` | Create an account (`POST /signup`; the backend stores only a password hash), then sign in. |
| `/Dashboard` | Market Move Dashboard: story, chart, why it moved, the personas' forecast and votes, news, and watchlist, all from the backend API (start it first; `/api` is proxied to port 8000). Lazy-loaded. |
| `/scenarios` | Market Move Scenarios: move hypothetical factors and see an educational example. Not a forecast. |
| `/paper-trading` | Simulated buys and sells with $100,000 of virtual cash, filled at the latest saved daily close, with holdings, P&L and order history. Needs the backend (`/paper/*`) and a stock whose prices have been refreshed. No real money. |

Dashboard notes, including which API route feeds each panel, are in [`frontend/src/features/market-dashboard/README.md`](frontend/src/features/market-dashboard/README.md).

## Backend

AI agents imitate three strategies — long-term holders, day traders, and index/options traders — across age bands from 16 to 65 (13 personas). Each strategy sees a different packet of computed metrics, plus retrieved evidence (news excerpts, Hacker News threads, and optional SEC filings). Personas are averaged within a strategy so one strategy cannot outvote the others by having more people. **Flat** means the price is expected to stay inside a volatility band. **Unclear** means the personas disagree or lean only weakly.

Setup, the CLI, Docker, and environment variables are in [`backend/README.md`](backend/README.md). Shortest local path, from `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r src/requirements.txt
copy .env.example .env          # set GEMINI_API_KEY and DATABASE_URL; API_REQUIRE_SIGN_IN=false to run forecasts without signing in
```

From `backend/src/`:

```bash
python -m database.migrate      # creates the tables; run again after every pull (applies only what's new)
python main.py AAPL             # all 13 personas, 5-day horizon, logged to JSONL
python main.py AAPL --database  # same forecast, saved in PostgreSQL with retrieved evidence
python main.py --score          # accuracy vs baselines once horizons have passed
uvicorn api.main:app --reload   # HTTP API at http://127.0.0.1:8000  (docs at /docs)
```

Or, from `backend/` with `POSTGRES_PASSWORD` and `GEMINI_API_KEY` in `.env`:

```bash
docker compose up --build       # PostgreSQL + migrations + API on http://127.0.0.1:8000
```

Creating a forecast through the API requires Google sign-in unless `API_REQUIRE_SIGN_IN=false`. Reads do not. Paper trading (`/paper/*`) needs sign-in too, or `API_REQUIRE_SIGN_IN=false` for one local account per client address. Run `python -m database.migrate` first (migration 009), and point the frontend at the API with `VITE_API_BASE_URL` (default `http://localhost:8000`). A forecast usually takes 10–60 seconds; `POST /prediction-jobs` returns immediately and is polled with `GET /prediction-jobs/{job_id}`.


## More documentation

| Doc | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | For contributors and AI coding agents: what to run after pulling, how to run and test both apps, rules that span frontend and backend |
| [`frontend/README.md`](frontend/README.md) | Frontend layout, commands and tests |
| [`backend/src/spec.md`](backend/src/spec.md) | Backend layout and why it is split this way |
| [`backend/src/database/docs/README.md`](backend/src/database/docs/README.md) | Database guides (schema, local setup, Tiger Cloud) |
| [`backend/src/database/SETUP.md`](backend/src/database/SETUP.md) | Local PostgreSQL, migrations, API service |
| [`backend/src/sources/spec.md`](backend/src/sources/spec.md) | Which documents are collected |
| [`backend/src/ml/spec.md`](backend/src/ml/spec.md) | Learned price models and the stacker |

CI: `.github/workflows/backend.yml` runs the backend tests, including PostgreSQL, and builds the API image on pushes that touch `backend/`; `.github/workflows/frontend.yml` runs the frontend tests, lint and build on pushes that touch `frontend/`.
