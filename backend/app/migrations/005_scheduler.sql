CREATE TABLE automation_schedule (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    next_run_at TEXT,
    last_tick_at TEXT,
    last_enqueued_at TEXT,
    last_job_id INTEGER REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    last_source_id INTEGER NOT NULL DEFAULT 0,
    last_status TEXT NOT NULL DEFAULT 'disabled'
);
INSERT INTO automation_schedule(singleton) VALUES (1);

-- Separate metadata preserves the original jobs and every existing FK/history.
-- Existing collection_jobs.trigger is a legacy manual-only field; readers use this metadata.
CREATE TABLE automation_job_runs (
    job_id INTEGER PRIMARY KEY REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    settings_version INTEGER NOT NULL,
    settings_json TEXT NOT NULL CHECK(json_valid(settings_json)),
    scheduled_for TEXT NOT NULL
);

CREATE TABLE automation_source_usage (
    job_source_id INTEGER PRIMARY KEY REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    pages_used INTEGER NOT NULL CHECK(pages_used >= 0)
);
