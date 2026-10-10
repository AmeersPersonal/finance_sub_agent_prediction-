# Moving from local PostgreSQL to Tiger Cloud

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
commands at the new service and run the core migration. Then fetch new data and
make new forecasts there. Old local records stay local.

**Keep local history:** pause writes, back up with PostgreSQL's `pg_dump`, and
restore the application schema/data using `pg_restore` into a suitable empty
target. Preserve IDs, relationships, identity sequences, and `schema_migrations`.
Adapt ownership and grants to the cloud role rather than copying local login
credentials. Keep private backups in gitignored storage.

Choose one schema-creation approach: do not restore a full schema on top of
tables already created by the migration runner. Existing cloud application data
requires a separate merge plan. After restoring migration history, the runner
checks it and applies only updates that have not been applied.

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

Cloud migration has not been performed; these are future steps.
