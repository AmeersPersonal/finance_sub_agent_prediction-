# spec: backend/src/ai/

## TODOS

- [x] Deleted the empty `ai/test.py`.
- [ ] Run `--modes temps`, then `models` (and `providers` with a second provider), live, and compare `--score` by-mode / by-model accuracy before keeping any mode. Blocked on data: needs scored live forecasts, not code.
- [x] Non-Gemini provider behind `JsonLLM`: `OpenAICompatibleLLM` (OpenAI, Groq, OpenRouter or a local Ollama via `ALT_LLM_*`), routed by `RoutingLLM` for models named `alt:<model>`; the `alt` mode and `providers` preset use it. `build_llm()` is the one constructor.
- [x] Measure it: `--score` and `/score` report up/down accuracy by stability bucket (`Report.by_stability`).
- [ ] Use `stability` as a confidence input only if that table shows higher stability is right more often. Blocked on data: a few hundred scored multi-mode forecasts.
- [ ] `rag_retrieval.py` is keyword overlap only; evaluate embeddings once `docs/` has real content. Blocked: `docs/` holds only `.gitkeep`. (Database-backed forecasts retrieve from PostgreSQL instead; see `database/spec.md`.)
- [x] Scorer: outcomes relative to SPY over the same sessions (`Outcome.relative_*`, `Report.relative`), so always-up can't ride a rising market; SPY closes are fetched with every scoring run.
- [x] `tool.py` uses unofficial yfinance; live-feed adapter added behind the same `MarketSnapshot`: `live.py` (Yahoo's streaming websocket via `yfinance.AsyncWebSocket`; `LiveFeed` protocol for a paid feed).
- [x] Handle stock splits in `evaluation.resolve`: Yahoo split-adjusted closes are restated to the logged share basis; outcomes stay pending when actions or a session bar are missing.
- [x] `strategy_weights` is derived from `--score` history: `evaluation.derive_strategy_weights`, `Report.strategy_weights`, `--weights auto`.
- [x] Keep a changelog of `PROMPT_VERSION` bumps: `agents.PROMPT_CHANGELOG`; `test_pipeline.py` fails if the current version is missing.
- [x] Keyed live feed: `FinnhubLiveFeed` (Finnhub's quote, free tier, `FINNHUB_API_KEY`), chosen with `LIVE_FEED=finnhub` (`live_feed_from_env`); a trade older than 15 minutes keeps the REST quote, like the websocket's timeout.

## Purpose

Everything that involves the LLM or orchestrates a prediction: gathering the
market snapshot, running the persona agents, combining their views, and
scoring the results later.

## Files

| File | Role |
|---|---|
| `main.py` | `predict()`: fetch -> optional live quote -> sentiment -> personas in parallel (optionally under several reasoning modes) -> aggregate -> `Prediction` -> optional call policy. `llm=`, `snapshot=`, `live_feed=`, `documents_by_strategy=` (retrieved passages) and `regression_daily=` (the frozen database dataset) are injectable; `policy=` and `price_signal=` (model A, logged only) are opt-in |
| `policy.py` | `CallPolicy` from `data/call_policy.json` (fitted by `python -m ml coverage --save`): `apply_policy` withholds a call below the horizon's fitted strength (`Prediction.withheld_call`, shown as unclear) and adds `Prediction.p_correct`. Only parts that passed their held-out check are applied |
| `tool.py` | Parallel yfinance fetching into `MarketSnapshot` (prices, annual and quarterly statements, Street data, options, news with links, macro). `fetch_daily` and `clean_daily` (fills Yahoo's unfinalised last bar from the quote). Failures go to `snapshot.errors`, not exceptions |
| `live.py` | `LiveFeed` protocol, `YahooLiveFeed` (first websocket tick), `FinnhubLiveFeed` (keyed quote), `live_feed_from_env` (`LIVE_FEED`), `apply_live_quote` (falls back to the REST price with a warning) |
| `feeds.py` | Yahoo Finance RSS news (`NewsItem`: title, link, date, summary) and BLS inflation/jobs (cached daily in `data/cache/`, pruned after 7 days) |
| `sentiment.py` | One Gemini call scoring headlines -1..+1 |
| `agents.py` | Horizon info, per-strategy data packet, prompt, one Gemini call per persona. Holds `PROMPT_VERSION` and `PROMPT_CHANGELOG` |
| `personas.py` | Strategies, age bands, eligibility (16-17 are long_term only) -> 13 personas |
| `modes.py` | Reasoning modes (model + temperature) and presets: `default`, `temps`, `models`, `full`, `providers` (the `alt` mode exists only with `ALT_LLM_*`) |
| `llm.py` | `GeminiLLM` (retries, 30-second timeout, async cleanup), `OpenAICompatibleLLM` (the second provider), `RoutingLLM`, `build_llm()`; the only file that talks to model providers |
| `confidence_score.py` | Strategy-balanced vote -> up / down / flat / unclear + strength |
| `evaluation.py` | Baselines (always-up, momentum, regression), prediction log (rotated by year), scorer (split-aware; relative to SPY; by strength and stability), derived strategy weights |
| `rag_retrieval.py` | Keyword retrieval over `docs/` (.md / .txt) and age-profile overrides |
| `features.py` | `extract_features`: flattens the strategy packets, regression output and sentiment into one numeric row (`Prediction.features`), logged for the stacker in `ml/` |
| `schemas.py` | `PersonaView` (with validated citation IDs), `PersonaResult`, `Prediction` (pydantic; `quote_source`, `features`, `withheld_call`, `p_correct`, `price_model`, `audit`, sources, frozen packets and learning context are optional so old log lines load; new fields must default to None, see `database.repository.same_forecast`) |
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
  Telling personas not to use flat as a way to pass backfired (version 7):
  unclear is always a miss, so removing flat votes costs accuracy.
- The call policy never changes the personas, the vote or `net_score`; a
  withheld call is kept in `withheld_call` so the policy can be refitted.
- Bump `PROMPT_VERSION` whenever prompts or packets change, and say what changed
  in `PROMPT_CHANGELOG`.
- Only score live-logged predictions; replaying history overstates accuracy.
- Never let a NaN price reach the packets or the scorer: `clean_daily` repairs
  the snapshot, and `resolve` leaves a prediction pending while a required
  session close is missing or invalid.

## Prompt history

`agents.PROMPT_CHANGELOG` is the authoritative list. Before the merge the
database branch numbered its own changes 4-6 (4: supplied online passages with
coverage labels and source IDs; 5: role labels and role mixing; 6: Hacker News
threads). Those numbers collided with the backend branch's 4 and 5, so after
the merge all of them together are version 6.

Version 7 added `horizon.past_outcomes_2y` (`finance.indicators.outcome_base_rates`)
and told personas that missing data or a horizon outside their style lowers
conviction instead of turning the vote flat; `python -m ml bias` showed
long_term voting flat 73% of the time on the replay. On the prices-only replay
(`ml/spec.md`) it scored 6.2 points below version 6 at 1 day: with no flat
votes a split panel fell through to unclear, which always counts as a miss.
Version 8 keeps the base rates and takes the system-prompt additions back.

For database-backed forecasts, `regression_daily` is the frozen `model_datasets` copy of the same daily snapshot the personas saw (`database.datasets`). Direct `predict()` calls still default to `snapshot.daily`. News and persona opinions are not regression features.
