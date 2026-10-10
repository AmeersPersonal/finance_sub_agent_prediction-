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
├── .env                      # real secrets, gitignored
├── .env.example              # variable names only, committed
├── data/                     # gitignored
│   ├── predictions.jsonl     # prediction log
│   └── cache/bls_<date>.json # BLS allows 25 keyless requests/day, so it's cached daily
└── src/
    ├── main.py               # CLI: predict + log, or --score
    ├── ai/
    │   ├── main.py           # predict(): fetch -> sentiment -> personas in parallel -> aggregate
    │   ├── tool.py           # parallel fetching -> MarketSnapshot (prices, statements, Street, macro)
    │   ├── feeds.py          # Yahoo Finance RSS headlines, BLS inflation/jobs (cached)
    │   ├── sentiment.py      # one Gemini call scoring headlines -1..+1
    │   ├── agents.py         # horizon info, per-strategy packet, prompt, one Gemini call each
    │   ├── personas.py       # strategies, age bands, eligibility rules
    │   ├── llm.py            # Gemini client (only file that talks to the provider)
    │   ├── confidence_score.py  # strategy-balanced vote -> up/down/flat/unclear + strength
    │   ├── evaluation.py     # baselines, prediction log, scorer
    │   ├── rag_retrieval.py  # keyword retrieval over ai/docs/ (.md/.txt)
    │   ├── schemas.py        # PersonaView, PersonaResult, Prediction
    │   ├── test.py           # empty; pytest only collects tests/test_*.py
    │   └── docs/             # private documents, contents gitignored
    │       └── age_profiles/<band>.md   # optional sourced profile, overrides personas.py text
    ├── finance/
    │   ├── indicators.py     # RSI, MACD, ATR, VWAP, volume profile, beta, options, flat band
    │   ├── linear_regression.py  # OLS on price features, walk-forward validated: the baseline
    │   ├── backtest.py       # strategy returns with costs; Sharpe, Sortino, max DD, profit factor
    │   ├── fundamentals.py   # margins, FCF, ROIC, leverage, valuation; Beneish M-score
    │   ├── risk_management.py  # Altman Z-score; ATR stop and 1%-risk position size
    │   ├── quarter_review_analysis.py  # 10-Q growth, margin trend, EPS surprises
    │   ├── positioning.py    # insiders, institutions, short interest, analysts
    │   ├── macro.py          # yield curve, CPI, unemployment, payrolls
    │   └── revenue_forecast.py
    ├── api/                  # localhost FastAPI routes
    ├── sources/              # Yahoo/Google News RSS, Hacker News, optional SEC filings + press releases
    ├── audit/                # source digest and educational risk explanations
    ├── database/             # migrations, repository, orchestration, setup/docs
    ├── oauth/                # auth placeholder; not imported by the dashboard API
    └── tests/                # offline: synthetic snapshot + fake LLM
```

## Commands

From `backend/`:

```
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate elsewhere)
pip install -r src/requirements.txt
copy .env.example .env            # then set GEMINI_API_KEY
```

From `backend/src/`:

```
python main.py AAPL                                   # all 13 personas, 5-day horizon, logged
python main.py AAPL MSFT NVDA --horizon 1             # several tickers
python main.py AAPL --strategy day_trader --age 18-24 # subset (faster on the free tier)
python main.py AAPL --json --no-log
python main.py --score                                # accuracy vs baselines, once horizons pass
pytest
```

Environment variables: `GEMINI_API_KEY` for real predictions, optional
`GEMINI_MODEL` (default `gemini-3.5-flash-lite`), `DATABASE_URL` for database
operations, optional `SEC_USER_AGENT` for SEC filings and 8-K press releases, and optional
`API_CORS_ORIGINS` for local frontend development.

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
  fixtures in `tests/conftest.py`; `predict()` takes `llm=` and `snapshot=`.

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
- Dependencies live in `src/requirements.txt`, pinned with `==`.
- `snake_case` module names, spelled correctly. Earlier typos were fixed in
  `requirements.txt`, `rag_retrieval.py`, `finance/` and `revenue_forecast.py`;
  do not reintroduce them.
- Tests live in `tests/test_*.py`. Never name a module `pytest.py`.

## Known data limits (yfinance)

- Free and unofficial: quotes are near-real-time at best, and Yahoo rate-limits.
  For true live data, swap `tool.py` to a websocket feed (e.g. Alpaca, Finnhub).
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
- **Scoring restates prices to the logged share basis.** Yahoo closes are
  split-adjusted after the fact, so `resolve` multiplies by every split after
  the forecast date. Missing split history, a missing session bar, or an
  unknown basis leaves the prediction pending rather than mis-scoring it.


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
retrieval, frontend wiring, and account integration are not implemented. Record
prompt changes in `ai/spec.md`; current version 6 adds Hacker News threads.

`database/SETUP.md` describes the project-owned local PostgreSQL and API user
services. Service files, cluster files, and credentials stay gitignored. Use
`database/docs/` for simple explanations and the future explicit cloud migration.
Core PostgreSQL does not need TimescaleDB; the optional migration is deliberate.
Do not assume a cloud connection change transfers data.

For tests, mock all external sources and the LLM. Opt-in database tests permit
only isolated local Unix sockets; never point them at `finance_dev` or cloud.
Live provider verification is a separate authorized smoke check, not a pytest
fixture. The API currently binds to loopback and exposes no user preferences.
