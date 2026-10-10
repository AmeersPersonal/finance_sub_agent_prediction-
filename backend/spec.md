# spec: backend/

## TODOS

- [x] Add a pointer to `src/spec.md` in a README once `src/oauth/` has an API surface (`README.md`).
- [x] Add navigation through `README.md` and beginner database guides.
- [x] Decide whether `data/` needs a retention policy. Decision: `predictions.jsonl` is kept forever (it's the scoring record, a few KB per prediction, and only live-logged predictions can be scored); `cache/bls_<date>.json` files older than 7 days are deleted by `ai/feeds.prune_cache` whenever a new one is written.
- [x] Retention and backup policy for database records: `src/database/docs/retention-and-access.md`; backups with `python -m database.backup` (pg_dump, 7 daily / 4 weekly / 12 monthly).
- [x] Add a lock file: `src/requirements.lock` is `uv pip compile --universal --generate-hashes` output (see Design notes).
- [x] Regenerate `src/requirements.lock` after the database merge (2026-10-10): added `psycopg[binary]`, `exchange_calendars` and their dependencies; no existing pin changed. Now a universal lock (Windows, Linux, macOS; Python 3.12+), replacing the Windows-only pip-compile one.
- [x] Regenerate `src/requirements.lock` for the optional Snowflake RAG (2026-10-10): added `snowflake-connector-python` and its dependencies (`boto3`, `pyjwt`, `pyopenssl`, ...). One existing pin moved: `filelock` 4.1.0 -> 3.32.7, because the connector requires `filelock<4`; `torch` accepts either.
- [x] Decide on a home for non-Python tooling. Decision: a `Dockerfile` and `.dockerignore` go in `backend/` (build context `backend/`; `.dockerignore` must exclude `.env`, `.venv/` and `data/`); CI goes in the repo-root `.github/workflows/` (GitHub reads it only there) and runs from `backend/src/`. Nothing non-Python goes in `src/`.
- [x] `predictions.jsonl` rotates by year once it passes 100 MB (`predictions-2026.jsonl`, `ai.evaluation.rotate_log`); `load_log` reads the live file and every archive, deduplicated by prediction id.
- [x] Package deployment/startup: `Dockerfile` (the API, from `src/requirements-api.lock`, no ml stack), `docker-compose.yml` (PostgreSQL, migrations, API on 127.0.0.1:8000), `.dockerignore`; CI in the repo-root `.github/workflows/backend.yml` (tests including PostgreSQL on a Unix socket, and an image build).

## Purpose

Python backend of the finance sub-agent prediction project. AI agents imitate
trader personas (strategy x age band) and their views are combined into one
stock call (up / down / flat / unclear) over N trading days. Every call is
saved beside naive baselines and a linear regression, then scored once its
horizon passes. A CLI (`src/main.py`) and an HTTP API (`src/api/`) run the same
pipeline. The CLI keeps the JSONL workflow; `--database` and the API persist to
PostgreSQL with ingested market data, retrieved evidence and learning
explanations. No real trades are executed.

## Layout

```
backend/
├── README.md       # setup and run commands; points to src/spec.md and the database guides
├── Dockerfile      # the API image (src/requirements-api.lock), one worker, non-root
├── docker-compose.yml  # local stack: PostgreSQL + migrations + API
├── .dockerignore   # keeps .env, data/, tests and private documents out of the image
├── .env            # real secrets, gitignored, never read or print
├── .env.example    # variable names only (GEMINI_*, ALT_LLM_*, OAUTH_*, API_*, DATABASE_URL, LIVE_FEED, ...)
├── .venv/          # local virtualenv, gitignored
├── data/           # runtime output, gitignored
│   ├── predictions.jsonl     # prediction log (appended by the CLI without --database, read by --score)
│   ├── predictions-<year>.jsonl  # yearly archives once the log passes 100 MB
│   ├── backups/              # python -m database.backup: pg_dump files, pruned by schedule
│   ├── models/               # python -m ml ... --save: <name>-<time>.joblib + .json sidecar
│   ├── postgres/             # persistent local PostgreSQL cluster
│   ├── pgsocket/             # local admin connection socket
│   ├── *.service             # generated local user-service definitions
│   └── cache/bls_<date>.json # BLS keyless limit is 25 requests/day, so cached daily; kept 7 days
└── src/            # all application code; see src/spec.md
```

## Design notes

- `src/` is the import root (`pythonpath = .` in `src/pytest.ini`); run
  everything from `backend/src/`.
- `data/` is the only place the app writes. Paths are resolved relative to the
  module (`Path(__file__).resolve().parents[2] / "data"`), so the working
  directory doesn't matter.
- Secrets come from the environment only, loaded from `backend/.env` by
  `src/main.py`, the API and migrations at startup.
- `DATABASE_URL` chooses the database; replacing it does not transfer data.
  PostgreSQL persistence is explicit with CLI `--database`; the API always uses
  the database service. `--no-log` bypasses CLI persistence and ingestion.
- Local server state is project-owned; cloud data would reside on Tiger Cloud.
  TimescaleDB remains optional and requires its own migration. Setup, API
  walkthrough and migration plan live under `src/database/`.
- Dependencies: `src/requirements.txt` lists direct dependencies pinned with
  `==`; `src/requirements.lock` pins every transitive dependency with hashes.
  After changing `requirements.txt`, regenerate the lock from `backend/src/`
  with `uv pip compile requirements.txt --universal --python-version 3.12
  --generate-hashes -o requirements.lock` (uv, installed outside the project
  venv, e.g. `pipx install uv`). `--universal` resolves for every platform at
  once and marks platform-only packages (`colorama ; sys_platform == 'win32'`,
  PyTorch's `nvidia-*` / `triton` ; `sys_platform == 'linux'`), so the lock
  works on any OS with Python 3.12+, and the existing lock is kept as a
  preference, so unrelated pins don't move. Regenerate the API image's lock the
  same way: `uv pip compile requirements-api.in -c requirements.txt --universal
  --python-version 3.12 --generate-hashes -o requirements-api.lock`
  (`requirements-api.in` lists names only; versions come from
  `requirements.txt`). `setuptools` (which `torch` needs) is
  included. Install reproducibly with `pip install --require-hashes -r
  requirements.lock`. PyPI's `torch` is CPU-only on Windows and macOS but the
  CUDA build on Linux (several GB of `nvidia-*` packages). For a CPU-only Linux
  install, or the GPU build on Windows, reinstall it afterwards from PyTorch's
  index (`pip install torch==2.12.0 --index-url
  https://download.pytorch.org/whl/cpu` or `.../whl/cu130`, with
  `--force-reinstall --no-deps`).
