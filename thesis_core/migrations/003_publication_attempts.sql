CREATE TABLE publication_attempts (
    id bigserial PRIMARY KEY,
    manifest_id text NOT NULL,
    manifest_kind text NOT NULL DEFAULT 'publication_manifest'
        CHECK (manifest_kind = 'publication_manifest'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_hash text CHECK (response_hash ~ '^[0-9a-f]{64}$'),
    error_hash text CHECK (error_hash ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (manifest_id, manifest_kind) REFERENCES records(id, kind),
    CHECK (response_hash IS NOT NULL OR error_hash IS NOT NULL)
);
CREATE INDEX publication_attempts_manifest ON publication_attempts(manifest_id, id);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON publication_attempts
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
