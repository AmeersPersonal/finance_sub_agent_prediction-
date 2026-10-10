# Retention, backups, source use and access

The project's policy for what the database keeps, for how long, how it is
backed up, what each source may be used for, and who can do what. It applies to
any PostgreSQL the backend points at: the local cluster, the Docker Compose
stack, or a future Tiger Cloud service. Change it here, in one place, when the
team decides differently.

## What is kept, and for how long

| Data | Tables | Kept | Why |
| --- | --- | --- | --- |
| Forecasts and their inputs | `prediction_runs`, `prediction_outputs`, `prediction_evidence`, `model_datasets` | Forever | They are the scoring record; only live-logged forecasts can be scored, so a deleted one can never be replaced. Immutable by trigger. |
| Outcomes | `evaluations` | Forever | Append-only revisions; the audit trail of every score. |
| Prices | `price_bars`, `price_bar_revisions` | Forever | A few MB per ticker per year. Revisions make any past dataset rebuildable (`model_data.load_daily_prices_as_known`). |
| Company data | `fundamental_snapshots` | Forever | Point-in-time; Yahoo can't serve it historically. |
| Source documents | `documents`, `document_chunks`, `document_instruments` | Forever, within each source's terms below | Forecasts cite them by id. |
| Snowflake index (optional) | Snowflake `RAG_CHUNKS`; `snowflake_synced_chunks` here | As long as `RAG_BACKEND=snowflake` is used | A derived copy of document chunks with embeddings, for ranking only. PostgreSQL stays the record: drop `RAG_CHUNKS` and delete the tracking rows to remove it, and `python -m snowflake_rag sync` rebuilds it. |
| Sign-in state | `oauth_pending_logins`, `oauth_sessions` | 10 minutes / 8 hours, deleted after expiry | Hashes only; swept on the next write. |
| Account preferences | `user_preferences` | Until the user deletes them (`DELETE /me/preferences`) or asks us to | Personal data: keep only while the user wants it. |
| JSONL log (CLI) | `backend/data/predictions.jsonl` | Forever; rotated by year past 100 MB | Same reason as forecasts. |
| BLS cache | `backend/data/cache/` | 7 days | Re-fetchable. |

"Forever" means the life of the project. If the project ends, export what you
want to keep (a final backup) and drop the database; nothing here is needed by
anyone else.

## Backups

- **What:** `python -m database.backup` (from `backend/src/`) runs `pg_dump`
  in custom format into `backend/data/backups/`, which is gitignored.
- **When:** daily while forecasts are being collected (Phase 1, `ml/spec.md`),
  e.g. a scheduled task or cron entry, plus once before every migration.
- **How long:** the newest dump of each of the last 7 days, 4 weeks and 12
  months. Each run prunes the rest; files not named by the tool are never touched.
- **Where:** a dump holds everything in the table above, including account
  preferences, so treat it like the database itself. Copy it to storage only the
  team can read (an encrypted disk or a private bucket), never into the repo or
  a shared chat.
- **Restore test:** once a month, restore the newest dump into a scratch
  database (`createdb restore_check && pg_restore --no-owner --dbname
  restore_check <file>`), run `python -m database.migrate` against it (it
  should say the schema is up to date), then drop it. A backup that was never
  restored is a hope, not a backup.
- **Docker Compose:** `docker compose exec db pg_dump -U finance -Fc finance >
  data/backups/finance-<date>.dump` from `backend/`.
- **Tiger Cloud:** keep its own automated backups on as well; `pg_dump` dumps
  are the portable copy (`tiger-cloud-migration.md`).

## Source use

What each source may be stored and used for. These follow the providers'
published terms as summarised in `sources/spec.md`; read the terms again
before any public or commercial use.

| Source | Stored | Allowed use here | Not allowed |
| --- | --- | --- | --- |
| Yahoo Finance RSS | Headline, publisher description (an excerpt), link | Evidence passages and citations in this learning prototype | Following links or storing full articles; republishing excerpts outside the app |
| Google News RSS | Headline and link only | As above; its terms cover personal, non-commercial reading | Any other use without reviewing its terms |
| SEC EDGAR | Full text of the latest 10-K, 10-Q, 8-K and 8-K press releases | Evidence passages and citations; these are public filings | Requests without a real `SEC_USER_AGENT` contact, or faster than SEC's fair-access rate |
| Hacker News | Top comments (400 characters), thread link; no author names | Evidence passages, cited by thread | Treating it as a sample of investor opinion; storing authors |
| Reddit | Nothing | None | Collecting it at all (its Responsible Builder Policy needs approval and forbids sharing data with a model) |
| yfinance (prices, statements, ownership) | Numbers | Computing metrics for personas | Redistributing raw data as a data product |

Copying chunks to the optional Snowflake index is internal processing under the
same rules: it stores nothing a source's row above forbids storing, and its
contents never leave the team's Snowflake account.

Document text from `backend/src/ai/docs/` is private and never stored in the
database or committed (`CLAUDE.md`).

## Access roles

`database/roles.sql` creates least-privilege roles for any database more than
one person can reach. The local development cluster can keep its single owner.

| Role | Can | Cannot | Used by |
| --- | --- | --- | --- |
| Owner (administrator) | Everything, including DDL | | `python -m database.migrate`, `roles.sql`, backups |
| `finance_writer` / login `finance_api` | Read all tables; insert records; update `price_bars` and `user_preferences`; delete preferences and sign-in sessions | Change or delete forecasts, evidence or outcomes; alter the schema | The API and CLI (`DATABASE_URL`) |
| `finance_reader` / login `finance_analyst` | Read forecasts, outcomes, prices and sources | Read sign-in state or preferences; write anything | Analysis, notebooks, dashboards |

Rules:

- The API's `DATABASE_URL` uses `finance_api`, never the owner. Migrations and
  backups use the owner's URL, kept outside the API's environment.
- Re-run `roles.sql` after every new migration so new tables get their grants.
- Rotate a password by re-running `roles.sql` (it prompts) or `ALTER ROLE`.
- Cloud credentials live only in each person's private `backend/.env` or the
  host's secret store; never in the repo, issues or chat.
