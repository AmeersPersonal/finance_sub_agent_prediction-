-- OPTIONAL: explicitly opt in on Tiger Data / a TimescaleDB-enabled server.
-- Never apply this migration automatically on ordinary PostgreSQL.
-- The deployment must already provide the extension and sufficient privileges.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Every unique key includes bar_at, as required by hypertable partitioning.
SELECT create_hypertable(
    'price_bars', 'bar_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);
