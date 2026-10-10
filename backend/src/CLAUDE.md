# AGENTS.md: Backend

Guidance for AI coding agents working in `backend/` (the Python backend of the
finance sub-agent prediction project). It does not cover any frontend.

## Layout

```
backend/
├── .env                     # real secrets, gitignored
├── .env.copy                # gitignored
└── src/
    ├── main.py              # backend entry point
    ├── requirements.txt     # Python dependencies
    ├── ai/
    │   ├── main.py              # AI pipeline entry point
    │   ├── rag_retrieval.py     # retrieval over the documents in ai/docs/
    │   ├── confidence_score.py  # confidence scoring for predictions
    │   ├── tool.py              # tools the agent can call
    │   ├── pytest.py            # placeholder; shadows the pytest package, rename to test_*.py
    │   └── docs/                # private RAG source documents, contents gitignored
    ├── finance/
    │   └── revenue_forecast.py  # revenue forecasting
    └── oauth/               # OAuth flow and token handling
```

## Hard rules

- **Never read, print, log, or commit `.env` or any `.env.*`** (only
  `.env.example` is allowed in git, and it holds variable names only). Refer to
  secrets by variable name and load them from the environment. Never hardcode
  keys, tokens, or client secrets.
- **Never commit documents.** `src/ai/docs/` holds private source documents for
  RAG. Do not copy their contents into code, tests, fixtures, logs, or commit
  messages.
- **OAuth credentials and tokens stay out of git.** Anything credential-like
  under `src/oauth/` (client secrets, `token.json`, keys) is gitignored. Keep
  it that way.
- **Do not weaken `.gitignore`.** Before committing, check `git status`; if a
  secret or document shows up as staged, stop and unstage it.

## Conventions

- Python. Dependencies live in `src/requirements.txt`; pin the version when
  adding one.
- `snake_case` module names, spelled correctly. Earlier typos were fixed in
  `requirements.txt`, `rag_retrieval.py`, `finance/`, and
  `revenue_forecast.py`; do not reintroduce them.
- Keep concerns in their module: retrieval in `rag_retrieval.py`, scoring in
  `confidence_score.py`, agent tools in `tool.py`, forecasting in `finance/`.
  `main.py` files wire things together and should not hold that logic.
- Tests use pytest and live in `test_*.py` files. Never name a module
  `pytest.py`.

## Status

Every source file is currently an empty scaffold. Fill in the framework, run
and test commands, and environment variable names (names only) here as they
are added.
