"""database.backup without a database: retention schedule, pruning, and how pg_dump is called."""

import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from database.backup import NAME_FORMAT, BackupError, backup_time, pg_environment, prune, run_backup, to_keep

UTC = timezone.utc


def test_retention_keeps_the_newest_per_day_week_and_month():
    start = datetime(2025, 1, 1, 3, tzinfo=UTC)
    daily = [start + timedelta(days=d) for d in range(400)]  # one dump a day for 400 days
    twice_today = daily + [daily[-1] + timedelta(hours=6)]
    keep = to_keep(twice_today)
    newest = twice_today[-1]
    assert newest in keep and daily[-1] not in keep  # one per day: the later dump that day
    days = {t.date() for t in keep if (newest - t).days < 7}
    assert len(days) == 7
    months = {(t.year, t.month) for t in keep}
    assert len(months) == 12  # the current month plus 11 earlier ones
    assert min(keep) > start  # the oldest months fell off
    assert len(keep) <= 7 + 4 + 12
    assert to_keep([]) == set()


def test_prune_deletes_only_our_dumps_outside_the_schedule(tmp_path):
    now = datetime(2026, 10, 10, 2, tzinfo=UTC)
    for days in range(40):
        (tmp_path / (now - timedelta(days=days)).strftime(NAME_FORMAT)).write_bytes(b"dump")
    (tmp_path / "finance-manual-copy.dump").write_bytes(b"keep me")
    (tmp_path / "notes.txt").write_text("keep me")
    removed = prune(tmp_path)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert removed and all(backup_time(p) for p in removed)
    assert "finance-manual-copy.dump" in left and "notes.txt" in left
    assert len([n for n in left if backup_time(tmp_path / n)]) == len(to_keep(
        now - timedelta(days=d) for d in range(40)))


def test_connection_goes_through_the_environment_never_argv(tmp_path):
    url = "postgresql://finance:s3cret-pass@db.example.com:5433/finance"
    calls = []

    def fake_pg_dump(args, env, capture_output, text):
        calls.append((args, env))
        target = args[args.index("--file") + 1]
        with open(target, "wb") as f:
            f.write(b"PGDMP")
        return subprocess.CompletedProcess(args, 0, "", "")

    path = run_backup(url, tmp_path, datetime(2026, 10, 10, 2, 30, tzinfo=UTC), runner=fake_pg_dump)
    assert path.name == "finance-20261010T023000Z.dump" and path.read_bytes() == b"PGDMP"
    args, env = calls[0]
    assert "s3cret-pass" not in " ".join(args) and "db.example.com" not in " ".join(args)
    assert env["PGPASSWORD"] == "s3cret-pass" and env["PGHOST"] == "db.example.com"
    assert env["PGPORT"] == "5433" and env["PGDATABASE"] == "finance"
    assert env["PGSSLMODE"] == "require"  # remote hosts get TLS, as in database.connection


def test_failed_dump_leaves_no_backup_and_no_secret_in_the_message(tmp_path):
    def failing(args, env, capture_output, text):
        open(args[args.index("--file") + 1], "wb").close()
        return subprocess.CompletedProcess(args, 1, "", "FATAL: password authentication failed")

    with pytest.raises(BackupError) as error:
        run_backup("postgresql://u:hunter2@localhost/finance", tmp_path, runner=failing)
    assert "hunter2" not in str(error.value) and list(tmp_path.iterdir()) == []


def test_local_connections_keep_their_tls_setting_and_odd_options_are_refused():
    assert "PGSSLMODE" not in pg_environment("postgresql://u@localhost/finance")
    assert pg_environment("postgresql:///finance?host=/var/run/postgresql")["PGHOST"] == "/var/run/postgresql"
    with pytest.raises(BackupError, match="options") as error:
        pg_environment("postgresql://u:pw@localhost/finance?options=-csearch_path%3Dx")
    assert "pw" not in str(error.value)
