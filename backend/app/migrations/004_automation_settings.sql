CREATE TABLE automation_settings (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    updated_at TEXT NOT NULL
);

INSERT INTO automation_settings(singleton, data_json, updated_at) VALUES (
    1,
    '{"enabled":false,"interval_minutes":360,"max_sources_per_run":10,"max_new_sources_per_run":3,"max_pages_per_source":5,"max_images_per_post":3,"allow_paid_providers":false,"provider_daily_request_limit":0,"provider_daily_budget_usd":"0.00","instagram_public_competition_accounts_only":true}',
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
);
