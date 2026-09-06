CREATE TABLE job_events (
    id bigserial PRIMARY KEY,
    job_id bigint NOT NULL REFERENCES jobs(id),
    event text NOT NULL CHECK (event = 'retry_requested'),
    generation bigint NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor text NOT NULL CHECK (length(actor)>0),
    reason text NOT NULL CHECK (length(reason)>0)
);
CREATE INDEX job_events_job ON job_events(job_id, id);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON job_events
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
