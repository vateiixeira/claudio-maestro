"""Pure migration-28 statements for backend-issued CI evidence receipts."""

CI_SCHEMA = [
    """CREATE TABLE work_ci_receipts (
        evidence_ref TEXT PRIMARY KEY,
        attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
        session_id TEXT NOT NULL,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        work_revision INTEGER NOT NULL,
        source_revision TEXT,
        dossier_ref TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        target_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    'CREATE INDEX work_ci_receipts_attempt ON work_ci_receipts(attempt_id)',
]
