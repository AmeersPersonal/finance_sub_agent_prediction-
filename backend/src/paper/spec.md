# spec: backend/src/paper/

## TODOS

- [x] Simulated stock buys and sells at the latest saved close, per signed-in account (`/paper/*` in `api/`).
- [x] Link an order to the forecast it was placed from; order history returns that forecast's aggregate call.
- [ ] Prediction-market contracts (Kalshi-style YES/NO shares priced $0.01-$0.99 that settle at $1 or $0) on the same ledger. Needs a settlement job and a defined price model, not the persona signal strength (that isn't a probability).
- [ ] Score "followed the forecast" trades against the forecast's own evaluation once its horizon passes.
- [ ] Optional: record each fill as a Solana devnet memo transaction as a verifiable receipt. Never custody keys or move real assets.
- [ ] Fill at a live quote during market hours instead of the last saved close.

## Purpose

Simulated ("paper") trading so the app can show what following a forecast would
have done. Nothing here moves real money, touches a brokerage, or signs a
blockchain transaction. Each account starts with $100,000 of virtual cash and
holds long-only share positions (no shorting, margin or leverage). It is
educational, not financial advice.

## Files

| File | Role |
|---|---|
| `ledger.py` | Pure arithmetic with `Decimal`: apply one order, value an account. No database, no network |
| `service.py` | `PaperTrading`: account, orders, reset and price lookup against PostgreSQL (migration 009) |

## Design rules

- **Money is `Decimal`.** Cash and order totals are whole cents; shares and average
  cost carry six decimals so a dollar-sized order can buy a fraction of a share.
- **Fills use the latest saved daily close** (`DatabaseRepository.get_price_history`)
  and report that bar's time. A price older than `PAPER_MAX_PRICE_AGE_DAYS` (default 7)
  or missing is rejected rather than filled with a made-up number.
- **One order at a time per account.** The account row is locked with `FOR UPDATE`
  for the length of an order, so double clicks can't spend the same cash.
- **Idempotent.** `(account, idempotency_key)` is unique; a repeated key returns the
  first order with `replayed: true` and trades nothing.
- **A rejected order changes nothing.** `OrderRejected` messages are safe to show to
  the user; the API returns them as a 422.
- **Sells are by share count.** Dollar-sized orders are buys only; a sell-all sends the
  position's exact share count.
- **Account key is the provider-namespaced subject id** (same as `user_preferences`),
  never the email. With `API_REQUIRE_SIGN_IN=false` there is one account per client address.
- **Don't mix this with forecasting.** `paper/` reads prices and forecast ids; nothing
  in `ai/`, `finance/` or `ml/` imports it.
