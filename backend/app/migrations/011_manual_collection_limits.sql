-- Manual collection shares provider budgets, while retaining the manual trigger and pause semantics.
CREATE TABLE manual_job_limits (
    job_id INTEGER PRIMARY KEY REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    settings_json TEXT NOT NULL CHECK(json_valid(settings_json))
);
