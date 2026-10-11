-- Portable PostgreSQL schema. Apply once using the migration runner.
-- Credentials, OAuth tokens, and brokerage secrets must never be stored here.

CREATE TABLE instruments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE CHECK (length(trim(symbol)) > 0),
    name TEXT,
    instrument_type TEXT NOT NULL DEFAULT 'stock'
        CHECK (instrument_type IN ('stock', 'etf', 'bond', 'index', 'option', 'other')),
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE price_bars (
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    bar_at TIMESTAMPTZ NOT NULL,
    interval TEXT NOT NULL CHECK (length(trim(interval)) > 0),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    adjustment_basis TEXT NOT NULL CHECK (adjustment_basis IN ('raw', 'split', 'total_return')),
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL CHECK (close >= 0),
    volume NUMERIC CHECK (volume >= 0),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    PRIMARY KEY (instrument_id, bar_at, interval, provider, adjustment_basis),
    CHECK (high IS NULL OR low IS NULL OR high >= low)
);
CREATE INDEX price_bars_lookup_idx ON price_bars (instrument_id, interval, bar_at DESC);

-- A changed article is a new row with a new content hash. first_seen_at records
-- when OUR system obtained this version; published_at alone is not availability.
CREATE TABLE documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_url TEXT NOT NULL CHECK (length(trim(source_url)) > 0),
    source_name TEXT,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (document_type IN
        ('news', 'filing', 'company_report', 'announcement', 'forum', 'other')),
    content_kind TEXT NOT NULL CHECK (content_kind IN ('full_text', 'excerpt', 'headline')),
    content_text TEXT NOT NULL CHECK (length(trim(content_text)) > 0),
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    classification JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(classification) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    UNIQUE (source_url, content_sha256)
);
CREATE INDEX documents_available_idx ON documents (first_seen_at DESC, published_at DESC);

CREATE TABLE document_instruments (
    document_id BIGINT NOT NULL REFERENCES documents(id),
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    relationship TEXT NOT NULL DEFAULT 'mentions',
    PRIMARY KEY (document_id, instrument_id)
);
CREATE INDEX document_instruments_lookup_idx ON document_instruments (instrument_id, document_id);

-- Text passages are optional. No embedding provider or vector extension is
-- required; an embedding index may be introduced by a later migration.
CREATE TABLE document_chunks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content_text TEXT NOT NULL CHECK (length(trim(content_text)) > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    UNIQUE (document_id, chunk_index),
    UNIQUE (document_id, id)
);
CREATE INDEX document_chunks_search_idx ON document_chunks
    USING GIN (to_tsvector('english', content_text));

CREATE TABLE fundamental_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    provider TEXT NOT NULL,
    period_end DATE,
    available_at TIMESTAMPTZ NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    source_document_id BIGINT REFERENCES documents(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object')
);
CREATE INDEX fundamental_snapshots_lookup_idx ON fundamental_snapshots (instrument_id, available_at DESC);

-- Match existing Prediction.id without changing its hex-string representation.
-- frozen_inputs contains the exact snapshot/packets used, not mutable pointers.
-- prediction_payload preserves the complete existing Pydantic Prediction JSON.
CREATE TABLE prediction_runs (
    id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0),
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    generated_at TIMESTAMPTZ NOT NULL,
    cutoff_at TIMESTAMPTZ NOT NULL,
    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
    horizon_unit TEXT NOT NULL DEFAULT 'trading_days' CHECK (horizon_unit = 'trading_days'),
    selected_strategies TEXT[] NOT NULL DEFAULT '{}'::text[]
        CHECK (selected_strategies <@ ARRAY['long_term', 'day_trader', 'index_options']::text[]),
    selected_age_bands TEXT[] NOT NULL DEFAULT '{}'::text[],
    data_as_of DATE NOT NULL,
    last_price NUMERIC NOT NULL CHECK (last_price > 0),
    flat_band_pct NUMERIC NOT NULL CHECK (flat_band_pct >= 0),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    frozen_inputs JSONB NOT NULL CHECK (jsonb_typeof(frozen_inputs) = 'object'),
    prediction_payload JSONB NOT NULL CHECK (jsonb_typeof(prediction_payload) = 'object'),
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (cutoff_at <= generated_at)
);
CREATE INDEX prediction_runs_history_idx ON prediction_runs (instrument_id, generated_at DESC);

