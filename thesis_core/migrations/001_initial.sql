CREATE TABLE record_kinds (kind text PRIMARY KEY);
CREATE TABLE link_specs (
    kind text NOT NULL REFERENCES record_kinds(kind),
    field text NOT NULL,
    relation text NOT NULL,
    target_kind text NOT NULL REFERENCES record_kinds(kind),
    many boolean NOT NULL,
    required boolean NOT NULL,
    PRIMARY KEY (kind, field)
);

CREATE TABLE records (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    kind text NOT NULL REFERENCES record_kinds(kind),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    canonical_payload bytea NOT NULL,
    payload jsonb NOT NULL,
    created_txid bigint NOT NULL,
    recorded_at timestamptz NOT NULL,
    UNIQUE (id, kind),
    CHECK (encode(sha256(canonical_payload), 'hex') = id),
    CHECK (convert_from(canonical_payload, 'UTF8')::jsonb = payload),
    CHECK (payload->>'kind' = kind),
    CHECK ((payload->>'schema_version')::integer = schema_version)
);

CREATE TABLE record_links (
    source_id text NOT NULL,
    source_kind text NOT NULL,
    field_path text NOT NULL,
    relation text NOT NULL,
    target_id text NOT NULL,
    target_kind text NOT NULL,
    PRIMARY KEY (source_id, field_path),
    FOREIGN KEY (source_id, source_kind) REFERENCES records(id, kind)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (target_id, target_kind) REFERENCES records(id, kind)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX record_links_target ON record_links(target_id, relation, source_id);
-- A task belongs to one registered cohort in the initial protocol.
CREATE UNIQUE INDEX one_experiment_per_task ON record_links(target_id)
    WHERE source_kind = 'experiment' AND target_kind = 'evaluation_task';

CREATE TABLE record_acceptances (
    record_id text PRIMARY KEY REFERENCES records(id),
    committed_at timestamptz NOT NULL
);

CREATE TABLE outbox (
    id bigserial PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    kind text NOT NULL,
    subject_id text NOT NULL REFERENCES records(id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE outbox_delivery (
    outbox_id bigint PRIMARY KEY REFERENCES outbox(id),
    delivered_at timestamptz
);
CREATE TABLE jobs (
    id bigserial PRIMARY KEY,
    outbox_id bigint NOT NULL UNIQUE REFERENCES outbox(id),
    idempotency_key text NOT NULL UNIQUE,
    kind text NOT NULL,
    subject_id text NOT NULL REFERENCES records(id),
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'leased', 'complete', 'failed', 'unknown')),
    worker_id text,
    lease_token text,
    generation bigint NOT NULL DEFAULT 0,
    lease_expires_at timestamptz,
    dispatched_attempt_id text REFERENCES records(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((state = 'leased') =
        (worker_id IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX jobs_pending ON jobs(kind, id) WHERE state = 'pending';
CREATE TABLE task_attempt_counters (
    task_id text PRIMARY KEY REFERENCES records(id),
    next_sequence integer NOT NULL CHECK (next_sequence >= 1)
);
CREATE TABLE attempt_allocations (
    attempt_id text PRIMARY KEY,
    attempt_kind text NOT NULL DEFAULT 'attempt' CHECK (attempt_kind = 'attempt'),
    task_id text NOT NULL,
    task_kind text NOT NULL DEFAULT 'evaluation_task' CHECK (task_kind = 'evaluation_task'),
    sequence integer NOT NULL CHECK (sequence >= 1),
    job_id bigint NOT NULL UNIQUE REFERENCES jobs(id),
    FOREIGN KEY (attempt_id, attempt_kind) REFERENCES records(id, kind)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (task_id, task_kind) REFERENCES records(id, kind),
    UNIQUE (task_id, sequence)
);
CREATE TABLE attempt_events (
    id bigserial PRIMARY KEY,
    attempt_id text NOT NULL REFERENCES attempt_allocations(attempt_id),
    event text NOT NULL CHECK (event IN ('started', 'succeeded', 'failed', 'unknown', 'reconciled')),
    result_id text REFERENCES records(id),
    at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE UNIQUE INDEX one_attempt_start ON attempt_events(attempt_id) WHERE event = 'started';
CREATE UNIQUE INDEX one_attempt_terminal ON attempt_events(attempt_id)
    WHERE event IN ('succeeded', 'failed', 'unknown');
CREATE UNIQUE INDEX one_attempt_reconciliation ON attempt_events(attempt_id)
    WHERE event = 'reconciled';

CREATE FUNCTION reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
END;
$$;

CREATE FUNCTION assign_record_metadata() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_txid := txid_current();
    NEW.recorded_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER record_metadata BEFORE INSERT ON records
    FOR EACH ROW EXECUTE FUNCTION assign_record_metadata();

CREATE FUNCTION assign_acceptance() RETURNS trigger LANGUAGE plpgsql
SET search_path FROM CURRENT AS $$
DECLARE origin bigint;
BEGIN
    SELECT created_txid INTO origin FROM records WHERE id = NEW.record_id;
    IF origin IS NULL OR origin = txid_current() THEN
        RAISE EXCEPTION 'Acceptance requires a previously committed scientific record';
    END IF;
    NEW.committed_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER acceptance_metadata BEFORE INSERT ON record_acceptances
    FOR EACH ROW EXECUTE FUNCTION assign_acceptance();

CREATE FUNCTION check_record_links() RETURNS trigger LANGUAGE plpgsql
SET search_path FROM CURRENT AS $$
DECLARE
    record_id text;
    subject records%ROWTYPE;
    spec link_specs%ROWTYPE;
    reference_value jsonb;
    reference_id text;
    path text;
    ordinal bigint;
    expected_count integer := 0;
    actual_count integer;
BEGIN
    IF TG_TABLE_NAME = 'records' THEN record_id := NEW.id;
    ELSE record_id := NEW.source_id;
    END IF;
    SELECT * INTO STRICT subject FROM records WHERE id = record_id;
    FOR spec IN SELECT * FROM link_specs WHERE kind = subject.kind LOOP
        reference_value := subject.payload->spec.field;
        IF reference_value IS NULL OR reference_value = 'null'::jsonb THEN
            IF spec.required THEN RAISE EXCEPTION 'Missing required reference %', spec.field; END IF;
            CONTINUE;
        END IF;
        IF spec.many THEN
            IF jsonb_typeof(reference_value) <> 'array' THEN
                RAISE EXCEPTION 'Reference % must be an array', spec.field;
            END IF;
            FOR reference_id, ordinal IN
                SELECT value, ordinality FROM jsonb_array_elements_text(reference_value) WITH ORDINALITY
            LOOP
                path := spec.field || '[' || (ordinal - 1)::text || ']';
                expected_count := expected_count + 1;
                IF NOT EXISTS (SELECT 1 FROM record_links l WHERE
                    l.source_id = record_id AND l.source_kind = subject.kind
                    AND l.field_path = path AND l.relation = spec.relation
                    AND l.target_id = reference_id AND l.target_kind = spec.target_kind) THEN
                    RAISE EXCEPTION 'Missing or mismatched reference %', path;
                END IF;
            END LOOP;
        ELSE
            IF jsonb_typeof(reference_value) <> 'string' THEN
                RAISE EXCEPTION 'Reference % must be a string', spec.field;
            END IF;
            reference_id := reference_value #>> '{}';
            expected_count := expected_count + 1;
            IF NOT EXISTS (SELECT 1 FROM record_links l WHERE
                l.source_id = record_id AND l.source_kind = subject.kind
                AND l.field_path = spec.field AND l.relation = spec.relation
                AND l.target_id = reference_id AND l.target_kind = spec.target_kind) THEN
                RAISE EXCEPTION 'Missing or mismatched reference %', spec.field;
            END IF;
        END IF;
    END LOOP;
    SELECT count(*) INTO actual_count FROM record_links WHERE source_id = record_id;
    IF actual_count <> expected_count THEN RAISE EXCEPTION 'Unexpected scientific references'; END IF;
    IF EXISTS (
        WITH RECURSIVE dependencies(id) AS (
            SELECT target_id FROM record_links WHERE source_id = record_id
            UNION
            SELECT l.target_id FROM record_links l JOIN dependencies d ON l.source_id = d.id
        ) SELECT 1 FROM dependencies WHERE id = record_id
    ) THEN RAISE EXCEPTION 'Scientific dependency graph must be acyclic'; END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER record_link_completeness AFTER INSERT ON records
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_record_links();
CREATE CONSTRAINT TRIGGER inserted_link_completeness AFTER INSERT ON record_links
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_record_links();

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'record_kinds', 'link_specs', 'records', 'record_links', 'record_acceptances',
        'outbox', 'attempt_allocations', 'attempt_events'
    ] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()', table_name);
    END LOOP;
END;
$$;
