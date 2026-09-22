-- Durable user-initiated feedback reports (module P2 review queue).
--
-- Until now the triage queue lived in process memory: a report was classified,
-- returned to the user and then lost on the next restart, so the "human review
-- queue" could not actually be reviewed. This table is that queue.
--
-- Privacy rules, enforced by the schema and not only by the endpoint:
--   * a row exists only because the user pressed "报告问题" — nothing is scanned,
--     inferred or backfilled;
--   * the default row carries identifiers only (course / message / run / model /
--     template / version). The free-text body columns may carry content ONLY when
--     the user explicitly set attach_body; the CHECK below makes that structural,
--     so a future code path cannot quietly store a body without opt-in;
--   * the row records the *suggestion* (category, severity, suggested human queue)
--     and the Jev receipts behind it. It is never a grade, a sanction, a hidden
--     state change or an automatic resolution: status starts OPEN and only a human
--     moves it.

CREATE TABLE IF NOT EXISTS feedback_reports (
    id TEXT PRIMARY KEY,
    report_key TEXT NOT NULL UNIQUE,
    owner_user_id TEXT NOT NULL,
    owner_scope_hash TEXT NOT NULL,
    course_id TEXT NOT NULL,
    product_surface TEXT NOT NULL DEFAULT 'learn',
    message_id TEXT,
    run_id TEXT,
    model TEXT,
    template_version TEXT,
    app_version TEXT,
    category TEXT NOT NULL,
    severity INTEGER NOT NULL,
    suggested_queue TEXT NOT NULL,
    path TEXT NOT NULL,
    used_jev INTEGER NOT NULL DEFAULT 0 CHECK(used_jev IN (0, 1)),
    jev_calls INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    definition_version TEXT,
    latency_ms REAL,
    category_receipt_id TEXT,
    severity_receipt_id TEXT,
    attach_body INTEGER NOT NULL DEFAULT 0 CHECK(attach_body IN (0, 1)),
    report_text TEXT,
    question_text TEXT,
    answer_text TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK(status IN ('OPEN', 'REVIEWING', 'RESOLVED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- The body may only exist when the user opted in. This is the privacy rule
    -- made structural: no caller, present or future, can store a body without it.
    CHECK(
        attach_body = 1
        OR (report_text IS NULL AND question_text IS NULL AND answer_text IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_feedback_reports_queue
ON feedback_reports(status, severity DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_feedback_reports_owner
ON feedback_reports(owner_user_id, created_at);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(30, 'feedback reports');
