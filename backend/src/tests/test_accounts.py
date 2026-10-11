"""Email/password accounts (POST /signup, POST /login) and password hashing.
The repository is an in-memory fake; sessions use MemoryStore. No network."""

import pytest
from fastapi.testclient import TestClient

from api import main
from api import accounts
from oauth.passwords import hash_password, verify_password
from oauth.provider import OAuthSettings
from oauth.routes import SESSION_COOKIE, get_settings, get_store
from oauth.sessions import MemoryStore

SIGNUP = {"firstName": "Maya", "lastName": "Lopez", "email": "Maya@Example.com", "password": "correct horse"}
SETTINGS = OAuthSettings(client_id=None, client_secret=None, cookie_secure=False)


class FakeAccounts:
    """Stands in for DatabaseRepository's create_account / get_account."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def __call__(self, method, *args, **kwargs):
        if method == "create_account":
            email = kwargs["email"]
            if email in self.rows:
                return None
            self.rows[email] = {"id": len(self.rows) + 1, "email": email, "password_hash": kwargs["password_hash"],
                                "first_name": kwargs["first_name"], "last_name": kwargs["last_name"]}
            return self.rows[email]["id"]
        if method == "get_account":
            return self.rows.get(args[0])
        raise AssertionError(method)


@pytest.fixture
def client(monkeypatch):
    accounts.attempts.clear()
    repo, store = FakeAccounts(), MemoryStore()
    monkeypatch.setattr(accounts, "_repo", repo)
    monkeypatch.setattr(main, "_read", lambda method, *args, **kwargs: None)
    main.app.dependency_overrides = {get_store: lambda: store, get_settings: lambda: SETTINGS}
    try:
        with TestClient(main.app) as test_client:
            test_client.repo = repo
            yield test_client
    finally:
        main.app.dependency_overrides = {}
        accounts.attempts.clear()


# --- passwords ---------------------------------------------------------------------


def test_password_hash_round_trip_and_salting():
    first, second = hash_password("s3cret pass"), hash_password("s3cret pass")
    assert first != second and first.startswith("scrypt$")  # random salt per hash
    assert verify_password("s3cret pass", first) and verify_password("s3cret pass", second)
    assert not verify_password("s3cret pasS", first)
    assert "s3cret" not in first


@pytest.mark.parametrize("stored", ["", "plain", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$AA==$AA==",
                                    "scrypt$1073741824$8$1$AA==$AA==", "scrypt$16384$8$1$!!$AA=="])
def test_malformed_or_hostile_hashes_never_verify(stored):
    assert not verify_password("anything", stored)


# --- sign-up -------------------------------------------------------------------------


def test_signup_creates_an_account_with_a_hashed_password(client):
    response = client.post("/signup", json=SIGNUP)
    assert response.status_code == 201
    assert response.json()["user"] == {"sub": "password:1", "email": "maya@example.com",
                                       "name": "Maya Lopez", "provider": "password"}
    row = client.repo.rows["maya@example.com"]
    assert row["password_hash"] != SIGNUP["password"] and verify_password(SIGNUP["password"], row["password_hash"])
    assert SESSION_COOKIE not in response.cookies  # the form sends people to sign in next


def test_duplicate_email_is_409_regardless_of_case(client):
    assert client.post("/signup", json=SIGNUP).status_code == 201
    again = client.post("/signup", json={**SIGNUP, "email": " MAYA@example.COM "})
    assert again.status_code == 409 and "already exists" in again.json()["detail"]


@pytest.mark.parametrize("change", [
    {"email": "not-an-email"}, {"email": "a@b"}, {"email": ""},
    {"password": "short"}, {"password": "x" * 257},
    {"firstName": ""}, {"firstName": "   "}, {"lastName": "x" * 101},
])
def test_invalid_signup_is_422(client, change):
    assert client.post("/signup", json={**SIGNUP, **change}).status_code == 422


def test_signup_needs_every_field(client):
    for field in SIGNUP:
        body = {k: v for k, v in SIGNUP.items() if k != field}
        assert client.post("/signup", json=body).status_code == 422


# --- sign-in -------------------------------------------------------------------------


def test_login_starts_a_session_the_rest_of_the_api_recognizes(client):
    client.post("/signup", json=SIGNUP)
    response = client.post("/login", json={"email": "MAYA@example.com", "password": SIGNUP["password"]})
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "maya@example.com"
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Path=/" in cookie
    me = client.get("/oauth/me")
    assert me.status_code == 200 and me.json()["user"]["name"] == "Maya Lopez"
    # Preferences key on the namespaced account id, never the email.
    assert main.account_reference(me.json()["user"], SETTINGS) == "password:1"
    assert client.post("/oauth/logout").status_code == 200
    assert client.get("/oauth/me").status_code == 401


@pytest.mark.parametrize("email, password", [
    ("maya@example.com", "wrong password"),
    ("nobody@example.com", "correct horse"),
    ("not an email", "correct horse"),
])
def test_wrong_email_or_password_get_the_same_401(client, email, password):
    client.post("/signup", json=SIGNUP)
    response = client.post("/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    assert SESSION_COOKIE not in response.cookies


@pytest.mark.parametrize("body", [{}, {"email": "maya@example.com"}, {"email": "maya@example.com", "password": ""},
                                  {"email": "maya@example.com", "password": "x" * 257}])
def test_malformed_login_is_422(client, body):
    assert client.post("/login", json=body).status_code == 422


def test_repeated_attempts_are_rate_limited(client):
    client.post("/signup", json=SIGNUP)
    for _ in range(accounts.attempts.limit):
        assert client.post("/login", json={"email": "maya@example.com", "password": "nope"}).status_code == 401
    blocked = client.post("/login", json={"email": "maya@example.com", "password": SIGNUP["password"]})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # Another email from the same address still gets its own attempts.
    assert client.post("/login", json={"email": "other@example.com", "password": "nope"}).status_code == 401


def test_database_outage_is_a_503(client, monkeypatch):
    def down(*args, **kwargs):
        raise main.DatabaseError("connection refused")
    monkeypatch.setattr(accounts, "_repo", down)
    assert client.post("/signup", json=SIGNUP).status_code == 503
    assert client.post("/login", json={"email": "maya@example.com", "password": "whatever1"}).status_code == 503


def test_forecast_quota_belongs_to_the_signed_in_account(client, monkeypatch):
    """With sign-in required, a password account can create forecasts like a Google one."""
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "true")
    calls = []

    async def service(method, *args, **kwargs):
        calls.append(args[0])
        return {"id": "p-1", "ticker": args[0], "direction": "up"}

    monkeypatch.setattr(main, "_service", service)
    main.app.dependency_overrides[main.get_llm] = lambda: object()
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 401
    client.post("/signup", json=SIGNUP)
    client.post("/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 201 and calls == ["AAPL"]
