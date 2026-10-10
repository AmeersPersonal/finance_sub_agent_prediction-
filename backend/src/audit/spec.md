# spec: backend/src/audit/

## TODOS

- [ ] Define or remove unused `analysis.py` and `info.py` placeholders.
- [ ] Add richer passage-based summaries after evaluating citation quality.

## Purpose

Explain database-backed forecasts using known numbers and source metadata.
No new LLM calls, numerical models, or fetching happen here.

| File | Role |
|---|---|
| `media.py` | Deduplicated source titles, URLs, publication dates, and coverage labels. This is a source digest, not an invented full-article summary. |
| `risk.py` | Explains the forecast question, confidence, regression, flat/unclear, and existing risk calculations. Includes strategy learning context. |
| `analysis.py`, `info.py` | Unused placeholders. |

`database.service` attaches these explanations to `Prediction.learning` before
saving it. Age alone is not a suitability assessment. A source listed as provided
to Gemini is not automatically a source that supports every claim.
