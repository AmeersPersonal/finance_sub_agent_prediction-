# CLAUDE.md: Backend

Guidance for AI coding agents working in `backend/` (the Python backend of the
finance sub-agent prediction project). Repo-wide steps (after pulling, running both
apps, tests, the frontend/backend API contract) are in the root `AGENTS.md`.

## What it does

AI agents imitate trader personas and their views are combined into one stock
call over N trading days: **up / down / flat / unclear**, with a signal
strength (not a calibrated probability). Every call is logged next to naive
baselines and a linear regression, and scored once its horizon passes.

- **Flat band** = 0.25 × trailing-1y daily volatility × √N, so about 1 outcome
  in 5 counts as flat for any stock (a fixed ±1% was flat 38% of the time for
  SPY but 10% for TSLA). Personas, the regression and the scorer all use it.
- **flat ≠ unclear.** "flat" means personas expect the price to stay inside the
  band; "unclear" means they split or lean only weakly. Don't merge them.
- **Reasoning modes** (`ai/modes.py`) run every persona under several
  model/temperature settings. They are collapsed per persona before the strategy
  average, so extra samples add evidence, not weight. The default is one mode
  (`default`); keep it logged as the control.
- **Each strategy gets one vote.** Personas are averaged within a strategy
  first, so long_term's extra 16–17 persona doesn't give it more weight.
- **Earnings inside the horizon** are flagged to every persona (yfinance calendar).

Personas are **strategy × age band** (16–65):

| Strategy | Sees | Age bands |
|---|---|---|
| `long_term` | 5y CAGR, drawdown, valuation; margins, FCF yield, ROIC, leverage, EV/EBITDA, PEG; Altman Z, Beneish M; 10-Q review and EPS surprises; insiders (Form 4), institutions (13F), analyst estimates and targets; Treasury yields; filings | 16–17, 18–24, 25–39, 40–54, 55–65 |
| `day_trader` | Latest session: VWAP, RSI, gap, range; MACD, ATR, 5-session volume profile, live bid-ask spread, volume vs average; recent returns; analyst rating changes; headlines + sentiment score | 18–24, 25–39, 40–54, 55–65 |
| `index_options` | Beta and relative strength vs S&P 500, sector ETF and Nasdaq-100; VIX; put/call ratios, ATM IV vs realized vol; short interest and its change; yields, CPI, unemployment, payrolls; headlines + sentiment score | 18–24, 25–39, 40–54, 55–65 |

Deliberately not included (no free source): order-book depth / order flow
(needs a paid Level 2 feed), social-media sentiment (Reddit's Responsible
Builder Policy requires approval and bars sharing its data, e.g. with Gemini;
Hacker News threads are evidence passages, not a score), IV rank (needs IV
history), GDP and the 2-year yield (FRED needs a key; its keyless CSV endpoint
timed out from this network).

16–17-year-olds are long-term only: custodial/youth accounts are cash-only, so
no shorting, options or practical day trading. That's 13 personas in total.

## Layout and data flow

