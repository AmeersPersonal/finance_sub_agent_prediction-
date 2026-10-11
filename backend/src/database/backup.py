"""Back up the database with pg_dump and keep a bounded history.

    python -m database.backup            # from backend/src: dump, then prune old dumps
    python -m database.backup --prune    # only prune

Dumps go to backend/data/backups/ (gitignored) in pg_dump's custom format;
restore one with `pg_restore --clean --if-exists --no-owner --dbname <target> <file>`.
Kept: the newest dump of each of the last 7 days, 4 ISO weeks and 12 months
(policy: docs/retention-and-access.md). Needs PostgreSQL's `pg_dump` on PATH,
the server's major version or newer.

The connection comes from DATABASE_URL and reaches pg_dump through PG*
environment variables, never its command line, so the password doesn't show
in process listings, and no message here ever includes the URL.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
NAME_FORMAT = "finance-%Y%m%dT%H%M%SZ.dump"
KEEP = {"daily": 7, "weekly": 4, "monthly": 12}
# libpq keyword -> the environment variable pg_dump reads it from.
PG_ENV = {
    "host": "PGHOST", "port": "PGPORT", "user": "PGUSER", "password": "PGPASSWORD",
    "dbname": "PGDATABASE", "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT",
    "connect_timeout": "PGCONNECT_TIMEOUT",
}


class BackupError(RuntimeError):
    """A user-safe failure; never includes the connection URL."""


def backup_time(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.name, NAME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None  # not one of ours: never pruned


def to_keep(times: Iterable[datetime], daily: int = KEEP["daily"], weekly: int = KEEP["weekly"],
            monthly: int = KEEP["monthly"]) -> set[datetime]:
    """Grandfather-father-son: the newest backup of each of the last `daily` days,
    `weekly` ISO weeks and `monthly` months that have one."""
    newest_first = sorted(times, reverse=True)
    keep: set[datetime] = set()
    periods: tuple[tuple[Callable[[datetime], object], int], ...] = (
        (lambda t: t.date(), daily),
        (lambda t: t.isocalendar()[:2], weekly),
        (lambda t: (t.year, t.month), monthly),
    )
    for period, count in periods:
        seen: list[object] = []
        for t in newest_first:
            key = period(t)
            if key in seen:
                continue
            if len(seen) == count:
                break
            seen.append(key)
            keep.add(t)
    return keep


def prune(directory: Path = BACKUP_DIR) -> list[Path]:
    """Delete our dumps outside the retention schedule; returns what was deleted."""
    dumps = {t: p for p in directory.glob("finance-*.dump") if (t := backup_time(p))}
    keep = to_keep(dumps)
    removed = [p for t, p in sorted(dumps.items()) if t not in keep]
    for path in removed:
        path.unlink()
    return removed


def pg_environment(url: str) -> dict[str, str]:
    """PG* variables for `url`, with the same TLS default as `database.connection.connect`."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        options = conninfo_to_dict(url)
    except Exception:
        raise BackupError("DATABASE_URL could not be parsed.") from None
    unsupported = sorted(set(options) - set(PG_ENV))
    if unsupported:
        raise BackupError(f"Unsupported connection options for backups: {', '.join(unsupported)}")
    host = str(options.get("host", ""))
    if host and host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
        options.setdefault("sslmode", "require")
    return {PG_ENV[key]: str(value) for key, value in options.items()}


def run_backup(url: str, directory: Path = BACKUP_DIR, now: datetime | None = None,
               runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Path:
    """Dump to a temporary name and rename it when pg_dump succeeds, so a partial
    dump never counts as a backup."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (now or datetime.now(timezone.utc)).strftime(NAME_FORMAT)
    partial = target.with_suffix(".partial")
    environment = {**os.environ, **pg_environment(url)}
    try:
        result = runner(["pg_dump", "--format=custom", "--no-owner", "--file", str(partial)],
                        env=environment, capture_output=True, text=True)
    except FileNotFoundError:
        raise BackupError("pg_dump was not found; install the PostgreSQL client tools.") from None
    if result.returncode != 0:
        partial.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed (exit {result.returncode}). Check connectivity and the pg_dump version.")
    partial.replace(target)
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m database.backup", description=__doc__.split("\n\n")[0])
    parser.add_argument("--prune", action="store_true", help="only delete dumps outside the retention schedule")
    parser.add_argument("--dir", type=Path, default=BACKUP_DIR, help="where dumps live (default backend/data/backups)")
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    try:
        if not args.prune:
            url = os.environ.get("DATABASE_URL", "").strip()
            if not url:
                raise BackupError("Set DATABASE_URL in the backend environment first.")
            print(f"Saved {run_backup(url, args.dir)}")
        removed = prune(args.dir)
    except BackupError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Pruned {len(removed)} old dump(s)." if removed else "Nothing to prune.")


if __name__ == "__main__":
    main()
