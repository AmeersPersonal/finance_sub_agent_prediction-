"""Paper-trading arithmetic and routes: pure ledger and a faked service, no database."""

from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from api import main
from oauth.provider import OAuthSettings
from oauth.routes import SESSION_COOKIE, get_settings, get_store
from oauth.sessions import MemoryStore
from paper.ledger import OrderRejected, Position, apply_order, shares_for_dollars, value_account

SETTINGS = OAuthSettings(client_id="id", client_secret="secret",
                         userinfo_url="https://idp.example/userinfo", cookie_secure=False)
USER = {"sub": "user-1", "email": "user@example.com", "name": "User One"}


# --- ledger -----------------------------------------------------------------------


def test_buy_reduces_cash_and_opens_a_position():
    fill = apply_order(D("1000"), None, side="buy", symbol="AAPL", shares=D("4"), price=D("123.45"))
    assert fill.total == D("493.80")
    assert fill.cash == D("506.20")
    assert fill.position == Position("AAPL", D("4"), D("123.45"))
    assert fill.realized_pnl is None


def test_second_buy_averages_the_cost():
    held = Position("AAPL", D("10"), D("100"))
    fill = apply_order(D("5000"), held, side="buy", symbol="AAPL", shares=D("10"), price=D("120"))
    assert fill.position.shares == D("20")
    assert fill.position.average_cost == D("110")


def test_partial_sell_realizes_profit_and_keeps_average_cost():
    held = Position("AAPL", D("10"), D("100"))
    fill = apply_order(D("0"), held, side="sell", symbol="AAPL", shares=D("4"), price=D("125"))
    assert fill.total == D("500.00")
    assert fill.cash == D("500.00")
    assert fill.realized_pnl == D("100.00")
    assert fill.position == Position("AAPL", D("6"), D("100"))


def test_selling_everything_closes_the_position_and_can_realize_a_loss():
    held = Position("AAPL", D("2.5"), D("200"))
    fill = apply_order(D("10"), held, side="sell", symbol="AAPL", shares=D("2.5"), price=D("180"))
    assert fill.position is None
    assert fill.realized_pnl == D("-50.00")
    assert fill.cash == D("460.00")


@pytest.mark.parametrize("cash, position, side, shares, message", [
    (D("100"), None, "buy", D("3"), "Not enough cash"),
    (D("100"), None, "sell", D("1"), "don't own any"),
    (D("100"), Position("AAPL", D("1"), D("10")), "sell", D("2"), "tried to sell"),
    (D("100"), None, "buy", D("0"), "too small"),
])
def test_rejected_orders(cash, position, side, shares, message):
    with pytest.raises(OrderRejected, match=message):
        apply_order(cash, position, side=side, symbol="AAPL", shares=shares, price=D("50"))


def test_dollar_orders_never_overspend():
    shares = shares_for_dollars(D("100"), D("3"))
    assert shares == D("33.333333")
    assert shares * D("3") <= D("100")
    with pytest.raises(OrderRejected, match="too small"):
        apply_order(D("100"), None, side="buy", symbol="AAPL",
                    shares=shares_for_dollars(D("0.0001"), D("500")), price=D("500"))


def test_account_value_and_pnl():
    holdings = [(Position("AAPL", D("10"), D("100")), D("110")), (Position("MSFT", D("5"), D("200")), D("190"))]
    summary = value_account(D("8000"), D("10000"), holdings)
    assert summary["market_value"] == D("2050.00")
    assert summary["equity"] == D("10050.00")
    assert summary["unrealized_pnl"] == D("50.00")
    assert summary["total_pnl"] == D("50.00")
    assert summary["total_return_pct"] == D("0.50")


# --- routes -----------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch):
    """(client, store, calls): `_paper_call` is replaced by a recorder."""
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "true")
    store, calls = MemoryStore(), []

    def paper_call(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        if method == "place_order" and kwargs["shares"] == D("999"):
            raise OrderRejected("Not enough cash")
        return {"account": {"cash": D("1")}, "positions": [], "orders": []}

    monkeypatch.setattr(main, "_paper_call", paper_call)
    main.app.dependency_overrides = {get_store: lambda: store, get_settings: lambda: SETTINGS}
    try:
        with TestClient(main.app) as client:
            yield client, store, calls
    finally:
        main.app.dependency_overrides = {}


def sign_in(client, store, user=USER):
    client.cookies.set(SESSION_COOKIE, store.create_session(user))


ORDER = {"ticker": " aapl ", "side": "buy", "shares": 2, "idempotency_key": "order-key-0001"}


def test_paper_routes_need_sign_in(env):
    client, _, calls = env
    assert client.get("/paper/account").status_code == 401
    assert client.get("/paper/orders").status_code == 401
    assert client.post("/paper/orders", json=ORDER).status_code == 401
    assert client.post("/paper/reset").status_code == 401
    assert calls == []


def test_order_is_normalized_and_scoped_to_the_signed_in_account(env):
    client, store, calls = env
    sign_in(client, store)
    response = client.post("/paper/orders", json={**ORDER, "prediction_id": "0b9d6e0e2c3a4f1b8f5d7a1c2e3f4a5b"})
    assert response.status_code == 201
    method, args, kwargs = calls[0]
    assert method == "place_order"
    assert args == ("idp.example:user-1",)  # provider host + subject id, never the email
    assert kwargs["symbol"] == "AAPL" and kwargs["side"] == "buy"
    assert kwargs["shares"] == D("2") and kwargs["dollars"] is None


def test_rejected_order_is_a_422_with_a_readable_message(env):
    client, store, _ = env
    sign_in(client, store)
    response = client.post("/paper/orders", json={**ORDER, "shares": 999})
    assert response.status_code == 422
    assert response.json()["detail"] == "Not enough cash"


@pytest.mark.parametrize("extra", [
    {"side": "short"}, {"shares": 0}, {"shares": -1}, {"dollars": 0}, {"shares": 1.0000001},
    {"idempotency_key": "short"}, {"idempotency_key": "has spaces in it"},
    {"ticker": "bad ticker"}, {"prediction_id": "not-an-id"},
])
def test_invalid_orders_are_422(env, extra):
    client, store, calls = env
    sign_in(client, store)
    assert client.post("/paper/orders", json={**ORDER, **extra}).status_code == 422
    assert calls == []


def test_order_limit_is_bounded(env):
    client, store, _ = env
    sign_in(client, store)
    assert client.get("/paper/orders?limit=0").status_code == 422
    assert client.get("/paper/orders?limit=201").status_code == 422
    assert client.get("/paper/orders?limit=5").status_code == 200


def test_local_development_uses_one_account_per_client(env, monkeypatch):
    client, _, calls = env
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "false")
    assert client.get("/paper/account").status_code == 200
    assert calls[0][1][0].startswith("local:")