```
backend/
├── README.md                 # setup and run commands
├── .env                      # real secrets, gitignored
├── .env.example              # variable names only, committed
├── data/                     # gitignored
│   ├── predictions.jsonl     # prediction log, kept forever (it's the scoring record)
│   └── cache/bls_<date>.json # BLS allows 25 keyless requests/day, so it's cached daily; kept 7 days
└── src/
    ├── main.py               # CLI: predict + log, --score, --backtest; --weights, --live, --audit
    ├── requirements.txt      # direct dependencies, pinned
    ├── requirements.lock     # every dependency, pinned with hashes (uv pip compile --universal)
    ├── api/
    │   ├── main.py           # the one FastAPI app: forecasts (sign-in, rate limit, jobs), reads, /score, /me
    │   ├── state.py          # in-process rate limiter, prediction jobs, score cache (run one worker)
    │   ├── lambda_jobs.py    # JOBS_BACKEND=lambda: PostgreSQL-backed jobs, signed worker events (AWS Lambda)
    │   └── accounts.py       # POST /signup, /login: email/password accounts, same session as Google
    ├── ai/
    │   ├── main.py           # predict(): fetch -> live quote? -> sentiment -> personas -> aggregate
    │   ├── tool.py           # parallel fetching -> MarketSnapshot; clean_daily repairs Yahoo's last bar
    │   ├── live.py           # live quote (Yahoo websocket, or Finnhub with LIVE_FEED) on the MarketSnapshot
    │   ├── feeds.py          # Yahoo Finance RSS news (with links), BLS inflation/jobs (cached)
    │   ├── sentiment.py      # one Gemini call scoring headlines -1..+1
    │   ├── agents.py         # horizon info, per-strategy packet, prompt; PROMPT_VERSION + changelog
    │   ├── personas.py       # strategies, age bands, eligibility rules
    │   ├── modes.py          # reasoning modes: model + temperature presets
    │   ├── llm.py            # Gemini + an OpenAI-compatible second provider; build_llm (only file that talks to providers)
    │   ├── confidence_score.py  # strategy-balanced vote -> up/down/flat/unclear + strength
    │   ├── evaluation.py     # baselines, prediction log, split-aware scorer, derived weights
    │   ├── rag_retrieval.py  # keyword retrieval over ai/docs/ (.md/.txt)
    │   ├── features.py       # flattens the packets into Prediction.features (stacker training rows)
    │   ├── schemas.py        # PersonaView, PersonaResult, Prediction
    │   └── docs/             # private documents, contents gitignored
    │       └── age_profiles/<band>.md   # optional sourced profile, overrides personas.py text
    ├── audit/                # explains a prediction: no new math
    │   ├── analysis.py       # audit_prediction() (--audit): the entry point, one LLM call
    │   ├── info.py           # company overview, data checks
    │   ├── risk.py           # decision risk checklist; learning_context for the dashboard
    │   └── media.py          # news TL;DRs (links from the feed, never the model); source_digest
    ├── charts/               # chart-ready JSON for the frontend (price, forecast, score); pure
    │   ├── base.py           # the one chart shape, JSON-safe numbers
    │   ├── price.py          # candles + SMA, volume, RSI, MACD, drawdown; 5m: VWAP, volume profile
    │   ├── prediction.py     # votes, conviction, strategy scores, flat band, baselines
    │   ├── backtest.py       # regression equity curve vs buy and hold
    │   └── score.py          # accuracy vs baselines, over time, by strategy/age/mode/strength
    ├── finance/
    │   ├── indicators.py     # RSI, MACD, ATR, VWAP, volume profile, beta, options, flat band
    │   ├── linear_regression.py  # OLS on price features, walk-forward validated: the baseline
    │   ├── backtest.py       # strategy returns with costs; Sharpe, Sortino, max DD, profit factor
    │   ├── fundamentals.py   # margins, FCF, ROIC, leverage, valuation; Beneish M-score
    │   ├── risk_management.py  # Altman Z-score (annual, TTM); ATR stop and 1%-risk position size
    │   ├── quarter_review_analysis.py  # 10-Q growth, margin trend, EPS surprises
    │   ├── positioning.py    # insiders, institutions, short interest, analysts (point-in-time)
    │   ├── macro.py          # yield curve, CPI, unemployment, payrolls
    │   └── revenue_forecast.py  # revenue trend; naive extrapolation, labelled not a forecast
    ├── ml/                   # learned models, gated on walk-forward results (ml/spec.md); python -m ml
    │   ├── dataset.py        # rows labelled like the scorer: price rows (model A), scored personas (B)
    │   ├── model.py          # logistic, LightGBM, PyTorch MLP (CUDA if present), one interface
    │   ├── walkforward.py    # purged expanding-window evaluation, baselines, metrics, gates
    │   ├── calibration.py    # accuracy at coverage, strength -> probability, earnings split
    │   └── store.py          # save/load under data/models/ with a sidecar JSON
    ├── sources/              # Yahoo/Google News RSS, Hacker News, optional SEC filings + press releases
    ├── snowflake_rag/        # optional Snowflake vector index over stored chunks (RAG_BACKEND=snowflake)
    ├── database/             # migrations, repository, orchestration, backup.py, roles.sql, setup/docs
    ├── oauth/                # Google OIDC sign-in (code + PKCE), email/password accounts; sessions in memory or PostgreSQL
    └── tests/                # offline: synthetic snapshot + fake LLM, fake OAuth provider
```

