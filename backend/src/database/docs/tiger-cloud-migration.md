# Moving from local PostgreSQL to Tiger Cloud

**Status (October 10, 2026):** done. The team's Tiger service (PostgreSQL 18,
TimescaleDB 2.30) has every migration, including the optional Timescale one,
and a copy of the local history with IDs and sequences preserved. The Snowflake
index was built from the same IDs, so it needed no rebuild. The steps below are
kept for the next service (staging, production).

## Connecting to the team's Tiger service

1. **Get the connection URL and database password** from the service owner,
   privately. Never commit either one.
2. **Get your public IP allowed.** The service has an IP allow list (Tiger
   Console -> Security -> IP Allow Lists; edit the list attached to the
   service). Find your address with `curl https://api.ipify.org` and add it as
   `<ip>/32`. Your address changes with the network you're on.
3. **Avoid campus Wi-Fi for database work.** It silently drops PostgreSQL
   traffic: `psql` hangs and then reports `timeout expired`, even with an
   allowed IP. A phone hotspot works (add its IP too).
4. **Keep the password out of `.env`.** Put it in `~/.pgpass` (mode 600) as
   `host:port:tsdb:tsdbadmin:password`, and set `DATABASE_URL` in `backend/.env`
   without one:
   `postgresql://tsdbadmin@<host>:<port>/tsdb?sslmode=require&connect_timeout=20`.
   `connect_timeout` turns a blocked network into a quick error instead of a hang.
5. **Check:** `psql "$DATABASE_URL" -c "select 1"`, then run
   `python -m database.migrate` from `backend/src/`; it should report nothing new
   unless someone added a migration.

Leave a commented-out local `DATABASE_URL` above the Tiger one to switch back
when you're on a network that blocks Tiger. Writes made locally stay local.

## Do we need TimescaleDB now?

No. Ordinary PostgreSQL supports our current schema and prototype. Keep building
locally, then enable time-series features when they are useful or when testing
the Tiger Cloud integration.

Tiger Cloud does not automatically discover or copy this computer's database.
Changing `DATABASE_URL` changes where new reads and writes go; it moves nothing.
Enabling TimescaleDB reorganizes a price table within a database, which is a
different operation from transferring local data to a cloud server.

## Plan once console access works

1. **Create a development cloud service.** Obtain its private PostgreSQL
   connection details and TLS settings. Check PostgreSQL compatibility: our
   local instance is version 18; do not assume a dump restores into an older
   server. Confirm extension availability and migration permissions too.
2. **Choose whether local data matters.** Use one of the paths below.
3. **Validate the cloud copy.** Check tables, migration history, row counts,
   prediction IDs, document links, and a sample forecast round-trip.
4. **Enable TimescaleDB if desired.** Our optional migration converts
   `price_bars` to a hypertable and records that change in migration history.
5. **Switch the app.** Update the private `DATABASE_URL` to the cloud connection,
   restart the backend, and verify reads/writes before resuming normal work.

## Two paths

**Start fresh:** if local rows are disposable development data, point migration
commands at the new service and run all ordinary migrations, including `005`
for the title search index. Then fetch new data and make new forecasts there.
Old local records stay local.

**Keep local history:** pause writes, back up with PostgreSQL's `pg_dump`, and
restore the application schema/data using `pg_restore` into a suitable empty
target. Preserve IDs, relationships, identity sequences, and `schema_migrations`.
Adapt ownership and grants to the cloud role rather than copying local login
credentials. Keep private backups in gitignored storage.

Choose one schema-creation approach: do not restore a full schema on top of
tables already created by the migration runner. Existing cloud application data
requires a separate merge plan. After restoring migration history, the runner
checks it and applies only updates that have not been applied. Verify the target's
own migration history and valid `documents_title_search_idx`; a local `005`
application does not establish that a cloud copy has the index.

The small-prototype approach above uses a deliberate write pause. Tiger Data
documents PostgreSQL dump/restore as a migration option in its
[migration guide](https://docs.tigerdata.com/migrate/latest).

## Optional time-series migration

With the backend configured for the intended target and a Timescale-enabled
server, run from `backend/src/`:

```bash
../.venv/bin/python -m database.migrate --timescale
```

This is explicit, not automatic. It requires extension permissions and may take
time or lock a populated price table. It does not copy data from another server.

Keep the local database and backup until cloud validation succeeds. If cutover
fails before cloud writes begin, switch back to the saved local connection.
After cloud writes begin, switching back requires reconciling those newer rows.

These steps were followed for the development service (keep-local-history
path, data-only `pg_dump` into a migrated target).
