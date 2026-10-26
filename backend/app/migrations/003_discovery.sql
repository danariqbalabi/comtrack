CREATE TABLE discovery_candidates (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('verified','unverified','irrelevant','failed')),
    reason TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    job_id INTEGER REFERENCES collection_jobs(id) ON DELETE RESTRICT
);
