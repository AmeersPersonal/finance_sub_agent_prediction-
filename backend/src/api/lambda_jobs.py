"""Forecast jobs for AWS Lambda: state in PostgreSQL, work in a second invocation.

A Lambda instance is frozen as soon as its response is sent, so the in-process
`JobStore` (api/state.py) can't run a job "in the background", and a poll can land
on another instance. With `JOBS_BACKEND=lambda`:

1. `POST /prediction-jobs` inserts a `queued` row and invokes this same function
   asynchronously with a signed event (`submit`).
2. The Lambda Web Adapter hands that event to `POST /internal/lambda-events`
   (`AWS_LWA_PASS_THROUGH_PATH`), which verifies the signature, claims the row
   (`queued` -> `running`, once) and runs the forecast (`claim`, `finish`).
3. `GET /prediction-jobs/{id}` reads the row, owner-checked (`get`).

The signature is an HMAC-SHA256 over the event with `JOB_SIGNING_KEY`, so the
internal route does nothing for anyone who can reach the function URL but doesn't
hold the key. The claim makes a replayed or retried event a no-op.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

JOB_TTL = timedelta(hours=1)  # finished jobs are kept this long, like JobStore
STALE_AFTER = timedelta(minutes=20)  # a worker that died mid-run; Lambda's limit is 15 min
MAX_ACTIVE_PER_OWNER = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(event: dict[str, Any]) -> bytes:
    body = {k: v for k, v in event.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return None if value is None else Jsonb(value)


class DatabaseJobStore:
    """Same job view as `api.state.Job.view()`, kept in the `prediction_jobs` table.

    `connect` is a context manager factory yielding a dict-row connection that
    commits on exit (`database.connection.connect`). `invoke` sends the signed
    event to the worker (a Lambda async invoke in production).
    """

    def __init__(self, connect: Callable[[], Any], invoke: Callable[[dict[str, Any]], None],
                 signing_key: str, clock: Callable[[], datetime] = _now) -> None:
        if len(signing_key) < 16:
            raise RuntimeError("Set JOB_SIGNING_KEY (16+ characters) to use JOBS_BACKEND=lambda")
        self._connect, self._invoke, self._clock = connect, invoke, clock
        self._key = signing_key.encode("utf-8")

    # --- signing ---------------------------------------------------------------

    def sign(self, event: dict[str, Any]) -> dict[str, Any]:
        digest = hmac.new(self._key, _canonical(event), hashlib.sha256).hexdigest()
        return {**event, "signature": digest}

    def verify(self, event: Any) -> bool:
        if not isinstance(event, dict) or not isinstance(event.get("signature"), str):
            return False
        expected = hmac.new(self._key, _canonical(event), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, event["signature"])

    # --- the API side ----------------------------------------------------------

    def submit(self, owner: str, request: dict[str, Any]) -> dict[str, Any]:
        """Queue a job for `request` (the PredictionRequest as JSON) and start its worker."""
        now = self._clock()
        job_id = uuid4().hex
        with self._connect() as connection:
            connection.execute("DELETE FROM prediction_jobs WHERE finished_at < %s", (now - JOB_TTL,))
            active = connection.execute(
                "SELECT count(*) AS n FROM prediction_jobs WHERE owner = %s AND finished_at IS NULL AND created_at > %s",
                (owner, now - STALE_AFTER),
            ).fetchone()["n"]
            if active >= MAX_ACTIVE_PER_OWNER:
                raise HTTPException(status_code=503, detail="Too many forecasts are running. Try again shortly.")
            connection.execute(
                "INSERT INTO prediction_jobs (id, owner, status, created_at) VALUES (%s, %s, 'queued', %s)",
                (job_id, owner, now),
            )
        try:
            self._invoke(self.sign({"job_id": job_id, "owner": owner, "request": request, "issued": now.isoformat()}))
        except Exception:
            self.finish(job_id, error={"status_code": 503, "detail": "Could not start the forecast. Try again shortly."})
            raise HTTPException(status_code=503, detail="Could not start the forecast. Try again shortly.") from None
        return self.get(job_id, owner) or {"job_id": job_id, "status": "queued"}

    def get(self, job_id: str, owner: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, owner, status, created_at, finished_at, result, error FROM prediction_jobs "
                "WHERE id = %s AND owner = %s", (job_id, owner),
            ).fetchone()
        return self._view(row) if row else None

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        status, error, finished = row["status"], row["error"], row["finished_at"]
        if status in ("queued", "running") and self._clock() - row["created_at"] > STALE_AFTER:
            status, finished = "failed", self._clock()
            error = {"status_code": 500, "detail": "The forecast failed. Try again later."}
        prediction = row["result"]
        return {
            "job_id": row["id"], "status": status,
            "created_at": row["created_at"].isoformat(),
            "finished_at": finished.isoformat() if finished else None,
            "prediction_id": prediction.get("id") if isinstance(prediction, dict) else None,
            "prediction": prediction, "error": error,
        }

    # --- the worker side -------------------------------------------------------

    def claim(self, job_id: str) -> bool:
        """Move a queued job to running. False if it isn't queued: a replay, a retry, an unknown id."""
        with self._connect() as connection:
            row = connection.execute(
                "UPDATE prediction_jobs SET status = 'running', started_at = %s "
                "WHERE id = %s AND status = 'queued' RETURNING id", (self._clock(), job_id),
            ).fetchone()
        return row is not None

    def finish(self, job_id: str, result: Any = None, error: dict[str, Any] | None = None) -> None:
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                "UPDATE prediction_jobs SET status = %s, finished_at = %s, result = %s, error = %s "
                "WHERE id = %s AND finished_at IS NULL",
                ("failed" if error else "succeeded", self._clock(), _json(result), _json(error), job_id),
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM prediction_jobs")


def _lambda_invoker() -> Callable[[dict[str, Any]], None]:
    import boto3  # installed in the Lambda image only (backend/requirements-lambda.txt)

    function = os.environ["AWS_LAMBDA_FUNCTION_NAME"]
    client = boto3.client("lambda")

    def invoke(event: dict[str, Any]) -> None:
        client.invoke(FunctionName=function, InvocationType="Event", Payload=json.dumps(event).encode("utf-8"))

    return invoke


def from_env() -> DatabaseJobStore | None:
    """`JOBS_BACKEND`: unset or `memory` -> None (use the in-process JobStore); `lambda` -> this store."""
    kind = (os.getenv("JOBS_BACKEND") or "memory").strip().lower()
    if kind == "memory":
        return None
    if kind == "lambda":
        from database.connection import connect

        return DatabaseJobStore(connect, _lambda_invoker(), os.getenv("JOB_SIGNING_KEY") or "")
    raise RuntimeError(f"Unknown JOBS_BACKEND {kind!r}; use memory or lambda")
