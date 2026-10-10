"""Where login state lives: process memory, never disk.

- Pending logins: `state` -> PKCE verifier, for 10 minutes, removed on first use.
- Sessions: a random opaque id (the only thing in the browser's cookie) -> the
  user's `sub`, email and name, for 8 hours.

Provider tokens are used once in the callback to read the user's profile and
then dropped. They're never stored, logged or written to disk, so there's
nothing to leak or commit. Restarting the server signs everyone out. With more
than one worker process, move this store to a shared server-side cache such as
Redis, never to files in the repo.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

LOGIN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=8)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
