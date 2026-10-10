# spec: backend/src/ai/

## TODOS

- [ ] `ai/test.py` is empty; delete it.
- [ ] `rag_retrieval.py` is keyword overlap only; evaluate embeddings once `docs/` has real content.
- [ ] `tool.py` uses unofficial yfinance; add a websocket/live-feed adapter behind the same `MarketSnapshot`.
- [ ] Handle stock splits in `evaluation.resolve` (scoring uses unadjusted closes).
- [ ] `strategy_weights` is accepted by `predict()` but nothing sets it; derive from `--score` history.
- [ ] Keep a changelog of `PROMPT_VERSION` bumps so old log entries stay interpretable.

## Purpose

Everything that involves the LLM or orchestrates a prediction: gathering the
market snapshot, running the persona agents, combining their views, and
scoring the results later.

## Files

| File | Role |
|---|---|
| `main.py` | `predict()`: fetch -> sentiment -> personas in parallel -> aggregate -> `Prediction`. `llm=` and `snapshot=` are injectable for tests |
| `tool.py` | Parallel yfinance fetching into `MarketSnapshot` (prices, statements, Street data, options, macro). Failures go to `snapshot.errors`, not exceptions |
| `feeds.py` | Yahoo Finance RSS headlines and BLS inflation/jobs (cached daily in `data/cache/`) |
| `sentiment.py` | One Gemini call scoring headlines -1..+1 |
| `agents.py` | Horizon info, per-strategy data packet, prompt, one Gemini call per persona. Holds `PROMPT_VERSION` |
| `personas.py` | Strategies, age bands, eligibility (16-17 are long_term only) -> 13 personas |
| `llm.py` | Gemini client with retries; the only file that talks to the provider |
| `confidence_score.py` | Strategy-balanced vote -> up / down / flat / unclear + strength |
| `evaluation.py` | Baselines (always-up, momentum, regression), prediction log, scorer |
| `rag_retrieval.py` | Keyword retrieval over `docs/` (.md / .txt) and age-profile overrides |
| `schemas.py` | `PersonaView`, `PersonaResult`, `Prediction` (pydantic) |
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
