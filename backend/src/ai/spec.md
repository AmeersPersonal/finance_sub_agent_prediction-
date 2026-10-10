# spec: backend/src/ai/

## TODOS

- [ ] `ai/test.py` is empty; delete it.
- [ ] `rag_retrieval.py` is keyword overlap only; evaluate embeddings once `docs/` has real content.
- [ ] `tool.py` uses unofficial yfinance; add a websocket/live-feed adapter behind the same `MarketSnapshot`.
- [x] Handle stock splits in `evaluation.resolve`: Yahoo split-adjusted closes are restated to the logged share basis; outcomes stay pending when actions or a session bar are missing.
- [ ] `strategy_weights` is accepted by `predict()` but nothing sets it; derive from `--score` history.
- [x] Record prompt changes below; continue updating this log.

## Purpose

Everything that involves the LLM or orchestrates a prediction: gathering the
market snapshot, running the persona agents, combining their views, and
scoring the results later.

## Files

| File | Role |
|---|---|
| `main.py` | Numerical/headline packets plus optional supplied passages -> persona views -> aggregate and regression results. LLM, snapshot, documents, and the regression price dataset are injectable |
| `tool.py` | Parallel yfinance fetching into `MarketSnapshot` (prices, statements, Street data, options, macro). Failures go to `snapshot.errors`, not exceptions |
| `feeds.py` | Yahoo Finance RSS headlines and BLS inflation/jobs (cached daily in `data/cache/`) |
| `sentiment.py` | One Gemini call scoring headlines -1..+1 |
| `agents.py` | Horizon info, per-strategy data packet, prompt, one Gemini call per persona. Holds `PROMPT_VERSION` |
| `personas.py` | Strategies, age bands, eligibility (16-17 are long_term only) -> 13 personas |
| `llm.py` | Gemini structured-output client, retries, 30-second request timeout, and async cleanup |
| `confidence_score.py` | Strategy-balanced vote -> up / down / flat / unclear + strength |
| `evaluation.py` | Baselines (always-up, momentum, regression), prediction log, scorer |
| `rag_retrieval.py` | Keyword retrieval over `docs/` (.md / .txt) and age-profile overrides |
| `schemas.py` | Views with valid citation IDs; predictions with source metadata, frozen packets, and learning context |
| `docs/` | Private source documents; contents gitignored, only `.gitkeep` tracked |

## Design rules

- Python computes numbers, the LLM interprets them. New metrics go in
  `finance/` and into a strategy packet in `agents.py`; never send raw price rows.
- Each strategy gets a different packet, otherwise personas echo each other.
- Missing data degrades: metrics become `null`, personas are told to lower conviction.
- Each strategy gets one vote; personas are averaged inside a strategy first.
- "flat" (expect price inside the band) is not "unclear" (personas split).
- Bump `PROMPT_VERSION` whenever prompts or packets change.
- Only score live-logged predictions; replaying history overstates accuracy.

## Prompt history

- Version 3: strategy-specific numeric packets and volatility-sized direction question.
- Version 5: each passage shows its role (company info, public opinion, product event) and an "unconfirmed" mark for rumor/leak wording; the system prompt explains the labels. Retrieval now gives every strategy a mix of the three roles, so packets change too.
- Version 4: supplied online passages with coverage labels, source IDs, and untrusted-evidence handling. Invalid citation IDs are discarded. Database-backed forecasts retrieve sources through `database.service`; direct `predict()` retains injectable documents and the local retrieval fallback.

For database-backed forecasts, `regression_daily` is the frozen `model_datasets` copy of the same daily snapshot the personas saw (`database.datasets`). Direct `predict()` calls still default to `snapshot.daily`. News and persona opinions are not regression features.
