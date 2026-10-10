# CLAUDE.md: Backend

Guidance for AI coding agents working in `backend/` (the Python backend of the
finance sub-agent prediction project). It does not cover any frontend.

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
(needs a paid Level 2 feed), social-media sentiment, IV rank (needs IV
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
    ├── requirements.lock     # every dependency, pinned with hashes (pip-compile)
    ├── api/
    │   └── app.py            # FastAPI: POST /predict, GET /score, GET /health, OAuth routes
    ├── ai/
    │   ├── main.py           # predict(): fetch -> live quote? -> sentiment -> personas -> aggregate
    │   ├── tool.py           # parallel fetching -> MarketSnapshot; clean_daily repairs Yahoo's last bar
    │   ├── live.py           # Yahoo websocket live quote behind the same MarketSnapshot
    │   ├── feeds.py          # Yahoo Finance RSS news (with links), BLS inflation/jobs (cached)
    │   ├── sentiment.py      # one Gemini call scoring headlines -1..+1
    │   ├── agents.py         # horizon info, per-strategy packet, prompt; PROMPT_VERSION + changelog
    │   ├── personas.py       # strategies, age bands, eligibility rules
    │   ├── modes.py          # reasoning modes: model + temperature presets
    │   ├── llm.py            # Gemini client (only file that talks to the provider)
    │   ├── confidence_score.py  # strategy-balanced vote -> up/down/flat/unclear + strength
    │   ├── evaluation.py     # baselines, prediction log, split-aware scorer, derived weights
    │   ├── rag_retrieval.py  # keyword retrieval over ai/docs/ (.md/.txt)
    │   ├── schemas.py        # PersonaView, PersonaResult, Prediction
    │   ├── test.py           # empty; to be deleted
    │   └── docs/             # private documents, contents gitignored
    │       └── age_profiles/<band>.md   # optional sourced profile, overrides personas.py text
    ├── audit/                # explains a prediction (--audit): no new math, one LLM call
    │   ├── analysis.py       # audit_prediction(): the entry point
    │   ├── info.py           # company overview, data checks
    │   ├── risk.py           # decision risk checklist composed from finance/ measures
    │   └── media.py          # news TL;DRs; links come from the feed, never the model
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
    ├── oauth/                # Google OIDC sign-in (code + PKCE), in-memory sessions
    └── tests/                # offline: synthetic snapshot + fake LLM, fake OAuth provider
```

## Commands

From `backend/`:

```
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate elsewhere)
pip install -r src/requirements.txt  # or: pip install --require-hashes -r src/requirements.lock
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
uvicorn api.app:app --reload                          # HTTP API, docs at /docs
pytest                                                # offline
pytest --cov --cov-report=term-missing                # with coverage
```

Environment variables: `GEMINI_API_KEY` (required), `GEMINI_MODEL` (optional,
default `gemini-3.5-flash-lite`), `GEMINI_MODEL_STRONG` (optional, used by the
`strong` reasoning modes), and for API sign-in `OAUTH_CLIENT_ID` /
`OAUTH_CLIENT_SECRET` plus the optional `OAUTH_*` settings in `.env.example`.

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
- **Gemini calls go through `llm.py` only**, using `client.aio.models.generate_content`
  with `response_json_schema`. Keep schemas simple; Gemini supports a subset of
  JSON Schema.
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
  bump `PROMPT_VERSION` in `agents.py` whenever prompts or packets change.
- **Strength isn't probability.** Check `--score`'s by-strength table before
  presenting strength as a percentage chance.
- **Scoring uses unadjusted closes** to match logged live prices, but Yahoo's
  "unadjusted" closes are still split-adjusted after the fact, so `resolve`
  divides the logged price by every split after the prediction's data date.
- **The regression baseline is below always-up** on average (39-41% vs 40-42%
  across 25 tickers; `finance/spec.md`). Always-up is the bar to beat.
