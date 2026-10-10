"""Where login state lives: process memory by default, or PostgreSQL; never files.

- Pending logins: `state` -> PKCE verifier, for 10 minutes, removed on first use.
- Sessions: a random opaque id (the only thing in the browser's cookie) -> the
  user's `sub`, email and name, for 8 hours.

Provider tokens are used once in the callback to read the user's profile and
then dropped. They're never stored, logged or written to disk, so there's
nothing to leak or commit.

`MemoryStore` (the default) is per process: restarting signs everyone out and
a second worker wouldn't see the first one's sign-ins. With more than one
worker, set `OAUTH_SESSION_STORE=database` to use `DatabaseStore`, which shares
the state through PostgreSQL tables (migration 005) and keeps only hashes of
the state values and session ids.
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Protocol

LOGIN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=8)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore(Protocol):
    def begin_login(self) -> tuple[str, str]: ...
    def finish_login(self, state: str) -> str | None: ...
    def create_session(self, user: dict[str, Any]) -> str: ...
    def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    def end_session(self, session_id: str) -> None: ...


class MemoryStore:
    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[str, datetime]] = {}
        self._sessions: dict[str, tuple[dict[str, Any], datetime]] = {}

    def _purge(self, now: datetime) -> None:
        self._pending = {k: v for k, v in self._pending.items() if v[1] > now}
        self._sessions = {k: v for k, v in self._sessions.items() if v[1] > now}

    def begin_login(self) -> tuple[str, str]:
        """A new (state, PKCE verifier) pair."""
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._pending[state] = (verifier, now + LOGIN_TTL)
        return state, verifier

    def finish_login(self, state: str) -> str | None:
        """The verifier for `state`, once. None if unknown, expired or already used."""
        with self._lock:
            self._purge(self._clock())
            entry = self._pending.pop(state, None)
        return entry[0] if entry else None

    def create_session(self, user: dict[str, Any]) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = (user, self._clock() + SESSION_TTL)
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge(self._clock())
            entry = self._sessions.get(session_id)
        return entry[0] if entry else None

    def end_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


def _digest(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


class DatabaseStore:
    """The same contract as `MemoryStore`, shared by every worker through PostgreSQL.

    `connect` is a context manager factory yielding a dict-row connection that
    commits on exit (`database.connection.connect`); tests can pass their own.
    Expired rows are deleted whenever a new login or session is written.
    """

    def __init__(self, connect: Callable[[], Any], clock: Callable[[], datetime] = _utc_now) -> None:
        self._connect = connect
        self._clock = clock

    def begin_login(self) -> tuple[str, str]:
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        now = self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_pending_logins WHERE expires_at <= %s", (now,))
            connection.execute(
                "INSERT INTO oauth_pending_logins (state_hash, verifier, expires_at) VALUES (%s, %s, %s)",
                (_digest(state), verifier, now + LOGIN_TTL),
            )
        return state, verifier

    def finish_login(self, state: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "DELETE FROM oauth_pending_logins WHERE state_hash = %s RETURNING verifier, expires_at",
                (_digest(state),),
            ).fetchone()
        return row["verifier"] if row and row["expires_at"] > self._clock() else None

    def create_session(self, user: dict[str, Any]) -> str:
        from psycopg.types.json import Jsonb

        session_id, now = secrets.token_urlsafe(32), self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_sessions WHERE expires_at <= %s", (now,))
            connection.execute(
                "INSERT INTO oauth_sessions (session_hash, user_profile, expires_at) VALUES (%s, %s, %s)",
                (_digest(session_id), Jsonb(user), now + SESSION_TTL),
            )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_profile, expires_at FROM oauth_sessions WHERE session_hash = %s",
                (_digest(session_id),),
            ).fetchone()
        return row["user_profile"] if row and row["expires_at"] > self._clock() else None

    def end_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_sessions WHERE session_hash = %s", (_digest(session_id),))


def store_from_env() -> SessionStore:
    """`OAUTH_SESSION_STORE`: `memory` (default) or `database` (needs DATABASE_URL and migration 005)."""
    kind = (os.getenv("OAUTH_SESSION_STORE") or "memory").strip().lower()
    if kind == "memory":
        return MemoryStore()
    if kind == "database":
        from database.connection import connect

        return DatabaseStore(connect)
    raise RuntimeError(f"Unknown OAUTH_SESSION_STORE {kind!r}; use memory or database")
