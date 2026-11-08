CREATE TABLE paid_provider_requests (
    id INTEGER PRIMARY KEY,
    job_source_id INTEGER NOT NULL REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    action_key TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider='apify'),
    day_utc TEXT NOT NULL,
    reserved_microusd INTEGER NOT NULL CHECK(reserved_microusd>0),
    status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    created_at TEXT NOT NULL,
    UNIQUE(job_source_id,action_key)
);
CREATE INDEX paid_provider_day ON paid_provider_requests(day_utc);
CREATE TABLE instagram_candidates (
    username TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    discovered_from TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','held','rejected','approved','active','existing','limited')),
    reason TEXT,
    profile_json TEXT CHECK(profile_json IS NULL OR json_valid(profile_json)),
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    checked_at TEXT
);
