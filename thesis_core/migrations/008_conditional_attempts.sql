-- Exploratory conditionals deliberately have no references to scientific records.
CREATE TABLE conditional_attempts (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    contract_id text NOT NULL CHECK (contract_id ~ '^[0-9a-f]{64}$'),
    attempt_hash text NOT NULL CHECK (attempt_hash ~ '^[0-9a-f]{64}$'),
    started_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > started_at)
);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON conditional_attempts
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
CREATE TABLE conditional_results (
    attempt_id text PRIMARY KEY REFERENCES conditional_attempts(id),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    execution_state text NOT NULL CHECK (execution_state IN ('succeeded','failed','unknown')),
    finished_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON conditional_results
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
