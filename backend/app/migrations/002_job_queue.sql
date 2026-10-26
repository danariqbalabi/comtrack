ALTER TABLE collection_jobs ADD COLUMN worker_token TEXT;
ALTER TABLE collection_jobs ADD COLUMN lease_expires_at TEXT;
ALTER TABLE collection_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0);
ALTER TABLE collection_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts >= 1);

CREATE TABLE collection_job_sources (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    adapter TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    result_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_json))
);

CREATE INDEX job_sources_order ON collection_job_sources(job_id, id);

UPDATE collection_jobs SET lease_expires_at = datetime(COALESCE(heartbeat_at, started_at, requested_at), '+90 seconds')
WHERE status = 'running';
