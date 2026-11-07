CREATE TABLE extraction_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    output_json TEXT NOT NULL CHECK(json_valid(output_json)),
    created_at TEXT NOT NULL
);
CREATE TABLE extraction_attempts (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    job_source_id INTEGER NOT NULL REFERENCES collection_job_sources(id) ON DELETE RESTRICT,
    cache_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('ai','ocr')),
    document_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
    created_at TEXT NOT NULL,
    UNIQUE(job_source_id,cache_key,kind)
);
