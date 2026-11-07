CREATE TABLE discovery_rotation (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    next_index INTEGER NOT NULL DEFAULT 0 CHECK(next_index>=0)
);
INSERT INTO discovery_rotation(singleton) VALUES (1);

CREATE TABLE discovery_plans (
    job_source_id INTEGER PRIMARY KEY REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    queries_json TEXT NOT NULL CHECK(json_valid(queries_json)),
    preferences_json TEXT NOT NULL CHECK(json_valid(preferences_json))
);

CREATE TABLE provider_request_reservations (
    id INTEGER PRIMARY KEY,
    job_source_id INTEGER NOT NULL REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    query_index INTEGER NOT NULL,
    query_text TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider='brave'),
    day_utc TEXT NOT NULL,
    reserved_microusd INTEGER NOT NULL CHECK(reserved_microusd>0),
    status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
    results_json TEXT CHECK(results_json IS NULL OR json_valid(results_json)),
    created_at TEXT NOT NULL,
    UNIQUE(job_source_id,query_index)
);
CREATE INDEX provider_reservations_day ON provider_request_reservations(day_utc);

ALTER TABLE discovery_candidates ADD COLUMN canonical_key TEXT;
ALTER TABLE discovery_candidates ADD COLUMN domain TEXT;
ALTER TABLE discovery_candidates ADD COLUMN discovered_query TEXT;
ALTER TABLE discovery_candidates ADD COLUMN checked_at TEXT;
CREATE UNIQUE INDEX discovery_candidate_canonical ON discovery_candidates(canonical_key);
CREATE INDEX discovery_candidate_domain ON discovery_candidates(domain);
