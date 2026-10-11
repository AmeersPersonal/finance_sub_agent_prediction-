-- Least-privilege database roles for a shared or hosted database
-- (docs/retention-and-access.md). Not a migration: roles belong to the whole
-- server, so an administrator runs this once per database, after
-- `python -m database.migrate`, and again after every new migration (it is
-- idempotent and grants on the tables that exist when it runs):
--
--   psql "$ADMIN_DATABASE_URL" -f database/roles.sql                  # prompts for passwords
--   psql "$ADMIN_DATABASE_URL" -v schema=public -f database/roles.sql
--
-- Group roles (NOLOGIN) carry the privileges and login roles only inherit them,
-- so a leaked password is rotated with one ALTER ROLE, nothing re-granted.
-- The administrator (or a dedicated owner role) keeps ownership and runs the
-- migrations; the API never needs DDL rights.

\set ON_ERROR_STOP on
\if :{?schema}
\else
  \set schema public
\endif
\if :{?app_password}
\else
  \prompt 'Password for finance_api (the API and CLI): ' app_password
\endif
\if :{?readonly_password}
\else
  \prompt 'Password for finance_analyst (read-only): ' readonly_password
\endif

SELECT 'CREATE ROLE finance_writer NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_writer') \gexec
SELECT 'CREATE ROLE finance_reader NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_reader') \gexec

GRANT USAGE ON SCHEMA :"schema" TO finance_writer, finance_reader;

-- finance_writer: what the API and CLI do. Records are appended (immutable tables
-- also have triggers); price bars are refreshed in place (their old versions are
-- archived by trigger, which inserts into price_bar_revisions); preferences and
-- sign-in sessions are the only rows it deletes.
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA :"schema" TO finance_writer;
GRANT UPDATE ON :"schema".price_bars, :"schema".user_preferences,
    :"schema".prediction_jobs, :"schema".paper_accounts,
    :"schema".paper_positions TO finance_writer;
GRANT DELETE ON :"schema".user_preferences, :"schema".oauth_pending_logins,
    :"schema".oauth_sessions, :"schema".prediction_jobs, :"schema".paper_orders,
    :"schema".paper_positions TO finance_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA :"schema" TO finance_writer;
REVOKE INSERT ON :"schema".schema_migrations FROM finance_writer;

-- finance_reader: forecasts, outcomes, prices and sources for analysis; not
-- sign-in state or anyone's preferences.
GRANT SELECT ON ALL TABLES IN SCHEMA :"schema" TO finance_reader;
REVOKE SELECT ON :"schema".oauth_pending_logins, :"schema".oauth_sessions,
    :"schema".user_preferences, :"schema".user_accounts,
    :"schema".prediction_jobs, :"schema".paper_accounts, :"schema".paper_positions,
    :"schema".paper_orders FROM finance_reader;

-- Login roles. Re-running sets (rotates) their passwords.
SELECT 'CREATE ROLE finance_api LOGIN IN ROLE finance_writer'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_api') \gexec
SELECT 'CREATE ROLE finance_analyst LOGIN IN ROLE finance_reader'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_analyst') \gexec
ALTER ROLE finance_api PASSWORD :'app_password';
ALTER ROLE finance_analyst PASSWORD :'readonly_password';

-- Safety net: owning a table (directly, through a membership, or as a superuser)
-- bypasses every grant above, so stop if either login role could act as an owner.
SELECT format('DO $check$ BEGIN RAISE EXCEPTION %L; END $check$',
              'finance_api or finance_analyst can act as a table owner; remove that role membership')
WHERE EXISTS (
    SELECT FROM pg_tables t
    WHERE t.schemaname = :'schema'
      AND (pg_has_role('finance_api', t.tableowner, 'USAGE')
           OR pg_has_role('finance_analyst', t.tableowner, 'USAGE'))
) \gexec
