-- Append-only operator annotations; no scientific timing or scoring authority.
CREATE TABLE conditional_reviews (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    attempt_id text NOT NULL REFERENCES conditional_attempts(id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX conditional_reviews_attempt ON conditional_reviews(attempt_id,recorded_at,id);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON conditional_reviews
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
CREATE TABLE conditional_revisions (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    parent_attempt_id text NOT NULL REFERENCES conditional_attempts(id),
    revision_attempt_id text NOT NULL UNIQUE REFERENCES conditional_attempts(id),
    triggering_review_id text NOT NULL REFERENCES conditional_reviews(id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (parent_attempt_id <> revision_attempt_id)
);
CREATE INDEX conditional_revisions_parent ON conditional_revisions(parent_attempt_id);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON conditional_revisions
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
