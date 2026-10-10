# spec: backend/

## TODOS

- [ ] Add a pointer to `src/spec.md` in a README once `src/oauth/` has an API surface.
- [ ] Decide whether `data/` needs a retention policy (the prediction log grows forever).
- [ ] Add a lock file or `pip-compile` output; `src/requirements.txt` is pinned but has no hashes.
- [ ] Decide on a home for non-Python tooling (Dockerfile, CI config) before it lands in `src/`.

## Purpose

Python backend of the finance sub-agent prediction project. AI agents imitate
trader personas (strategy x age band) and their views are combined into one
stock call (up / down / flat / unclear) over N trading days. Every call is
logged beside naive baselines and a linear regression, then scored once its
horizon passes.

## Layout

```
backend/
├── .env            # real secrets, gitignored, never read or print
├── .env.example    # variable names only (GEMINI_API_KEY, GEMINI_MODEL)
├── .venv/          # local virtualenv, gitignored
├── data/           # runtime output, gitignored
│   ├── predictions.jsonl     # prediction log (appended by main.py, read by --score)
│   └── cache/bls_<date>.json # BLS keyless limit is 25 requests/day, so cached daily
└── src/            # all application code; see src/spec.md
```

## Design notes

- `src/` is the import root (`pythonpath = .` in `src/pytest.ini`); run
  everything from `backend/src/`.
- `data/` is the only place the app writes. Paths are resolved relative to the
  module (`Path(__file__).resolve().parents[2] / "data"`), so the working
  directory doesn't matter.
- Secrets come from the environment only, loaded from `backend/.env` by
  `src/main.py`.
