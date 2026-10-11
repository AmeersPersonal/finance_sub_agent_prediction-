"""Paper trading against the saved price bars, for one signed-in account at a time.

Orders fill at the latest *saved* daily close, not a live quote, and say which bar
that was. The account row is locked for the length of an order, so two clicks
can't spend the same cash, and a repeated idempotency key returns the first result.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from database.connection import DatabaseError
from database.repository import DatabaseRepository
from paper.ledger import (
    CENT, STARTING_CASH, OrderRejected, Position, Side, apply_order, cents, shares_for_dollars, value_account,
)


def max_price_age() -> timedelta:
    try:
        days = int(os.environ.get("PAPER_MAX_PRICE_AGE_DAYS") or 7)
    except ValueError:
        days = 7
    return timedelta(days=max(1, days))


class PaperTrading:
    """Wraps a psycopg connection configured with `dict_row`, like `DatabaseRepository`."""

    def __init__(self, connection: Any, *, starting_cash: Decimal = STARTING_CASH, now: datetime | None = None):
        self.connection = connection
        self.starting_cash = starting_cash
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    @contextmanager
    def _transaction(self):
        import psycopg
        try:
            with self.connection.transaction():
                yield
        except psycopg.Error:
            raise DatabaseError("Database operation failed.") from None

    # -- prices ----------------------------------------------------------------

    def latest_price(self, symbol: str) -> tuple[Decimal, datetime] | None:
        bars = DatabaseRepository(self.connection).get_price_history(symbol, interval="1d", limit=1)
        if not bars or bars[0]["close"] is None or Decimal(bars[0]["close"]) <= 0:
            return None
        return Decimal(bars[0]["close"]), bars[0]["bar_at"]

    def fill_price(self, symbol: str) -> tuple[Decimal, datetime]:
        found = self.latest_price(symbol)
        if found is None:
            raise OrderRejected(f"There are no saved prices for {symbol} yet. Refresh it first, then try again.")
        price, as_of = found
        if self.now - as_of > max_price_age():
            raise OrderRejected(f"The newest saved price for {symbol} is from {as_of:%Y-%m-%d}, which is too old "
                                "to simulate a fill. Refresh it first, then try again.")
        return price, as_of

    # -- account ---------------------------------------------------------------

    def _ensure_account(self, account: str, *, lock: bool = False) -> dict:
        self.connection.execute(
            """INSERT INTO paper_accounts (account_reference, starting_cash, cash)
            VALUES (%s, %s, %s) ON CONFLICT (account_reference) DO NOTHING""",
            (account, self.starting_cash, self.starting_cash),
        )
        return self.connection.execute(
            "SELECT starting_cash, cash FROM paper_accounts WHERE account_reference = %s"
            + (" FOR UPDATE" if lock else ""), (account,),
        ).fetchone()

    def account(self, account: str) -> dict[str, Any]:
        """Cash, equity, P&L and every holding valued at its latest saved close."""
        with self._transaction():
            row = self._ensure_account(account)
            holdings = self.connection.execute(
                """SELECT symbol, shares, average_cost FROM paper_positions
                WHERE account_reference = %s ORDER BY symbol""", (account,),
            ).fetchall()
        priced: list[tuple[Position, Decimal]] = []
        positions: list[dict[str, Any]] = []
        for held in holdings:
            position = Position(held["symbol"], Decimal(held["shares"]), Decimal(held["average_cost"]))
            found = self.latest_price(position.symbol)
            price, as_of = found if found else (position.average_cost, None)  # unvalued: shown at cost
            priced.append((position, price))
            value = cents(position.shares * price)
            basis = cents(position.shares * position.average_cost)
            positions.append({
                "symbol": position.symbol, "shares": position.shares, "average_cost": position.average_cost,
                "price": price, "price_as_of": as_of, "price_available": found is not None,
                "market_value": value, "unrealized_pnl": value - basis,
                "unrealized_pnl_pct": ((value - basis) / basis * 100).quantize(CENT) if basis else Decimal(0),
            })
        summary = value_account(Decimal(row["cash"]), Decimal(row["starting_cash"]), priced)
        return {"account": {**summary, "starting_cash": Decimal(row["starting_cash"])}, "positions": positions}

    def reset(self, account: str) -> dict[str, Any]:
        """Back to the starting balance with no holdings and no order history."""
        with self._transaction():
            self._ensure_account(account, lock=True)
            self.connection.execute("DELETE FROM paper_orders WHERE account_reference = %s", (account,))
            self.connection.execute("DELETE FROM paper_positions WHERE account_reference = %s", (account,))
            self.connection.execute(
                """UPDATE paper_accounts SET cash = starting_cash, updated_at = now()
                WHERE account_reference = %s""", (account,),
            )
        return self.account(account)

    # -- orders ----------------------------------------------------------------

    def place_order(self, account: str, *, symbol: str, side: Side, idempotency_key: str,
                    shares: Decimal | None = None, dollars: Decimal | None = None,
                    prediction_id: str | None = None) -> dict[str, Any]:
        """Fill one market order at the latest saved close.

        Give `shares` or `dollars` (buys only). Raises `OrderRejected` with a message
        safe to show the user; a replayed `idempotency_key` returns the original order.
        """
        if (shares is None) == (dollars is None):
            raise OrderRejected("Give either a number of shares or a dollar amount.")
        if dollars is not None and side == "sell":
            raise OrderRejected("Sell by number of shares.")
        price, as_of = self.fill_price(symbol)

        with self._transaction():
            cash_row = self._ensure_account(account, lock=True)
            previous = self.connection.execute(
                """SELECT id, symbol, side, shares, price, price_as_of, realized_pnl, prediction_id, created_at
                FROM paper_orders WHERE account_reference = %s AND idempotency_key = %s""",
                (account, idempotency_key),
            ).fetchone()
            if previous:
                if previous["symbol"] != symbol or previous["side"] != side:
                    raise OrderRejected("That idempotency key was already used for a different order.")
                replay = True
                order = previous
            else:
                replay = False
                if prediction_id is not None:
                    self._check_forecast(prediction_id, symbol)
                held = self.connection.execute(
                    """SELECT shares, average_cost FROM paper_positions
                    WHERE account_reference = %s AND symbol = %s FOR UPDATE""", (account, symbol),
                ).fetchone()
                position = Position(symbol, Decimal(held["shares"]), Decimal(held["average_cost"])) if held else None
                quantity = shares if shares is not None else shares_for_dollars(dollars, price)
                fill = apply_order(Decimal(cash_row["cash"]), position, side=side, symbol=symbol,
                                   shares=quantity, price=price)
                self.connection.execute(
                    "UPDATE paper_accounts SET cash = %s, updated_at = now() WHERE account_reference = %s",
                    (fill.cash, account),
                )
                if fill.position is None:
                    self.connection.execute(
                        "DELETE FROM paper_positions WHERE account_reference = %s AND symbol = %s", (account, symbol),
                    )
                else:
                    self.connection.execute(
                        """INSERT INTO paper_positions (account_reference, symbol, shares, average_cost)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (account_reference, symbol) DO UPDATE SET
                            shares = EXCLUDED.shares, average_cost = EXCLUDED.average_cost, updated_at = now()""",
                        (account, symbol, fill.position.shares, fill.position.average_cost),
                    )
                order = self.connection.execute(
                    """INSERT INTO paper_orders (account_reference, idempotency_key, symbol, side, shares,
                        price, price_as_of, realized_pnl, prediction_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, symbol, side, shares, price, price_as_of, realized_pnl, prediction_id, created_at""",
                    (account, idempotency_key, symbol, side, fill.shares, fill.price, as_of,
                     fill.realized_pnl, prediction_id),
                ).fetchone()
        return {"order": {**order, "total": cents(Decimal(order["shares"]) * Decimal(order["price"]))},
                "replayed": replay, **self.account(account)}

    def _check_forecast(self, prediction_id: str, symbol: str) -> None:
        row = self.connection.execute(
            """SELECT i.symbol FROM prediction_runs r JOIN instruments i ON i.id = r.instrument_id
            WHERE r.id = %s""", (prediction_id,),
        ).fetchone()
        if row is None:
            raise OrderRejected("That forecast doesn't exist.")
        if row["symbol"] != symbol:
            raise OrderRejected(f"That forecast is for {row['symbol']}, not {symbol}.")

    def orders(self, account: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Newest first, each with the forecast call it was placed from, if any."""
        with self._transaction():
            return self.connection.execute(
                """SELECT o.id, o.symbol, o.side, o.shares, o.price, o.price_as_of, o.realized_pnl,
                          o.created_at, o.prediction_id, a.direction AS forecast_direction,
                          r.horizon_days AS forecast_horizon_days
                FROM paper_orders o
                LEFT JOIN prediction_runs r ON r.id = o.prediction_id
                LEFT JOIN prediction_outputs a ON a.run_id = o.prediction_id AND a.output_key = 'aggregate'
                WHERE o.account_reference = %s
                ORDER BY o.created_at DESC, o.id DESC LIMIT %s""", (account, limit),
            ).fetchall()
