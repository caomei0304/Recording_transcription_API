import sqlite3
import uuid
from typing import Any

from app.database import Database, parse_summary, serialize_summary, utc_now


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def row_to_task(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "task_id": row["id"],
        "recording_id": row["recording_id"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def create_recording_with_task(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        file_path: str,
        content_type: str | None,
        extension: str,
        size_bytes: int,
        content_hash: str,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        recording_id = new_id("rec")
        task_id = new_id("task")
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO recordings (
                        id, original_filename, stored_filename, file_path, content_type,
                        extension, size_bytes, content_hash, idempotency_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        recording_id,
                        original_filename,
                        stored_filename,
                        file_path,
                        content_type,
                        extension,
                        size_bytes,
                        content_hash,
                        idempotency_key,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO tasks (id, recording_id, status, created_at, updated_at)
                    VALUES (?, ?, 'pending', ?, ?)
                    """,
                    (task_id, recording_id, now, now),
                )
        except sqlite3.IntegrityError:
            existing = self.find_existing_recording(content_hash, idempotency_key)
            if existing is None:
                raise
            return existing, False
        return {"recording_id": recording_id, "task_id": task_id, "status": "pending"}, True

    def find_existing_recording(self, content_hash: str, idempotency_key: str | None) -> dict[str, Any] | None:
        if idempotency_key:
            row = self.db.fetchone(
                "SELECT * FROM recordings WHERE idempotency_key = ? AND deleted_at IS NULL",
                (idempotency_key,),
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM recordings WHERE content_hash = ? AND deleted_at IS NULL",
                (content_hash,),
            )
        if not row:
            return None
        task = self.latest_task_for_recording(row["id"])
        if task is None:
            return None
        return {"recording_id": row["id"], "task_id": task["task_id"], "status": task["status"]}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return row_to_task(self.db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,)))

    def latest_task_for_recording(self, recording_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM tasks WHERE recording_id = ? ORDER BY created_at DESC LIMIT 1",
            (recording_id,),
        )
        return row_to_task(row)

    def list_recordings(self, page: int, page_size: int) -> tuple[int, list[dict[str, Any]]]:
        offset = (page - 1) * page_size
        total_row = self.db.fetchone("SELECT COUNT(*) AS total FROM recordings WHERE deleted_at IS NULL")
        rows = self.db.fetchall(
            """
            SELECT * FROM recordings
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        items = []
        for row in rows:
            items.append(
                {
                    "recording_id": row["id"],
                    "filename": row["original_filename"],
                    "size_bytes": row["size_bytes"],
                    "created_at": row["created_at"],
                    "latest_task": self.latest_task_for_recording(row["id"]),
                }
            )
        return int(total_row["total"] if total_row else 0), items

    def get_recording_detail(self, recording_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM recordings WHERE id = ? AND deleted_at IS NULL",
            (recording_id,),
        )
        if not row:
            return None
        task = self.latest_task_for_recording(recording_id)
        return {
            "recording_id": row["id"],
            "filename": row["original_filename"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
            "latest_task": task,
            "transcript": row["transcript"] if task and task["status"] == "done" else None,
            "summary": parse_summary(row["summary_json"]) if task and task["status"] == "done" else None,
        }

    def delete_recording(self, recording_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM recordings WHERE id = ? AND deleted_at IS NULL",
                (recording_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE recordings SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, recording_id),
            )
            return dict(row)

    def retry_task(self, task_id: str) -> tuple[dict[str, Any], bool] | None:
        now = utc_now()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            task = dict(row)
            if task["status"] != "failed":
                return task, False
            if task["retried_by_task_id"]:
                retry = conn.execute("SELECT * FROM tasks WHERE id = ?", (task["retried_by_task_id"],)).fetchone()
                return row_to_task(dict(retry)), True
            new_task_id = new_id("task")
            conn.execute(
                """
                INSERT INTO tasks (id, recording_id, status, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (new_task_id, task["recording_id"], now, now),
            )
            conn.execute(
                "UPDATE tasks SET retried_by_task_id = ?, updated_at = ? WHERE id = ?",
                (new_task_id, now, task_id),
            )
            retry = conn.execute("SELECT * FROM tasks WHERE id = ?", (new_task_id,)).fetchone()
            return row_to_task(dict(retry)), True

    def recoverable_task_ids(self) -> list[str]:
        rows = self.db.fetchall(
            """
            SELECT t.id FROM tasks t
            JOIN recordings r ON r.id = t.recording_id
            WHERE t.status IN ('pending', 'transcribing', 'summarizing')
              AND r.deleted_at IS NULL
            ORDER BY t.created_at ASC
            """
        )
        return [row["id"] for row in rows]

    def mark_status(self, task_id: str, status: str, error: str | None = None, finished: bool = False) -> None:
        now = utc_now()
        started_at_expr = "COALESCE(started_at, ?)" if status in {"transcribing", "summarizing"} else "started_at"
        finished_at = now if finished else None
        params: list[Any] = [status, error, now]
        if status in {"transcribing", "summarizing"}:
            params.append(now)
        params.extend([finished_at, task_id])
        self.db.execute(
            f"""
            UPDATE tasks
            SET status = ?, error = ?, updated_at = ?, started_at = {started_at_expr}, finished_at = COALESCE(?, finished_at)
            WHERE id = ?
            """,
            tuple(params),
        )

    def increment_attempt(self, task_id: str) -> int:
        now = utc_now()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            row = conn.execute("SELECT attempt_count FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return int(row["attempt_count"])

    def save_transcript(self, recording_id: str, transcript: str) -> None:
        now = utc_now()
        self.db.execute(
            "UPDATE recordings SET transcript = ?, updated_at = ? WHERE id = ?",
            (transcript, now, recording_id),
        )

    def save_summary(self, recording_id: str, summary: dict[str, Any]) -> None:
        now = utc_now()
        self.db.execute(
            "UPDATE recordings SET summary_json = ?, updated_at = ? WHERE id = ?",
            (serialize_summary(summary), now, recording_id),
        )
