"""Paper-trading arithmetic: pure functions, no database, no network.

Money is `Decimal`, never float. Cash and order totals are whole cents; share
quantities and average cost carry six decimals, so a dollar-sized order can buy a
fraction of a share. Positions are long only: no shorting, margin or leverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

Side = Literal["buy", "sell"]

CENT = Decimal("0.01")
SHARE = Decimal("0.000001")
STARTING_CASH = Decimal("100000.00")


class OrderRejected(ValueError):
    """The order can't be filled; the message is safe to show to the user."""


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class Fill:
    side: Side
    symbol: str
    shares: Decimal
    price: Decimal
    total: Decimal                 # cash paid (buy) or received (sell), in cents
    cash: Decimal                  # cash after the order
    position: Position | None      # holding after the order; None once fully sold
    realized_pnl: Decimal | None   # sells only


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def shares_for_dollars(dollars: Decimal, price: Decimal) -> Decimal:
    """Whole millionths of a share that `dollars` buys; never more than the dollars."""
    if price <= 0:
        raise OrderRejected("There is no usable price for this stock.")
    return (dollars / price).quantize(SHARE, rounding=ROUND_DOWN)


def apply_order(cash: Decimal, position: Position | None, *, side: Side, symbol: str,
                shares: Decimal, price: Decimal) -> Fill:
    """The result of filling one market order at `price`, or `OrderRejected`."""
    shares = shares.quantize(SHARE, rounding=ROUND_DOWN)
    if shares <= 0:
        raise OrderRejected("The order is too small to buy any of a share.")
    if price <= 0:
        raise OrderRejected("There is no usable price for this stock.")
    total = cents(shares * price)

    if side == "buy":
        if total > cash:
            raise OrderRejected(f"Not enough cash: this order costs ${total:,.2f} and you have ${cash:,.2f}.")
        held = position.shares if position else Decimal(0)
        basis = position.shares * position.average_cost if position else Decimal(0)
        new_shares = held + shares
        average = ((basis + shares * price) / new_shares).quantize(SHARE, rounding=ROUND_HALF_UP)
        return Fill("buy", symbol, shares, price, total, cash - total,
                    Position(symbol, new_shares, average), None)

    if position is None or position.shares <= 0:
        raise OrderRejected(f"You don't own any {symbol} to sell.")
    if shares > position.shares:
        raise OrderRejected(f"You own {position.shares.normalize():f} shares of {symbol} and tried to sell "
                            f"{shares.normalize():f}.")
    remaining = position.shares - shares
    realized = cents(total - shares * position.average_cost)
    left = Position(symbol, remaining, position.average_cost) if remaining > 0 else None
    return Fill("sell", symbol, shares, price, total, cash + total, left, realized)


def value_account(cash: Decimal, starting_cash: Decimal,
                  holdings: list[tuple[Position, Decimal]]) -> dict[str, Decimal]:
    """Equity and P&L from cash plus `(position, latest price)` pairs."""
    market_value = cents(sum((p.shares * price for p, price in holdings), Decimal(0)))
    cost_basis = cents(sum((p.shares * p.average_cost for p, _ in holdings), Decimal(0)))
    equity = cash + market_value
    return {
        "cash": cash,
        "market_value": market_value,
        "equity": equity,
        "unrealized_pnl": market_value - cost_basis,
        "total_pnl": equity - starting_cash,
        "total_return_pct": (((equity - starting_cash) / starting_cash) * 100).quantize(CENT, ROUND_HALF_UP),
    }
