-- Outcomes are audit records. Corrections append a new evaluation revision.
CREATE TRIGGER evaluations_immutable BEFORE UPDATE OR DELETE ON evaluations
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_record_change();