## Commands

From `backend/`:

```
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate elsewhere)
pip install -r src/requirements.txt  # or: pip install --require-hashes -r src/requirements.lock
pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu130 --force-reinstall --no-deps  # GPU build
copy .env.example .env            # then set GEMINI_API_KEY
```

From `backend/src/`:

```
python main.py AAPL                                   # all 13 personas, 5-day horizon, logged
python main.py AAPL MSFT NVDA --horizon 1             # several tickers
python main.py AAPL --strategy day_trader --age 18-24 # subset (faster on the free tier)
python main.py AAPL --modes temps                     # each persona at 3 temperatures
python main.py AAPL --modes models                    # default + GEMINI_MODEL_STRONG
python main.py AAPL --weights long_term=2,day_trader=0.5   # or --weights auto (from --score)
python main.py AAPL --live --audit                    # websocket price; checks, risk, news digest
python main.py AAPL --json --no-log
python main.py --score                                # accuracy vs baselines, once horizons pass
python main.py SPY --backtest [--features a,b,c]      # regression walk-forward only, no LLM
python -m ml price [--target relative]                # model A walk-forward + gate (ml/spec.md)
python -m ml stacker                                  # model B; needs ~300 scored predictions
python -m ml coverage                                 # accuracy at coverage, strength calibration
python -m database.migrate                            # after pulling: applies only new migrations
uvicorn api.main:app --reload                         # HTTP API (database-backed), docs at /docs
python -m snowflake_rag sync                          # index new passages for RAG_BACKEND=snowflake
python -m database.backup                             # pg_dump + retention schedule (database/docs/retention-and-access.md)
pytest                                                # offline
pytest --cov --cov-report=term-missing                # with coverage
```

Environment variables: `GEMINI_API_KEY` (required for real predictions),
`GEMINI_MODEL` (optional, default `gemini-3.5-flash-lite`), `GEMINI_MODEL_STRONG`
(optional, used by the `strong` reasoning modes), `DATABASE_URL` for database
operations, optional `SEC_USER_AGENT` for SEC filings and 8-K press releases,
optional `API_CORS_ORIGINS` for local frontend development, and for API sign-in
`OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` plus the optional `OAUTH_*` settings in
`.env.example`. Forecast requests need sign-in unless `API_REQUIRE_SIGN_IN=false`;
`API_PREDICTIONS_PER_HOUR` and `API_SCORE_CACHE_SECONDS` tune the API.
Optional: `RAG_BACKEND=snowflake` with the `SNOWFLAKE_*` key-pair settings,
`ALT_LLM_BASE_URL` / `ALT_LLM_MODEL` / `ALT_LLM_API_KEY` (a second,
OpenAI-compatible model provider), `LIVE_FEED=finnhub` with `FINNHUB_API_KEY`,
`OAUTH_SESSION_STORE=database`, and `POSTGRES_PASSWORD` for Docker Compose. AWS Lambda
hosting (`Dockerfile.lambda`, `deploy/aws/`) sets `JOBS_BACKEND=lambda` and `JOB_SIGNING_KEY`
so forecast jobs live in PostgreSQL (`api/lambda_jobs.py`).

## Hard rules

