-- price_bars holds the latest corrected value of each bar. Before a refresh
-- overwrites (or anything deletes) a bar, the old version is copied here, so the
-- prices as they were known at any past moment can be rebuilt exactly
-- (DatabaseRepository.get_price_history_as_of). Revisions are append-only.
CREATE TABLE price_bar_revisions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments(id),
    bar_at TIMESTAMPTZ NOT NULL,
    interval TEXT NOT NULL,
    provider TEXT NOT NULL,
    adjustment_basis TEXT NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL,
    volume NUMERIC,
    fetched_at TIMESTAMPTZ NOT NULL,  -- when the superseded version was fetched
    metadata JSONB NOT NULL,
    superseded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    change TEXT NOT NULL CHECK (change IN ('update', 'delete'))
);
CREATE INDEX price_bar_revisions_lookup_idx
    ON price_bar_revisions (instrument_id, interval, provider, adjustment_basis, bar_at, fetched_at);

CREATE FUNCTION archive_price_bar_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO price_bar_revisions
        (instrument_id, bar_at, interval, provider, adjustment_basis,
         open, high, low, close, volume, fetched_at, metadata, change)
    VALUES
        (OLD.instrument_id, OLD.bar_at, OLD.interval, OLD.provider, OLD.adjustment_basis,
         OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume, OLD.fetched_at, OLD.metadata,
         lower(TG_OP));
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- Only real changes are archived; save_price_bars already skips identical rows.
CREATE TRIGGER price_bars_archive_update BEFORE UPDATE ON price_bars
    FOR EACH ROW
    WHEN ((OLD.open, OLD.high, OLD.low, OLD.close, OLD.volume, OLD.metadata, OLD.fetched_at)
          IS DISTINCT FROM
          (NEW.open, NEW.high, NEW.low, NEW.close, NEW.volume, NEW.metadata, NEW.fetched_at))
    EXECUTE FUNCTION archive_price_bar_revision();
CREATE TRIGGER price_bars_archive_delete BEFORE DELETE ON price_bars
    FOR EACH ROW EXECUTE FUNCTION archive_price_bar_revision();

CREATE TRIGGER price_bar_revisions_immutable BEFORE UPDATE OR DELETE ON price_bar_revisions
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
