"""Live quotes from a streaming feed, applied on top of a MarketSnapshot.

yfinance's REST quote (`fast_info`) can lag. With `--live`, the snapshot's last
price is replaced by the first tick from Yahoo's streaming websocket
(`yfinance.AsyncWebSocket`: free, no key). Everything downstream reads
`snapshot.last_price`, so nothing else changes.

Outside market hours no ticks arrive: after `timeout` seconds the REST price is
kept and a data warning says why. A live failure is not recorded in
`snapshot.errors`, because the REST price is still there and personas shouldn't
lower their conviction over it.

To use a paid feed (Alpaca, Finnhub), implement `LiveFeed` and pass it to
`predict(live_feed=...)`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any, Protocol

from ai.tool import MarketSnapshot, _price

DEFAULT_TIMEOUT = 5.0

log = logging.getLogger(__name__)


class LiveFeed(Protocol):
    name: str

    async def first_tick(self, ticker: str, timeout: float) -> dict[str, Any]:
        """The first quote for `ticker`, with at least `price`. Raises TimeoutError."""
        ...


class YahooLiveFeed:
    """Yahoo Finance's streaming websocket, through yfinance."""

    name = "yahoo-websocket"

    def __init__(self, socket_factory: Callable[[], Any] | None = None) -> None:
        self._socket_factory = socket_factory  # tests pass a fake socket

    def _socket(self) -> Any:
        if self._socket_factory is not None:
            return self._socket_factory()
        from yfinance import AsyncWebSocket

        return AsyncWebSocket(verbose=False)

    async def first_tick(self, ticker: str, timeout: float) -> dict[str, Any]:
        socket = self._socket()
        tick: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def handle(message: dict[str, Any]) -> None:
            if message.get("id") == ticker and message.get("price") and not tick.done():
                tick.set_result(message)

        listener: asyncio.Task | None = None
        try:
            await socket.subscribe(ticker)
            listener = asyncio.create_task(socket.listen(handle))
            done, _ = await asyncio.wait(
                {tick, listener}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if tick in done:
                return tick.result()
            if listener in done:  # the connection failed before any tick
                listener.result()
                raise ConnectionError("live feed closed before sending a quote")
            raise TimeoutError(f"no tick within {timeout:g}s (market closed?)")
        finally:
            if listener is not None:
                listener.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await listener
            with contextlib.suppress(Exception):
                await socket.close()


async def apply_live_quote(
    snapshot: MarketSnapshot, feed: LiveFeed, timeout: float = DEFAULT_TIMEOUT
) -> str | None:
    """Swap in the feed's price. Returns a data warning when the REST price is kept."""
    try:
        tick = await feed.first_tick(snapshot.ticker, timeout)
    except Exception as exc:
        return f"live: kept the REST quote; {type(exc).__name__}: {exc}"
    price = _price(tick.get("price"))
    if price is None:
        return f"live: kept the REST quote; unusable price {tick.get('price')!r}"
    log.info("%s live price %.4f (REST had %.4f)", snapshot.ticker, price, snapshot.last_price)
    snapshot.last_price = price
    snapshot.previous_close = _price(tick.get("previous_close")) or snapshot.previous_close
    snapshot.quote_source = feed.name
    return None
