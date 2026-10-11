"""Connections configured through the environment, without exposing credentials."""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


class DatabaseError(RuntimeError):
    """A user-safe database failure; never includes a DSN or driver diagnostic."""


@contextmanager
def connect(url: str | None = None):
    """Commit on success, roll back on failure, and always close the connection."""
    url = url or os.environ.get("DATABASE_URL")
    if not url or not url.strip():
        raise DatabaseError("Set DATABASE_URL in the backend environment first.")
    try:
        options = conninfo_to_dict(url)
        options.setdefault("connect_timeout", "10")
        host = options.get("host", "")
        if host and host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
            options.setdefault("sslmode", "require")
        with psycopg.connect(**options, row_factory=dict_row) as connection:
            yield connection
    except (psycopg.Error, ValueError):
        raise DatabaseError(
            "Database operation failed. Check connectivity, credentials, permissions, and migrations."
        ) from None
