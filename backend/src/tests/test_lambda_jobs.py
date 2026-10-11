"""Durable (AWS Lambda) prediction jobs, offline: event signing, the worker route and
the job routes with a fake store. The SQL itself is covered in test_database.py."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import lambda_jobs, main
from api.lambda_jobs import DatabaseJobStore
from oauth.provider import OAuthSettings
from oauth.routes import SESSION_COOKIE, get_settings, get_store
from oauth.sessions import MemoryStore

KEY = "test-signing-key-0123456789"
SETTINGS = OAuthSettings(client_id="id", client_secret="secret",
                         userinfo_url="https://idp.example/userinfo", cookie_secure=False)
USER = {"sub": "user-1", "email": "user@example.com", "name": "User One"}


class FakeJobStore(DatabaseJobStore):
    """The real signing, claim rules and views; rows in a dict instead of PostgreSQL."""

    def __init__(self):
        self.rows, self.sent = {}, []
        super().__init__(connect=None, invoke=self.sent.append, signing_key=KEY)

    def submit(self, owner, request):
        job_id = f"{len(self.rows):032d}"
        self.rows[job_id] = {"id": job_id, "owner": owner, "status": "queued", "result": None, "error": None,
                             "created_at": datetime.now(timezone.utc), "finished_at": None}
        self._invoke(self.sign({"job_id": job_id, "owner": owner, "request": request}))
        return self.get(job_id, owner)

    def get(self, job_id, owner):
        row = self.rows.get(job_id)
        return self._view(row) if row and row["owner"] == owner else None

    def claim(self, job_id):
        row = self.rows.get(job_id)
        if row and row["status"] == "queued":
            row["status"] = "running"
            return True
        return False

    def finish(self, job_id, result=None, error=None):
        row = self.rows[job_id]
        row.update(status="failed" if error else "succeeded", finished_at=datetime.now(timezone.utc),
                   result=result.model_dump(mode="json") if hasattr(result, "model_dump") else result, error=error)


@pytest.fixture
def env(monkeypatch, fake_llm):
    store, calls, durable = MemoryStore(), [], FakeJobStore()

    async def service(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return {"id": "p-1", "ticker": args[0], "direction": "up"}

    # The worker route calls get_llm() itself, so a dependency override doesn't reach it.
    route_llm = main.get_llm
    monkeypatch.setattr(main, "get_llm", lambda: fake_llm)
    monkeypatch.setattr(main, "_service", service)
    monkeypatch.setattr(main, "durable_jobs", lambda: durable)
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "true")
    main.prediction_limiter.clear()
    main.app.dependency_overrides = {
        route_llm: lambda: fake_llm, get_store: lambda: store, get_settings: lambda: SETTINGS,
    }
    with TestClient(main.app) as client:
        client.cookies.set(SESSION_COOKIE, store.create_session(USER))
        yield client, store, durable, calls
    main.app.dependency_overrides = {}
    main.prediction_limiter.clear()


def test_signature_covers_the_event_and_the_key():
    store = FakeJobStore()
    event = store.sign({"job_id": "a" * 32, "owner": "user:1", "request": {"ticker": "AAPL"}})
    assert store.verify(event)
    assert not store.verify({**event, "request": {"ticker": "TSLA"}})  # tampered
    assert not store.verify({k: v for k, v in event.items() if k != "signature"})
    assert not store.verify("not an event") and not store.verify({**event, "signature": 5})
    other = DatabaseJobStore(None, lambda e: None, "a-different-key-0123456789")
    assert not other.verify(event)


def test_a_short_signing_key_is_refused():
    with pytest.raises(RuntimeError, match="JOB_SIGNING_KEY"):
        DatabaseJobStore(None, lambda e: None, "short")


def test_backend_selection_from_env(monkeypatch):
    monkeypatch.delenv("JOBS_BACKEND", raising=False)
    assert lambda_jobs.from_env() is None  # default: the in-process JobStore
    monkeypatch.setenv("JOBS_BACKEND", "carrier-pigeon")
    with pytest.raises(RuntimeError, match="JOBS_BACKEND"):
        lambda_jobs.from_env()


def test_job_runs_through_a_signed_worker_event(env):
    client, _, durable, calls = env
    started = client.post("/prediction-jobs", json={"ticker": "nvda", "horizon_days": 3})
    assert started.status_code == 202
    job = started.json()
    assert job["status"] == "queued" and job["poll"] == f"/prediction-jobs/{job['job_id']}"
    assert calls == []  # nothing runs in the API request itself

    worker = client.post("/internal/lambda-events", json=durable.sent[0])  # what the Web Adapter posts
    assert worker.status_code == 200 and worker.json() == {"status": "done"}
    finished = client.get(job["poll"]).json()
    assert finished["status"] == "succeeded" and finished["prediction_id"] == "p-1"
    assert finished["prediction"]["ticker"] == "NVDA" and calls[0][2]["horizon_days"] == 3

    # A retried or replayed event does not run the forecast again.
    assert client.post("/internal/lambda-events", json=durable.sent[0]).json() == {"status": "ignored"}
    assert len(calls) == 1


def test_worker_route_refuses_unsigned_or_altered_events(env):
    client, _, durable, calls = env
    client.post("/prediction-jobs", json={"ticker": "AAPL"})
    event = durable.sent[0]
    assert client.post("/internal/lambda-events", json={**event, "request": {"ticker": "TSLA"}}).status_code == 403
    assert client.post("/internal/lambda-events", json={"job_id": event["job_id"]}).status_code == 403
    assert client.post("/internal/lambda-events", content=b"not json").status_code == 403
    assert calls == [] and durable.rows[event["job_id"]]["status"] == "queued"


def test_worker_route_is_closed_without_the_lambda_backend(monkeypatch):
    monkeypatch.setattr(main, "durable_jobs", lambda: None)
    with TestClient(main.app) as client:
        assert client.post("/internal/lambda-events", json={"job_id": "x", "signature": "y"}).status_code == 403


@pytest.mark.parametrize("error, status, words", [
    (HTTPException(422, "No eligible personas for those strategies and age bands."), 422, "No eligible"),
    (RuntimeError("provider secret detail"), 500, "Try again later"),
])
def test_failed_worker_reports_a_safe_error(env, monkeypatch, error, status, words):
    client, _, durable, _ = env

    async def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr(main, "_service", failing)
    job = client.post("/prediction-jobs", json={"ticker": "AAPL"}).json()
    client.post("/internal/lambda-events", json=durable.sent[0])
    finished = client.get(job["poll"]).json()
    assert finished["status"] == "failed" and finished["error"]["status_code"] == status
    assert words in finished["error"]["detail"] and "secret" not in str(finished)


def test_another_user_cannot_read_the_job(env):
    client, store, _, _ = env
    job = client.post("/prediction-jobs", json={"ticker": "AAPL"}).json()
    client.cookies.set(SESSION_COOKIE, store.create_session({**USER, "sub": "user-2"}))
    assert client.get(job["poll"]).status_code == 404


# --- Snowflake key file on a host with no persistent disk ---------------------------


def test_snowflake_key_is_written_from_base64(monkeypatch, tmp_path):
    import base64
    import os

    from snowflake_rag.connection import SnowflakeError, materialize_key_from_env

    monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY_B64", raising=False)
    assert materialize_key_from_env(str(tmp_path)) is None

    pem = b"-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_B64", base64.b64encode(pem).decode())
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_FILE", "a-laptop-path-from-.env.p8")
    path = materialize_key_from_env(str(tmp_path))
    assert path and open(path, "rb").read() == pem
    assert os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"] == path  # replaces the laptop path

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_B64", "not base64!!")
    with pytest.raises(SnowflakeError, match="base64"):
        materialize_key_from_env(str(fresh))
