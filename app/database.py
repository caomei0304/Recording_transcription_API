import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import Settings


BEIJING_TZ = timezone(timedelta(hours=8))


def utc_now() -> str:
    # API responses use Beijing time for easier local reading and debugging.
    return datetime.now(BEIJING_TZ).isoformat()


class Database:
    def __init__(self, settings: Settings):
        self.path = settings.database_path
        self._lock = threading.RLock()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migration = (Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql").read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(migration)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock, self.connect() as conn:
            return conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock, self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def transaction(self):
        return _Transaction(self)


class _Transaction:
    def __init__(self, db: Database):
        self.db = db
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        # Serialize writes because SQLite allows limited concurrent write access.
        self.db._lock.acquire()
        self.conn = sqlite3.connect(self.db.path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.conn is not None
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        self.db._lock.release()


def serialize_summary(summary: dict[str, Any] | None) -> str | None:
    if summary is None:
        return None
    return json.dumps(summary, ensure_ascii=False)


def parse_summary(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)

