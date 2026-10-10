# spec: backend/src/tests/

## TODOS

- [ ] No tests for `ai/llm.py` retry behaviour (`RETRYABLE_STATUS`).
- [ ] No tests for `main.py` argument handling or `render`.
- [ ] Add tests for `audit/` and `oauth/` once they have code.
- [ ] Add a coverage run to the commands below.

## Purpose

Fast, fully offline test suite. Nothing here may touch the network or Gemini.

## Layout

| File | Covers |
|---|---|
| `conftest.py` | `snapshot` fixture (synthetic `MarketSnapshot`), `fake_llm` / `failing_llm`, sample statements and Street data |
| `test_pipeline.py` | `predict()` end to end with the fake LLM |
| `test_personas.py`, `test_confidence_score.py` | eligibility and aggregation |
| `test_evaluation.py` | baselines, log, scorer |
| `test_sentiment.py`, `test_feeds.py`, `test_rag_retrieval.py`, `test_tool.py` | ai helpers |
| `test_finance.py`, `test_fundamentals.py`, `test_positioning_macro.py`, `test_backtest.py`, `test_linear_regression.py` | finance modules |

## Rules

- Name files `test_*.py`; never name a module `pytest.py`.
- Use the `snapshot` and `fake_llm` fixtures; `predict()` takes `llm=` and `snapshot=`.
- Run from `backend/src/` with `pytest`.
