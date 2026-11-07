ALTER TABLE discovery_candidates ADD COLUMN onboarding_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(onboarding_status IN ('pending','held','rejected','active','existing','limited'));
ALTER TABLE discovery_candidates ADD COLUMN onboarding_reason TEXT;
ALTER TABLE discovery_candidates ADD COLUMN onboarding_checked_at TEXT;
ALTER TABLE discovery_candidates ADD COLUMN onboarded_source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL;

-- Retain quota consumption even if a source or candidate is later deleted.
CREATE TABLE website_onboardings (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES collection_jobs(id) ON DELETE RESTRICT,
    candidate_id INTEGER REFERENCES discovery_candidates(id) ON DELETE SET NULL,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    canonical_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(job_id,canonical_key)
);
CREATE INDEX website_onboardings_job ON website_onboardings(job_id);
