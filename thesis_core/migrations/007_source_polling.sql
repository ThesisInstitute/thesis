-- Operational schedules never supply scientific timing or forecast authority.
CREATE TABLE source_poll_schedules (
    target_id text PRIMARY KEY REFERENCES records(id),
    source_id text NOT NULL REFERENCES records(id),
    adapter_id text NOT NULL,
    measurement_period text NOT NULL,
    vintage_date text,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    stop_at timestamptz NOT NULL,
    interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 60 AND 86400),
    max_polls integer NOT NULL CHECK (max_polls BETWEEN 1 AND 96),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (window_start <= window_end AND window_end <= stop_at),
    CHECK (stop_at <= window_end + interval '48 hours')
);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON source_poll_schedules
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TABLE source_poll_state (
    target_id text PRIMARY KEY REFERENCES source_poll_schedules(target_id),
    state text NOT NULL DEFAULT 'active'
        CHECK (state IN ('active','resolved','overdue','paused')),
    next_poll_at timestamptz,
    poll_count integer NOT NULL DEFAULT 0 CHECK (poll_count >= 0),
    generation bigint NOT NULL DEFAULT 0,
    lease_token text,
    lease_expires_at timestamptz,
    last_started_at timestamptz,
    last_finished_at timestamptz,
    last_success_at timestamptz,
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_error_code text CHECK (last_error_code IN (
        'capture_failed','source_unavailable','resolution_invalid','lease_expired',
        'poll_budget_exhausted','outcome_overdue')),
    CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL))
);
CREATE INDEX source_poll_due ON source_poll_state(next_poll_at)
    WHERE state='active';
CREATE TABLE source_poll_events (
    id bigserial PRIMARY KEY,
    target_id text NOT NULL REFERENCES source_poll_schedules(target_id),
    generation bigint NOT NULL,
    event text NOT NULL CHECK (event IN (
        'scheduled','started','succeeded','failed','lease_expired','resolved','overdue','paused')),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    error_code text,
    exchange_ids jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX source_poll_history ON source_poll_events(target_id,id);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON source_poll_events
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
CREATE TABLE source_poll_worker (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    last_poll_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
