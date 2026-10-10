-- Forecast-specific history survives mutable price corrections and can be replayed.
CREATE TABLE model_datasets (
    id UUID PRIMARY KEY,
    ticker TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    cutoff_at TIMESTAMPTZ NOT NULL CHECK (fetched_at <= cutoff_at),
    metadata JSONB NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    price_rows JSONB NOT NULL CHECK (jsonb_typeof(price_rows) = 'array' AND jsonb_array_length(price_rows) > 0)
);
CREATE INDEX model_datasets_ticker_idx ON model_datasets (ticker, fetched_at DESC);
CREATE TRIGGER model_datasets_immutable BEFORE UPDATE OR DELETE ON model_datasets
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