CREATE TABLE prediction_outputs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(id),
    output_key TEXT NOT NULL,
    output_type TEXT NOT NULL CHECK (output_type IN ('persona', 'aggregate', 'regression', 'baseline')),
    persona_id TEXT,
    strategy TEXT CHECK (strategy IN ('long_term', 'day_trader', 'index_options')),
    age_band TEXT,
    direction TEXT CHECK (direction IN ('up', 'down', 'flat', 'unclear')),
    confidence DOUBLE PRECISION CHECK (confidence >= 0 AND confidence <= 1),
    predicted_return_pct DOUBLE PRECISION,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    UNIQUE (run_id, output_key),
    UNIQUE (run_id, id),
    CHECK (output_type <> 'persona' OR persona_id IS NOT NULL),
    CHECK (output_type <> 'persona' OR direction IS DISTINCT FROM 'unclear')
);

-- Save exactly the excerpt handed to Gemini, even if chunking changes later.
CREATE TABLE prediction_evidence (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(id),
    output_id BIGINT,
    document_id BIGINT NOT NULL REFERENCES documents(id),
    chunk_id BIGINT,
    evidence_role TEXT NOT NULL CHECK (evidence_role IN
        ('public_opinion', 'company_info', 'product_event', 'other')),
    excerpt_text TEXT NOT NULL CHECK (length(trim(excerpt_text)) > 0),
    retrieved_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    FOREIGN KEY (run_id, output_id) REFERENCES prediction_outputs(run_id, id),
    FOREIGN KEY (document_id, chunk_id) REFERENCES document_chunks(document_id, id)
);
CREATE INDEX prediction_evidence_run_idx ON prediction_evidence (run_id);
CREATE INDEX prediction_evidence_document_idx ON prediction_evidence (document_id);

CREATE FUNCTION check_evidence_availability() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    run_cutoff TIMESTAMPTZ;
    source_seen TIMESTAMPTZ;
    source_published TIMESTAMPTZ;
BEGIN
    SELECT cutoff_at INTO run_cutoff FROM prediction_runs WHERE id = NEW.run_id;
    SELECT first_seen_at, published_at INTO source_seen, source_published
        FROM documents WHERE id = NEW.document_id;
    IF source_seen > run_cutoff OR source_published > run_cutoff THEN
        RAISE EXCEPTION 'Evidence was not available at the prediction cutoff';
    END IF;
    IF NEW.retrieved_at > run_cutoff THEN
        RAISE EXCEPTION 'Evidence retrieval must precede the prediction cutoff';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER prediction_evidence_available BEFORE INSERT ON prediction_evidence
    FOR EACH ROW EXECUTE FUNCTION check_evidence_availability();

-- Evaluation revisions remain separate from the original immutable prediction.
CREATE TABLE evaluations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(id),
    output_id BIGINT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_at TIMESTAMPTZ NOT NULL,
    provider TEXT NOT NULL,
    adjustment_basis TEXT NOT NULL CHECK (adjustment_basis IN ('raw', 'split', 'total_return')),
    actual_price NUMERIC NOT NULL CHECK (actual_price >= 0),
    actual_return_pct DOUBLE PRECISION NOT NULL,
    actual_direction TEXT NOT NULL CHECK (actual_direction IN ('up', 'down', 'flat')),
    correct BOOLEAN,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    FOREIGN KEY (run_id, output_id) REFERENCES prediction_outputs(run_id, id),
    CHECK (outcome_at <= evaluated_at)
);
CREATE INDEX evaluations_run_idx ON evaluations (run_id, evaluated_at DESC);

-- External account reference only; no authentication or financial credentials.
CREATE TABLE user_preferences (
    account_reference TEXT PRIMARY KEY CHECK (length(trim(account_reference)) > 0),
    age_band TEXT CHECK (age_band IN ('18-24', '25-39', '40-54', '55-65')),
    strategy TEXT CHECK (strategy IN ('long_term', 'day_trader', 'index_options')),
    experience_level TEXT CHECK (experience_level IN ('beginner', 'intermediate', 'advanced')),
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(preferences) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION reject_immutable_record_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% records are immutable; insert a new version instead', TG_TABLE_NAME;
END;
$$;
CREATE TRIGGER documents_immutable BEFORE UPDATE OR DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
CREATE TRIGGER document_chunks_immutable BEFORE UPDATE OR DELETE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
CREATE TRIGGER fundamental_snapshots_immutable BEFORE UPDATE OR DELETE ON fundamental_snapshots
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
CREATE TRIGGER prediction_runs_immutable BEFORE UPDATE OR DELETE ON prediction_runs
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
CREATE TRIGGER prediction_outputs_immutable BEFORE UPDATE OR DELETE ON prediction_outputs
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
CREATE TRIGGER prediction_evidence_immutable BEFORE UPDATE OR DELETE ON prediction_evidence
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
