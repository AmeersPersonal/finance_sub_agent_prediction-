# Database guides

The team's development database is on Tiger Cloud (PostgreSQL 18 with
TimescaleDB); local PostgreSQL still works for offline development. To connect,
see [Moving to Tiger Cloud](tiger-cloud-migration.md#connecting-to-the-teams-tiger-service).

| Guide | Answers |
|---|---|
| [Schema](schema.md) | What do the tables store, and how are they connected? |
| [How it works](how-it-works.md) | How does Python send, save, and read information? |
| [Model data loader](model-data.md) | How do saved prices reach the regression or a future neural network? |
| [Moving to Tiger Cloud](tiger-cloud-migration.md) | What must happen before the cloud database replaces the local one? |
| [Retention, backups and access](retention-and-access.md) | What do we keep, how is it backed up, and who can read or change it? |
| [Setup instructions](../SETUP.md) | What connection settings and commands do I use? |

## Where we are now

- Persistent PostgreSQL 18 and the localhost dashboard API have been configured.
- Its database is `finance_dev`, reached at `127.0.0.1:55440`.
- The core schema is applied. The user service starts at login.
- Forecast storage and evaluation work through the `--database` CLI option.
- TimescaleDB has not been enabled; it is not needed to continue development.
- Linked RSS evidence (Yahoo, Google News), Hacker News threads, optional SEC filings and 8-K press releases, role-mixed keyword retrieval, and dashboard API routes are implemented.
- Optional Snowflake vector retrieval (`RAG_BACKEND=snowflake`, `snowflake_rag/spec.md`) is set up against the team account; the frontend integration is future work.
- [Dashboard walkthrough](dashboard-api.md) shows how to use the routes.

The private connection is in `backend/.env`. Database files live in
`backend/data/postgres/`. Both are ignored by Git. A persistent database survives
restarts, but still needs backups for protection against disk loss:
`python -m database.backup` ([retention-and-access.md](retention-and-access.md)).

Neither fixing Tiger Console login nor changing `DATABASE_URL` copies data.
Cloud migration is an explicit step described in the migration guide.
