import asyncio

from ai.live import YahooLiveFeed, apply_live_quote
from ai.main import predict


class FakeSocket:
    """Stands in for yfinance.AsyncWebSocket: replays `messages`, then idles."""

    def __init__(self, messages=(), fail_on_listen=None):
        self.messages, self.fail_on_listen = list(messages), fail_on_listen
        self.subscribed, self.closed = [], False

    async def subscribe(self, symbols):
        self.subscribed.append(symbols)

    async def listen(self, handler):
        if self.fail_on_listen:
            raise self.fail_on_listen
        for message in self.messages:
            handler(message)
        await asyncio.sleep(3600)  # a live socket never ends on its own

    async def close(self):
        self.closed = True


class FixedFeed:
    name = "fixed"

    def __init__(self, tick=None, error=None):
        self.tick, self.error = tick, error

    async def first_tick(self, ticker, timeout):
        if self.error:
            raise self.error
        return self.tick


def test_yahoo_feed_returns_the_first_tick_for_the_ticker():
    socket = FakeSocket([{"id": "OTHER", "price": 1.0}, {"id": "TEST", "price": 101.5}])
    tick = asyncio.run(YahooLiveFeed(lambda: socket).first_tick("TEST", timeout=1))
    assert tick["price"] == 101.5
    assert socket.subscribed == ["TEST"] and socket.closed


def test_yahoo_feed_times_out_when_the_market_is_quiet():
    socket = FakeSocket()
    feed = YahooLiveFeed(lambda: socket)
    try:
        asyncio.run(feed.first_tick("TEST", timeout=0.05))
    except TimeoutError as exc:
        assert "market closed" in str(exc)
    else:
        raise AssertionError("expected a timeout")
    assert socket.closed


def test_yahoo_feed_surfaces_a_dropped_connection():
    socket = FakeSocket(fail_on_listen=OSError("connection reset"))
    try:
        asyncio.run(YahooLiveFeed(lambda: socket).first_tick("TEST", timeout=1))
    except OSError as exc:
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("expected the connection error")


def test_live_quote_replaces_the_rest_price(snapshot):
    tick = {"id": "TEST", "price": 123.45, "previous_close": 120.0}
    assert asyncio.run(apply_live_quote(snapshot, FixedFeed(tick))) is None
    assert (snapshot.last_price, snapshot.previous_close) == (123.45, 120.0)
    assert snapshot.quote_source == "fixed"


def test_live_failure_keeps_the_rest_price_and_warns(snapshot):
    rest_price = snapshot.last_price
    warning = asyncio.run(apply_live_quote(snapshot, FixedFeed(error=TimeoutError("quiet"))))
    assert warning.startswith("live: kept the REST quote") and "quiet" in warning
    assert snapshot.last_price == rest_price and snapshot.quote_source == "yfinance"
    assert "live" not in snapshot.errors  # personas still have a price; don't flag a missing source
    bad = asyncio.run(apply_live_quote(snapshot, FixedFeed({"price": -1})))
    assert "unusable price" in bad


def test_predict_uses_the_live_feed(snapshot, fake_llm):
    tick = {"id": "TEST", "price": snapshot.last_price * 1.01}
    prediction = asyncio.run(
        predict("TEST", llm=fake_llm, snapshot=snapshot, live_feed=FixedFeed(tick))
    )
    assert prediction.quote_source == "fixed" and prediction.last_price == tick["price"]
    quiet = asyncio.run(
        predict("TEST", llm=fake_llm, snapshot=snapshot, live_feed=FixedFeed(error=TimeoutError()))
    )
    assert any(w.startswith("live:") for w in quiet.data_warnings)
