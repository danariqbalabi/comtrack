CREATE TABLE tavily_request_reservations (
    id INTEGER PRIMARY KEY,
    job_source_id INTEGER NOT NULL REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    query_index INTEGER NOT NULL,
    day_utc TEXT NOT NULL,
    month_utc TEXT NOT NULL,
    credits INTEGER NOT NULL DEFAULT 1 CHECK(credits>0),
    status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
    results_json TEXT CHECK(results_json IS NULL OR json_valid(results_json)),
    created_at TEXT NOT NULL,
    UNIQUE(job_source_id,query_index)
);
CREATE INDEX tavily_usage_day ON tavily_request_reservations(day_utc);
CREATE INDEX tavily_usage_month ON tavily_request_reservations(month_utc);
CREATE TABLE tavily_safety (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1))
);
INSERT INTO tavily_safety(singleton) VALUES (1);
CREATE TABLE discovery_provider_runs (
    job_source_id INTEGER PRIMARY KEY REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL CHECK(provider IN ('brave','tavily'))
);
-- Preserve the provider of previously issued requests, including in-flight jobs.
INSERT INTO discovery_provider_runs SELECT DISTINCT job_source_id,'brave' FROM provider_request_reservations;
