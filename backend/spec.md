# spec: backend/

## TODOS

- [x] Add navigation through `README.md` and beginner database guides.
- [ ] Define retention and backup policies for database records and runtime files.
- [ ] Add a dependency lock file or hashes beyond pinned package versions.
- [ ] Package deployment/startup for teammates and future hosting.

## Purpose

Python backend for the finance learning project. Gemini personas form a combined
up/down/flat/unclear forecast. An independent regression provides a historical
benchmark. Outcomes are evaluated after the trading-day horizon passes.

The CLI supports the original JSONL workflow. Database-backed CLI calls and the
local FastAPI server add market/document ingestion, keyword retrieval, evidence
links, and learning explanations. No real trades are executed.

## Layout

```
backend/
├── README.md       # guide navigation
├── .env            # private secrets; loaded normally, never inspected or printed
├── .env.example    # variable names and placeholders only
├── .venv/          # local Python environment, gitignored
├── data/           # local runtime state, gitignored
│   ├── postgres/   # persistent local PostgreSQL cluster
│   ├── pgsocket/   # local admin connection socket
│   ├── *.service   # generated local user-service definitions
│   ├── predictions.jsonl
│   └── cache/
└── src/            # application packages; see src/spec.md
```

## Design notes

- `src/` is the import root. Run commands from `backend/src/`.
- CLI, API, and migration entry points load the private backend environment.
- `DATABASE_URL` chooses the database; replacing it does not transfer data.
- PostgreSQL persistence is explicit with CLI `--database`; API operations use
  the database service. `--no-log` bypasses CLI persistence and ingestion.
- Local server state is project-owned; cloud data would reside on Tiger Cloud.
  TimescaleDB remains optional and requires its own migration.
- Account authorization is not implemented. Local API service binds to loopback.
- Setup, API walkthrough, and migration plan live under `src/database/`.
