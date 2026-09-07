-- One target contract resolves to one exact vintage. Repeated capture/jobs
-- must not create timestamp-distinct resolutions for the same target.
CREATE UNIQUE INDEX one_resolution_per_target ON record_links(target_id)
    WHERE source_kind='resolution' AND target_kind='target_version';
