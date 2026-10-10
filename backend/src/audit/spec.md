# spec: backend/src/audit/

## TODOS

- [x] The whole folder was placeholder; every file now has real code and tests.
- [x] `media.py`: company news -> concise TL;DRs with source links, via `ai/llm.py`.
- [x] `risk.py`: decided how it differs from `finance/risk_management.py`: it composes those measures into a decision-level checklist and adds no math of its own.
- [x] `analysis.py`: purpose defined as the audit entry point (`audit_prediction`).
- [x] `info.py`: purpose defined as company overview plus data validation.
- [x] `__init__.py` and tests (`tests/test_audit.py`, using `fake_llm`).
- [x] The model is reached only through `ai/llm.py`'s `JsonLLM`.
- [ ] Tune the risk thresholds (volatility 35% / 60%, agreement 0.6, strength 0.25) against scored outcomes once the log has a few hundred entries.
- [ ] The digest sees RSS titles and descriptions only. Full articles would need a scraper and care with publishers' terms.
- [ ] Add richer passage-based summaries after evaluating citation quality.

## Purpose

Explain and sanity-check a prediction for a human reader. Runs after
`ai.main.predict()` on the same snapshot; the result is stored on
`Prediction.audit`. Enabled by `--audit` on the CLI or `"audit": true` on
the prediction request. Database-backed forecasts also get `Prediction.learning`
(plain-language explanations and a source digest), which uses no LLM call.

| File | Role |
|---|---|
| `media.py` | Deduplicated source titles, URLs, publication dates, and coverage labels. This is a source digest, not an invented full-article summary. |
| `risk.py` | Explains the forecast question, confidence, regression, flat/unclear, and existing risk calculations. Includes strategy learning context. |
| `analysis.py`, `info.py` | Unused placeholders. |

| File | Role |
|---|---|
| `analysis.py` | Entry point: `audit_prediction(prediction, snapshot, llm, news=True)` -> `{company, checks, risk, news, warnings}` |
| `info.py` | `company_overview` (name, sector, industry, exchange, size, short business summary); `validate`: is it an equity, USD listing, fresh prices, quote vs history, enough history, sources complete (`ok` True / False / None = couldn't check) |
| `risk.py` | `decision_risk`: flags with a level (low / medium / high) and a reason. Signal quality (unclear, weak agreement, strength or stability, regression disagrees), earnings inside the horizon, volatility with the ATR position size, deep drawdown, Altman Z zone, Beneish flag, leverage, crowded short. `learning_context`: plain-language meaning of the forecast's numbers for the dashboard |
| `media.py` | `news_digest`: one LLM call; the model refers to items by number only, and links, sources and dates come from the feed. `source_digest`: the retrieved passages' sources with coverage and role, no LLM |

## Design rules

- Only `media.news_digest` calls the LLM; `news=False` makes an audit free.
- Links never come from the model. Items the model invents are dropped.
- `risk.py` reads measures from `finance/` and the prediction. New risk math
  belongs in `finance/`, not here.
- A failed digest is a warning in the audit, never a failed prediction.
- Dependency direction: `audit -> ai -> finance`. `ai/` never imports `audit/`.
- `database.service` attaches `learning_context` and `source_digest` to
  `Prediction.learning` before saving. Age alone is not a suitability
  assessment. A source listed as provided to Gemini is not automatically a
  source that supports every claim.
