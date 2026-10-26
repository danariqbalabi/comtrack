CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    kind TEXT NOT NULL CHECK(kind IN ('website', 'rss', 'instagram')),
    url TEXT NOT NULL,
    adapter TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'not_checked' CHECK(status IN ('not_checked', 'ok', 'partial', 'failed', 'not_connected')),
    last_checked_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, url)
);

CREATE TABLE competitions (
    id INTEGER PRIMARY KEY,
    dedup_key TEXT UNIQUE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    category TEXT NOT NULL CHECK(category IN ('hackathon', 'BCC', 'BPC', 'uncertain')),
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    first_seen_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX competitions_category_seen ON competitions(category, first_seen_at DESC);

CREATE TABLE evidence (
    id INTEGER PRIMARY KEY,
    competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE RESTRICT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    url TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    raw_text TEXT NOT NULL,
    field_values_json TEXT NOT NULL CHECK(json_valid(field_values_json)),
    fetched_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(competition_id, url, content_hash)
);

CREATE INDEX evidence_competition ON evidence(competition_id, fetched_at DESC);

CREATE TABLE competition_history (
    id INTEGER PRIMARY KEY,
    competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL,
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    changes_json TEXT NOT NULL CHECK(json_valid(changes_json)),
    reason TEXT NOT NULL,
    evidence_id INTEGER REFERENCES evidence(id) ON DELETE RESTRICT,
    recorded_at TEXT NOT NULL,
    UNIQUE(competition_id, version)
);

CREATE TABLE collection_jobs (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL DEFAULT 'manual' CHECK(trigger = 'manual'),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    requested_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(summary_json))
);

CREATE UNIQUE INDEX one_active_collection ON collection_jobs((1)) WHERE status IN ('queued', 'running');

CREATE TABLE collection_logs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    level TEXT NOT NULL CHECK(level IN ('info', 'warning', 'error')),
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX collection_logs_job ON collection_logs(job_id, created_at);

CREATE TABLE preferences (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    updated_at TEXT NOT NULL
);

INSERT INTO preferences(singleton, data_json, updated_at) VALUES (
    1,
    '{"categories":["hackathon","BCC","BPC"],"country":"ID","education_level":"university","include_unknown_eligibility":true,"hide_closed":true,"discovery_enabled":false}',
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
);
