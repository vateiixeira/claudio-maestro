"""Pure migration-27 statements. Applied only by the central migration registry."""

PR_SCHEMA = [
    """CREATE TABLE work_prs (
        url TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        origin_attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
        last_attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
        origin_session_id TEXT NOT NULL,
        last_session_id TEXT NOT NULL,
        workspace TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        polled_at INTEGER,
        closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)),
        head_sha TEXT
    )""",
    """CREATE TABLE work_pr_batches (
        id TEXT PRIMARY KEY,
        pr_url TEXT NOT NULL REFERENCES work_prs(url) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('dispatching','delivered','uncertain','rejected')),
        created_at INTEGER NOT NULL,
        receipt TEXT
    )""",
    """CREATE TABLE work_pr_comments (
        pr_url TEXT NOT NULL REFERENCES work_prs(url) ON DELETE CASCADE,
        comment_id TEXT NOT NULL,
        author TEXT NOT NULL,
        body_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        received_at INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','dispatching','delivered','uncertain')),
        batch_id TEXT REFERENCES work_pr_batches(id),
        PRIMARY KEY(pr_url,comment_id)
    )""",
    """CREATE TABLE work_pr_registrations (
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
        state TEXT NOT NULL CHECK(state IN ('pending','registered','blocked')),
        workspace TEXT,
        capture_ref TEXT,
        reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(session_id,url)
    )""",
    """CREATE TABLE work_pr_inbox (
        batch_id TEXT PRIMARY KEY REFERENCES work_pr_batches(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        attempt_id INTEGER NOT NULL UNIQUE REFERENCES work_attempts(id),
        receipt TEXT NOT NULL UNIQUE,
        dossier_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    'CREATE INDEX work_pr_comments_pending ON work_pr_comments(status,pr_url)',
]
