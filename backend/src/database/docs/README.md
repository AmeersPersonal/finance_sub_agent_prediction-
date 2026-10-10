# Database guides

The app currently uses local PostgreSQL. Tiger Cloud is the future hosting
location; TimescaleDB is an optional PostgreSQL extension for price history.

| Guide | Answers |
|---|---|
| [Schema](schema.md) | What do the tables store, and how are they connected? |
| [How it works](how-it-works.md) | How does Python send, save, and read information? |
| [Model data loader](model-data.md) | How do saved prices reach the regression or a future neural network? |
| [Moving to Tiger Cloud](tiger-cloud-migration.md) | What must happen before the cloud database replaces the local one? |
| [Setup instructions](../SETUP.md) | What connection settings and commands do I use? |

## Where we are now

- Persistent PostgreSQL 18 and the localhost dashboard API have been configured.
- Its database is `finance_dev`, reached at `127.0.0.1:55440`.
- The core schema is applied. The user service starts at login.
- Forecast storage and evaluation work through the `--database` CLI option.
- TimescaleDB has not been enabled; it is not needed to continue development.
- Linked RSS evidence, optional SEC filings, keyword retrieval, and dashboard API routes are implemented.
- Semantic vector retrieval, Reddit ingestion, and the frontend integration are future work.
- [Dashboard walkthrough](dashboard-api.md) shows how to use the routes.

The private connection is in `backend/.env`. Database files live in
`backend/data/postgres/`. Both are ignored by Git. A persistent database survives
restarts, but still needs backups for protection against disk loss.

Neither fixing Tiger Console login nor changing `DATABASE_URL` copies data.
Cloud migration is an explicit step described in the migration guide.
