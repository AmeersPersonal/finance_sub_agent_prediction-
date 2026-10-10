"""Apply versioned SQL migrations explicitly, never during prediction startup."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from dotenv import load_dotenv

from database.connection import DatabaseError, connect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def migrate(connection, *, timescale: bool = False) -> list[str]:
    applied = []
    with connection.transaction():
        # Serialize migration runners sharing this database.
        connection.execute("SELECT pg_advisory_xact_lock(683209741)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if "timescale" in path.name and not timescale:
                continue
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            previous = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE name = %s", (path.name,)
            ).fetchone()
            if previous:
                if previous["checksum"] != checksum:
                    raise DatabaseError(f"Applied migration {path.name} has changed; add a new migration instead.")
                continue
            connection.execute(sql, prepare=False)
            connection.execute(
                "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )
            applied.append(path.name)
    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the application's PostgreSQL schema")
    parser.add_argument("--timescale", action="store_true", help="also enable optional Timescale hypertables")
    args = parser.parse_args()
    load_dotenv(ENV_FILE)
    try:
        with connect() as connection:
            applied = migrate(connection, timescale=args.timescale)
    except DatabaseError as exc:
        parser.exit(1, f"{exc}\n")
    print("Applied: " + ", ".join(applied) if applied else "Schema is up to date.")


if __name__ == "__main__":
    main()
