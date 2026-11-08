CREATE TABLE source_health (
    source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    unchanged_runs INTEGER NOT NULL DEFAULT 0,
    relevant_found INTEGER NOT NULL DEFAULT 0,
    changes_found INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    next_check_at TEXT,
    reason TEXT
);
CREATE TABLE source_health_events (
    job_source_id INTEGER PRIMARY KEY REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);
CREATE TABLE competition_change_events (
    id INTEGER PRIMARY KEY,
    competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    changes_json TEXT NOT NULL CHECK(json_valid(changes_json)),
    created_at TEXT NOT NULL,
    UNIQUE(competition_id,version)
);
