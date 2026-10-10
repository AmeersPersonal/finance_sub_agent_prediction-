# Finance persona predictions: backend

AI agents imitate trader personas (long-term holders, day traders, index and
options traders, ages 16-65) and their views are combined into one call on a
stock over the next N trading days: up, down, flat or unclear. Every call is
saved next to naive baselines and a linear regression, and scored once its
horizon passes. Personas also read retrieved online evidence (news headlines
and excerpts, Hacker News threads, optional SEC filings and 8-K press
releases), each labelled with its role.

How the code is organised, and why: [src/spec.md](src/spec.md). Each folder has
its own `spec.md` with its open TODOs. Rules for AI coding agents:
[src/CLAUDE.md](src/CLAUDE.md). Database guides for beginners:
[src/database/docs/README.md](src/database/docs/README.md).

| Reference | Purpose |
|---|---|
| [Database setup](src/database/SETUP.md) | Local PostgreSQL, migrations, API service |
| [Database spec](src/database/spec.md) | Tables, persistence, and retrieval rules |
| [Dashboard API](src/api/spec.md) | Routes and request formats (the frontend contract) |
| [Online sources](src/sources/spec.md) | What documents are actually collected |
| [Learned models](src/ml/spec.md) | Neural-network and stacker experiments |
| [Cloud migration](src/database/docs/tiger-cloud-migration.md) | Explicit move to Tiger Cloud later |

## Setup

From `backend/`:

```
python -m venv .venv
.venv\Scripts\activate                 # Windows (source .venv/bin/activate elsewhere)
pip install -r src/requirements.txt    # or, reproducibly: pip install --require-hashes -r src/requirements.lock
pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu130 --force-reinstall --no-deps  # NVIDIA GPU
copy .env.example .env                 # then set GEMINI_API_KEY (DATABASE_URL, OAUTH_* as needed)
```

## Run

From `backend/src/`:

```
python main.py AAPL                    # all 13 personas, 5-day horizon, logged to JSONL
python main.py AAPL --database         # same, saved to PostgreSQL with retrieved evidence
python main.py AAPL --audit --live     # plus risk checklist and news digest; websocket price
python main.py --score                 # accuracy vs baselines once horizons pass
python main.py SPY --backtest          # the regression baseline alone, no LLM
python -m ml price                     # learned price models vs always-up, walk-forward (src/ml/spec.md)
uvicorn api.main:app --reload          # HTTP API (database-backed); docs at http://localhost:8000/docs
pytest                                 # offline tests
```

The local database is PostgreSQL (TimescaleDB optional). Retrieval is
keyword-based RAG, not semantic vector search.
