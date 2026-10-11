-- Simulated ("paper") trading: virtual cash, long-only share positions and an order
-- log, per signed-in account. Nothing here is real money, a brokerage account or an
-- on-chain transaction, and no credentials are stored.
--
-- account_reference is the same provider-namespaced subject id as user_preferences.
-- Orders are append-only history; a reset deletes the account's orders and positions.
CREATE TABLE paper_accounts (
    account_reference TEXT PRIMARY KEY CHECK (length(trim(account_reference)) > 0),
    starting_cash NUMERIC NOT NULL CHECK (starting_cash > 0),
    cash NUMERIC NOT NULL CHECK (cash >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE paper_positions (
    account_reference TEXT NOT NULL REFERENCES paper_accounts(account_reference) ON DELETE CASCADE,
    symbol TEXT NOT NULL CHECK (length(trim(symbol)) > 0),
    shares NUMERIC NOT NULL CHECK (shares > 0),
    average_cost NUMERIC NOT NULL CHECK (average_cost > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_reference, symbol)
);

-- price is the saved daily close the order filled at; price_as_of is that bar's time.
-- realized_pnl is set on sells only. prediction_id links an order to the forecast it
-- was placed from, so a result can be attributed back to the call.
CREATE TABLE paper_orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_reference TEXT NOT NULL REFERENCES paper_accounts(account_reference) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 64),
    symbol TEXT NOT NULL CHECK (length(trim(symbol)) > 0),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    shares NUMERIC NOT NULL CHECK (shares > 0),
    price NUMERIC NOT NULL CHECK (price > 0),
    price_as_of TIMESTAMPTZ NOT NULL,
    realized_pnl NUMERIC,
    prediction_id TEXT REFERENCES prediction_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (side = 'sell' OR realized_pnl IS NULL),
    UNIQUE (account_reference, idempotency_key)
);
CREATE INDEX paper_orders_history_idx ON paper_orders (account_reference, created_at DESC, id DESC);
