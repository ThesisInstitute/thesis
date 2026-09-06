-- Even failure to construct a timestamp request belongs in the immutable audit.
ALTER TABLE publication_attempts ALTER COLUMN request_hash DROP NOT NULL;
