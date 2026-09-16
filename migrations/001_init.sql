PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_type TEXT,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    transcript TEXT,
    summary_json TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_content_hash_active
ON recordings(content_hash)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_recordings_created_at
ON recordings(created_at DESC);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'transcribing', 'summarizing', 'done', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    retried_by_task_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
    FOREIGN KEY(retried_by_task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_recording_created_at
ON tasks(recording_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_status
ON tasks(status);
