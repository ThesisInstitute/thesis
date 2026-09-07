CREATE FUNCTION check_execution_record() RETURNS trigger LANGUAGE plpgsql
SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.kind = 'attempt' THEN
        IF NOT EXISTS (SELECT 1 FROM attempt_allocations a
            WHERE a.attempt_id=NEW.id AND a.task_id=NEW.payload->>'task_id'
            AND a.sequence=(NEW.payload->>'sequence')::integer) THEN
            RAISE EXCEPTION 'Attempt requires its atomically allocated sequence';
        END IF;
    ELSIF NEW.kind = 'attempt_result' THEN
        IF NOT EXISTS (SELECT 1 FROM attempt_events e WHERE e.result_id=NEW.id
            AND e.attempt_id=NEW.payload->>'attempt_id'
            AND (e.event=NEW.payload->>'outcome' OR
                (e.event='reconciled' AND NEW.payload->>'reconciles_result_id' IS NOT NULL))) THEN
            RAISE EXCEPTION 'Attempt result requires its fenced terminal event';
        END IF;
    ELSIF NEW.kind = 'forecast_run' THEN
        IF NOT EXISTS (SELECT 1 FROM attempt_events e JOIN records r ON r.id=e.result_id
            WHERE e.event='succeeded' AND e.attempt_id=NEW.payload->>'attempt_id'
            AND r.payload->>'run_id'=NEW.id) THEN
            RAISE EXCEPTION 'Forecast requires its fenced successful completion';
        END IF;
    ELSIF NEW.kind = 'experiment' THEN
        IF EXISTS (
            SELECT 1 FROM record_links l JOIN records r ON r.id=l.target_id
            WHERE l.source_id=NEW.id AND l.target_kind='evaluation_task'
            GROUP BY r.payload->>'target_version_id',r.payload->>'forecaster_version_id'
            HAVING count(*)>1
        ) THEN RAISE EXCEPTION 'Experiment repeats a target/forecaster pair'; END IF;
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER execution_record_guard AFTER INSERT ON records
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_execution_record();