- **Never read, print, log, or commit `.env` or any `.env.*`** (only
  `.env.example` is allowed in git, and it holds variable names only). Refer to
  secrets by variable name and load them from the environment. Never hardcode
  keys, tokens, or client secrets.
- **Never commit documents.** `src/ai/docs/` holds private source documents.
  Do not copy their contents into code, tests, fixtures, logs, or commit
  messages.
- **OAuth credentials and tokens stay out of git.** Anything credential-like
  under `src/oauth/` (client secrets, `token.json`, keys) is gitignored. Keep
  it that way.
- **Do not weaken `.gitignore`.** Before committing, check `git status`; if a
  secret or document shows up as staged, stop and unstage it.
- **Tests never hit the network or Gemini.** Use the `snapshot` and `fake_llm`
  fixtures in `tests/conftest.py`; `predict()` takes `llm=`, `snapshot=` and
  `live_feed=`. API and OAuth tests override FastAPI dependencies.

## Conventions

- **Python computes numbers; the LLM interprets them.** Add new metrics to
  `finance/` and pass them in a strategy's packet in `agents.py`. Never send
  raw price rows to the model.
- **Each strategy gets different data.** Identical packets make personas echo
  each other, which turns the aggregator's disagreement measure into noise.
- **Missing data degrades, it doesn't crash.** Fetches record failures in
  `MarketSnapshot.errors`, and metrics that can't be computed become `null`.
  Personas are told to lower conviction when their data is missing.
- **Model calls go through `llm.py` only**: Gemini via `client.aio.models.generate_content`
  with `response_json_schema`, the second provider via the chat-completions
  `response_format`. Keep schemas simple; Gemini supports a subset of JSON
  Schema. Build clients with `build_llm()`, never `GeminiLLM()` directly.
- Dependencies live in `src/requirements.txt`, pinned with `==`. Regenerate
  `src/requirements.lock` whenever it changes (command in `backend/spec.md`).
- **Bump `PROMPT_VERSION` with a `PROMPT_CHANGELOG` entry** whenever prompts or
  packets change; a test fails if the current version has no entry.
- `snake_case` module names, spelled correctly. Earlier typos were fixed in
  `requirements.txt`, `rag_retrieval.py`, `finance/` and `revenue_forecast.py`;
  do not reintroduce them.
- Tests live in `tests/test_*.py`. Never name a module `pytest.py`.
- **Keep every folder's `spec.md` current.** Each folder under `backend/` has a
  `spec.md` (TODOS first, then purpose, layout, design rules). Whenever you
  create, rename, move or delete a file or folder, update the `spec.md` of the
  folder it lives in in the same change:
  - New file: add a row to that folder's Files/Layout table.
  - New folder: create its `spec.md` (TODOS, Purpose, Files, Design rules) and
    add the folder to the parent `spec.md` layout.
  - Finished a TODO or added follow-up work: tick or add it under TODOS.
  - Skip folders whose contents are gitignored (`data/`, `ai/docs/`).

## Known data limits (yfinance)

- Free and unofficial: quotes are near-real-time at best, and Yahoo rate-limits.
  `--live` takes the first tick from Yahoo's websocket (`ai/live.py`); for a paid
  feed (Alpaca, Finnhub), implement `LiveFeed`. Outside market hours no tick
  arrives and the REST price is kept.
- The latest daily bar sometimes arrives with volume but NaN prices (seen the
  day after a session). `tool.clean_daily` fills it from the quote; never read
  `daily["Close"].iloc[-1]` from a raw `history()` call.
- Intraday history is short: 1-minute bars cap at 8 days per request.
- Intraday volumes don't sum to the real daily volume, so volume ratios use daily bars.
- `info["dividendYield"]` is already a percent; `shortPercentOfFloat` is a fraction.
- `Ticker.news` often returns nothing; headlines are optional everywhere.

## Evaluating accuracy

