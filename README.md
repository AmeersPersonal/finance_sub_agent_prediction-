# Hackknight 2026 — Market Moves

Educational market app for Hackknight 2026. The site explains what happened to a price, why it moved, and what a set of trader personas thinks might happen next. It does not place trades and it is not financial advice.

The repo has two apps that are merged on `main` and still run separately:

| App | Stack | What it does today |
|---|---|---|
| [`frontend/`](frontend/) | React 19, Vite, React Router, Tailwind 4 | Landing page, sign-in and sign-up screens, market dashboard, and a hypothetical scenarios page. Dashboard and scenarios use illustrative data. |
| [`backend/`](backend/) | Python 3.12, FastAPI, PostgreSQL, Gemini | Thirteen trader personas (strategy × age band) vote on a ticker over the next N trading days: **up**, **down**, **flat**, or **unclear**. Calls are stored beside naive baselines and a linear regression, then scored after the horizon passes. |

## Frontend

From `frontend/`:

```bash
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
```

| Route | Page |
|---|---|
| `/` | Landing page (Money Moves) |
| `/Signin` | Sign-in screen. The form posts to a placeholder `/api/login`, then navigates to `/dashboard`. |
| `/Signup` | Sign-up screen. The form posts to a placeholder `/api/signup`, then navigates to `/signin`. |
| `/Dashboard` | Market Move Dashboard: story, chart, why it moved, forecast, calendar, news, and watchlist. Lazy-loaded. Data is mock, including the live-tick demo. |
| `/scenarios` | Market Move Scenarios: move hypothetical factors and see an educational example. Not a forecast. |

Dashboard notes, including how to swap the mock fetchers for real API calls, are in [`frontend/src/features/market-dashboard/README.md`](frontend/src/features/market-dashboard/README.md).

## Backend

AI agents imitate three strategies — long-term holders, day traders, and index/options traders — across age bands from 16 to 65 (13 personas). Each strategy sees a different packet of computed metrics, plus retrieved evidence (news excerpts, Hacker News threads, and optional SEC filings). Personas are averaged within a strategy so one strategy cannot outvote the others by having more people. **Flat** means the price is expected to stay inside a volatility band. **Unclear** means the personas disagree or lean only weakly.

Setup, the CLI, Docker, and environment variables are in [`backend/README.md`](backend/README.md). Shortest local path, from `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r src/requirements.txt
copy .env.example .env          # set GEMINI_API_KEY; set API_REQUIRE_SIGN_IN=false for local API use without Google OAuth
```

From `backend/src/`:

```bash
python main.py AAPL             # all 13 personas, 5-day horizon, logged to JSONL
python main.py AAPL --database  # same forecast, saved in PostgreSQL with retrieved evidence
python main.py --score          # accuracy vs baselines once horizons have passed
uvicorn api.main:app --reload   # HTTP API at http://127.0.0.1:8000  (docs at /docs)
```

Or, from `backend/` with `POSTGRES_PASSWORD` and `GEMINI_API_KEY` in `.env`:

```bash
docker compose up --build       # PostgreSQL + migrations + API on http://127.0.0.1:8000
```

Creating a forecast through the API requires Google sign-in unless `API_REQUIRE_SIGN_IN=false`. Reads do not. A forecast usually takes 10–60 seconds; `POST /prediction-jobs` returns immediately and is polled with `GET /prediction-jobs/{job_id}`.


## More documentation

| Doc | What it covers |
|---|---|
| [`backend/src/spec.md`](backend/src/spec.md) | Backend layout and why it is split this way |
| [`backend/src/database/docs/README.md`](backend/src/database/docs/README.md) | Database guides (schema, local setup, Tiger Cloud) |
| [`backend/src/database/SETUP.md`](backend/src/database/SETUP.md) | Local PostgreSQL, migrations, API service |
| [`backend/src/sources/spec.md`](backend/src/sources/spec.md) | Which documents are collected |
| [`backend/src/ml/spec.md`](backend/src/ml/spec.md) | Learned price models and the stacker |

CI (`.github/workflows/backend.yml`) runs the backend tests, including PostgreSQL, and builds the API image on pushes that touch `backend/`.
