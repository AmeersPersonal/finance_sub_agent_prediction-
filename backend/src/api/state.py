"""In-process API state: the prediction rate limit, background prediction jobs and
the cached score report.

All three live in this process's memory, so run the API as one worker
(`uvicorn` without `--workers`, as the Dockerfile does). With several workers
each would keep its own limit, jobs and cache; OAuth sign-ins can already be
shared (`OAUTH_SESSION_STORE=database`), these can't yet.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

log = logging.getLogger(__name__)
MAX_TRACKED_CALLERS = 10_000


class RateLimiter:
    """At most `limit` acquisitions per caller in any `window` seconds (sliding window).
    `limit` 0 turns it off."""

    def __init__(self, limit: int, window: float = 3600.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> float | None:
        """Record one call for `key`. None if allowed, else seconds until one is."""
        if self.limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            if len(self._calls) > MAX_TRACKED_CALLERS:  # forget callers idle for a whole window
                self._calls = {k: v for k, v in self._calls.items() if v and v[-1] > now - self.window}
            calls = self._calls.setdefault(key, deque())
            while calls and calls[0] <= now - self.window:
                calls.popleft()
            if len(calls) >= self.limit:
                return calls[0] + self.window - now
            calls.append(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    owner: str
    status: str = "queued"  # queued -> running -> succeeded | failed
    created_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    task: asyncio.Task | None = None

    def view(self) -> dict[str, Any]:
        prediction = self.result.model_dump(mode="json") if hasattr(self.result, "model_dump") else self.result
        return {
            "job_id": self.id, "status": self.status,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "prediction_id": (prediction or {}).get("id") if isinstance(prediction, dict) else None,
            "prediction": prediction, "error": self.error,
        }


class JobStore:
    """Runs predictions in the background so a request doesn't stay open for a minute.

    A job is visible only to the caller that created it. Finished jobs are kept
    for `ttl` seconds; at most `max_active` run at once, more get a 503.
    """

    def __init__(self, ttl: float = 3600.0, max_active: int = 20) -> None:
        self.ttl, self.max_active = ttl, max_active
        self._jobs: dict[str, Job] = {}

    def _purge(self) -> None:
        cutoff = _now().timestamp() - self.ttl
        for job_id in [j.id for j in self._jobs.values()
                       if j.finished_at and j.finished_at.timestamp() < cutoff]:
            del self._jobs[job_id]

    def submit(self, owner: str, work: Callable[[], Awaitable[Any]]) -> Job:
        self._purge()
        if sum(j.finished_at is None for j in self._jobs.values()) >= self.max_active:
            raise HTTPException(status_code=503, detail="Too many forecasts are running. Try again shortly.")
        job = Job(id=uuid4().hex, owner=owner)
        self._jobs[job.id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job, work))
        return job

    async def _run(self, job: Job, work: Callable[[], Awaitable[Any]]) -> None:
        job.status = "running"
        try:
            job.result = await work()
            job.status = "succeeded"
        except HTTPException as exc:  # already a sanitized, user-facing error
            job.status, job.error = "failed", {"status_code": exc.status_code, "detail": exc.detail}
        except Exception as exc:  # never leak provider or database details
            log.warning("prediction job %s failed: %s", job.id, type(exc).__name__)
            job.status = "failed"
            job.error = {"status_code": 500, "detail": "The forecast failed. Try again later."}
        finally:
            job.finished_at = _now()
            job.task = None

    def get(self, job_id: str, owner: str) -> Job | None:
        self._purge()
        job = self._jobs.get(job_id)
        return job if job is not None and job.owner == owner else None

    def clear(self) -> None:
        self._jobs.clear()


class ScoreCache:
    """The last score report for `ttl` seconds. Scoring downloads closes for every
    saved ticker, so concurrent callers wait for one computation instead of each
    starting their own. `ttl` 0 turns caching off."""

    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self._clock = ttl, clock
        self._lock = threading.Lock()
        self._value: tuple[float, datetime, Any] | None = None

    def get(self, compute: Callable[[], Any], fresh: bool = False) -> tuple[Any, datetime]:
        """(report, when it was computed). Blocking: call it from a worker thread."""
        with self._lock:
            if not fresh and self._value is not None and self._clock() - self._value[0] < self.ttl:
                return self._value[2], self._value[1]
            report = compute()
            self._value = (self._clock(), _now(), report)
            return report, self._value[1]

    def clear(self) -> None:
        with self._lock:
            self._value = None
