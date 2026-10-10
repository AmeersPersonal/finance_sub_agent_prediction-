# Finance persona predictions: backend

AI agents imitate trader personas (long-term holders, day traders, index and
options traders, ages 16-65) and their views are combined into one call on a
stock over the next N trading days: up, down, flat or unclear. Every call is
logged next to naive baselines and scored once its horizon passes.

How the code is organised, and why: [src/spec.md](src/spec.md). Each folder has
its own `spec.md` with its open TODOs. Rules for AI coding agents:
[src/CLAUDE.md](src/CLAUDE.md).

## Setup

From `backend/`:

```
python -m venv .venv
.venv\Scripts\activate                 # Windows (source .venv/bin/activate elsewhere)
pip install -r src/requirements.txt    # or, reproducibly: pip install --require-hashes -r src/requirements.lock
pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu130 --force-reinstall --no-deps  # NVIDIA GPU
copy .env.example .env                 # then set GEMINI_API_KEY (and OAUTH_* for sign-in)
```

## Run

From `backend/src/`:

```
python main.py AAPL                    # all 13 personas, 5-day horizon, logged
python main.py AAPL --audit --live     # plus risk checklist and news digest; websocket price
python main.py --score                 # accuracy vs baselines once horizons pass
python main.py SPY --backtest          # the regression baseline alone, no LLM
python -m ml price                     # learned price models vs always-up, walk-forward (src/ml/spec.md)
uvicorn api.app:app --reload           # HTTP API; docs at http://localhost:8000/docs
pytest                                 # offline tests
```
