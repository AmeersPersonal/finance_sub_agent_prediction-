# spec: backend/src/audit/

## TODOS

- [ ] **The whole folder is placeholder.** `analysis.py` and `info.py` are empty; `media.py` and `risk.py` contain only comments.
- [ ] `media.py`: fetch company news and use `ai/llm.py` to produce concise TL;DRs with source links.
- [ ] `risk.py`: decide how it differs from `finance/risk_management.py` (Altman Z, ATR sizing) before writing code; it should compose those, not duplicate them.
- [ ] `analysis.py`: define its purpose (not stated anywhere) or delete it.
- [ ] `info.py`: define its purpose (company overview?) or delete it.
- [ ] Add `__init__.py` and tests under `tests/` using `fake_llm`.
- [ ] Reach the model only through `ai/llm.py`, never the provider directly.

## Purpose (intended)

Explain and sanity-check a prediction for a human reader: a short news/media
digest with links, and a risk summary of the investment decision.

## Files

| File | Intended role | State |
|---|---|---|
| `media.py` | General company news -> concise TL;DRs and links, via the LLM in `ai/` | docstring only |
| `risk.py` | Risk behind each investment decision | comment only |
| `analysis.py` | Not defined | empty |
| `info.py` | Not defined | empty |