- **Score against baselines, not 33%.** The scorer compares the persona call
  with always-up, momentum (repeat the last N days' direction) and the linear
  regression on the same 3-way outcome. Always-up is right about 45–50% of the
  time on 5-day horizons, which is the real bar.
- **Only score live-logged predictions.** The 5-year history overlaps the LLM's
  training data, so replaying it through the personas overstates accuracy. The
  regression can be backtested (it's fit on prices only): walk-forward, refit
  every N days on targets already known that day, then traded on
  non-overlapping periods with 5 bps costs against buy-and-hold. `info`
  valuation, statements, ownership and options data are today's values, so they
  can't be backtested at all.
- **Log stays comparable.** Each record carries `model` and `prompt_version`;
  bump `PROMPT_VERSION` in `agents.py` whenever prompts or packets change, and
  say what changed in `PROMPT_CHANGELOG` (a test enforces an entry per version).
- **Version numbers are claimed on `main` only.** Two branches once both used
  4 and 5 for different prompts, so "version 5" meant two things. On a feature
  branch, describe the change in the changelog under the next number but treat
  that number as provisional; when merging, renumber to the next version not yet
  on `main` (or on the branch being merged into) and merge colliding entries.
  Never reuse a number that a logged or stored prediction already carries.
- **Strength isn't probability.** Check `--score`'s by-strength table before
  presenting strength as a percentage chance.
- **Scoring restates prices to the logged share basis.** Yahoo closes are
  split-adjusted after the fact, so `resolve` multiplies by every split after
  the forecast date. Outcome dates come from the NYSE calendar. Missing split
  history, a missing session bar, an unsettled session or an unknown basis
  leaves the prediction pending rather than mis-scoring it.
- **The regression baseline is below always-up** on average (39-41% vs 40-42%
  across 25 tickers; `finance/spec.md`). Always-up is the bar to beat.


## Database-backed application

Use `database.service.predict_and_store` for API and persisted CLI forecasts.
It stores market data and documents before selecting point-in-time passages,
then saves the prediction and supplied evidence atomically. Do not route the API
through the JSONL-only path. `refresh_market` collects sources without Gemini.

Source IDs cited by an agent are distinct from passages supplied to it. Preserve
both. RSS descriptions are excerpts and Google News items are headlines, not
complete articles or representative public opinion. Hacker News threads (keyless,
always on) are tech-skewed discussion, not a sample of investors. SEC text is opt-in through a
real application/contact identifier. Reddit was removed: its Responsible Builder
Policy requires approval first and forbids sharing its data. Every document has a role
(`company_info`, `public_opinion`, `product_event`) shown in the prompt, and
retrieval mixes the roles per strategy (`service.mix_roles`). Semantic vector
retrieval is optional: `RAG_BACKEND=snowflake` fuses Snowflake Cortex rankings
with the keyword search (`snowflake_rag/spec.md`), and PostgreSQL reloads every
ranked chunk under the same point-in-time rules. The dashboard
(`frontend/src/features/market-dashboard`) reads these routes, and
`tests/test_frontend_contract.py` pins the fields it uses: change a field the
frontend reads and you change the frontend too. Retention, backups, source
use and database roles: `database/docs/retention-and-access.md`. Record prompt changes in
`agents.PROMPT_CHANGELOG` (and `ai/spec.md`).

`database/SETUP.md` describes the project-owned local PostgreSQL and API user
services. Service files, cluster files, and credentials stay gitignored. Use
`database/docs/` for simple explanations and the future explicit cloud migration.
Core PostgreSQL does not need TimescaleDB; the optional migration is deliberate.
Do not assume a cloud connection change transfers data.

For tests, mock all external sources and the LLM. Opt-in database tests permit
only isolated local Unix sockets; never point them at `finance_dev` or cloud.
Live provider verification is a separate authorized smoke check, not a pytest
fixture. The API binds to loopback.
