# spec: backend/src/ai/

## TODOS

- [ ] `ai/test.py` is empty; delete it (`git rm backend/src/ai/test.py`).
- [ ] Run `--modes temps`, then `models`, live and compare `--score` by-mode / by-model accuracy before keeping any mode.
- [ ] Add a non-Gemini provider behind `JsonLLM` for real model diversity.
- [ ] Use `stability` (share of samples matching the call) as a confidence input only if `--score` shows it helps.
- [ ] `rag_retrieval.py` is keyword overlap only; evaluate embeddings once `docs/` has real content. Blocked: `docs/` holds only `.gitkeep`.
- [x] `tool.py` uses unofficial yfinance; live-feed adapter added behind the same `MarketSnapshot`: `live.py` (Yahoo's streaming websocket via `yfinance.AsyncWebSocket`; `LiveFeed` protocol for a paid feed).
- [x] Handle stock splits in `evaluation.resolve`: the logged price is divided by every split after the data date (Yahoo's "unadjusted" closes are split-adjusted after the fact).
- [x] `strategy_weights` is derived from `--score` history: `evaluation.derive_strategy_weights`, `Report.strategy_weights`, `--weights auto`.
- [x] Keep a changelog of `PROMPT_VERSION` bumps: `agents.PROMPT_CHANGELOG`; `test_pipeline.py` fails if the current version is missing.
- [ ] Add a paid `LiveFeed` (Alpaca or Finnhub) if Yahoo's websocket proves unreliable; it needs an API key in `.env`.

## Purpose

Everything that involves the LLM or orchestrates a prediction: gathering the
market snapshot, running the persona agents, combining their views, and
scoring the results later.

## Files

| File | Role |
|---|---|
| `main.py` | `predict()`: fetch -> optional live quote -> sentiment -> personas in parallel -> aggregate -> `Prediction`. `llm=`, `snapshot=` and `live_feed=` are injectable for tests |
| `tool.py` | Parallel yfinance fetching into `MarketSnapshot` (prices, annual and quarterly statements, Street data, options, news with links, macro). `fetch_daily` and `clean_daily` (fills Yahoo's unfinalised last bar from the quote). Failures go to `snapshot.errors`, not exceptions |
| `live.py` | `LiveFeed` protocol, `YahooLiveFeed` (first websocket tick), `apply_live_quote` (falls back to the REST price with a warning) |
| `feeds.py` | Yahoo Finance RSS news (`NewsItem`: title, link, date, summary) and BLS inflation/jobs (cached daily in `data/cache/`, pruned after 7 days) |
| `sentiment.py` | One Gemini call scoring headlines -1..+1 |
| `agents.py` | Horizon info, per-strategy data packet, prompt, one Gemini call per persona. Holds `PROMPT_VERSION` and `PROMPT_CHANGELOG` |
| `personas.py` | Strategies, age bands, eligibility (16-17 are long_term only) -> 13 personas |
| `modes.py` | Reasoning modes (model + temperature) and presets: `default`, `temps`, `models`, `full` |
| `llm.py` | Gemini client with retries; the only file that talks to the provider |
| `confidence_score.py` | Strategy-balanced vote -> up / down / flat / unclear + strength |
| `evaluation.py` | Baselines (always-up, momentum, regression), prediction log, scorer (split-aware), derived strategy weights |
| `rag_retrieval.py` | Keyword retrieval over `docs/` (.md / .txt) and age-profile overrides |
| `schemas.py` | `PersonaView`, `PersonaResult`, `Prediction` (pydantic; `quote_source` and `audit` are optional so old log lines load) |
| `test.py` | empty; to be deleted |
| `docs/` | Private source documents; contents gitignored, only `.gitkeep` tracked |

## Design rules

- Python computes numbers, the LLM interprets them. New metrics go in
  `finance/` and into a strategy packet in `agents.py`; never send raw price rows.
- Each strategy gets a different packet, otherwise personas echo each other.
- Missing data degrades: metrics become `null`, personas are told to lower conviction.
- A live-quote failure is a data warning, not a `snapshot.errors` entry: the REST
  price is still there, so personas shouldn't lower conviction over it.
- Each strategy gets one vote; personas are averaged inside a strategy first.
  Strategy weights, when given, scale those votes.
- Reasoning modes are collapsed per persona before that, so extra samples never add weight.
- `default` mode equals the pre-modes behaviour; keep it logged as the control.
- "flat" (expect price inside the band) is not "unclear" (personas split).
- Bump `PROMPT_VERSION` whenever prompts or packets change, and say what changed
  in `PROMPT_CHANGELOG`.
- Only score live-logged predictions; replaying history overstates accuracy.
- Never let a NaN price reach the packets or the scorer: `clean_daily` repairs
  the snapshot, and `resolve` leaves a prediction pending while its target close is NaN.
