from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

from .models import ClipboardEvent


_MAX_FIELD_LENGTHS = {
    "image_hash": 128,
    "latex": 65536,
    "source": 512,
    "status": 32,
    "error": 4096,
}

_MAX_DB_SIZE_BYTES = 100 * 1024 * 1024
_MAX_HISTORY_ROWS = 50000


def _truncate_field(value: str, field_name: str) -> str:
    max_len = _MAX_FIELD_LENGTHS.get(field_name, 0)
    if max_len > 0 and len(value) > max_len:
        return value[:max_len - 3] + "..."
    return value


@dataclass(slots=True)
class HistoryStore:
    db_path: Path | None = None
    _connection: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.db_path is None:
            base_dir = Path(user_data_dir("PLatexClient", "Copilot"))
            base_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = base_dir / "history.sqlite3"
        else:
            if ".." in self.db_path.parts:
                raise ValueError(f"Database path contains path traversal ('..'): {self.db_path}")
            self.db_path = self.db_path.resolve()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    _MAX_CONNECT_RETRIES = 3

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is not None:
            try:
                self._connection.execute("SELECT 1")
                return self._connection
            except Exception:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None

        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_CONNECT_RETRIES + 1):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                self._connection = conn
                return conn
            except Exception as exc:
                last_exc = exc
                if attempt < self._MAX_CONNECT_RETRIES:
                    import time
                    time.sleep(0.1 * attempt)

        raise RuntimeError(f"Failed to connect to database after {self._MAX_CONNECT_RETRIES} attempts") from last_exc

    def _initialize(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clipboard_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    image_hash TEXT NOT NULL,
                    image_width INTEGER NOT NULL,
                    image_height INTEGER NOT NULL,
                    latex TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clipboard_history_created_at ON clipboard_history(created_at DESC)")
            conn.commit()
            self._restrict_db_file_permissions()

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def add(self, event: ClipboardEvent) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO clipboard_history (
                    created_at, image_hash, image_width, image_height,
                    latex, source, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._ensure_utc(event.created_at).isoformat(),
                    _truncate_field(event.image_hash, "image_hash"),
                    event.image_width,
                    event.image_height,
                    _truncate_field(event.latex, "latex"),
                    _truncate_field(event.source, "source"),
                    _truncate_field(event.status, "status"),
                    _truncate_field(event.error, "error") if event.error else None,
                ),
            )
            conn.commit()
            self._auto_vacuum_if_needed(conn)

    def latest(self) -> ClipboardEvent | None:
        rows = self.list_recent(limit=1)
        return rows[0] if rows else None

    _MAX_QUERY_LIMIT = 10000

    def list_recent(self, limit: int = 20) -> list[ClipboardEvent]:
        if not isinstance(limit, int) or limit < 1:
            limit = 20
        if limit > self._MAX_QUERY_LIMIT:
            logger.warning("list_recent limit %d exceeds maximum %d, clamping", limit, self._MAX_QUERY_LIMIT)
            limit = self._MAX_QUERY_LIMIT
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT created_at, image_hash, image_width, image_height, latex, source, status, error
                FROM clipboard_history
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        result: list[ClipboardEvent] = []
        for row in rows:
            result.append(
                ClipboardEvent(
                    created_at=datetime.fromisoformat(row["created_at"]),
                    image_hash=row["image_hash"],
                    image_width=row["image_width"],
                    image_height=row["image_height"],
                    latex=row["latex"],
                    source=row["source"],
                    status=row["status"],
                    error=row["error"],
                )
            )
        return result

    def _restrict_db_file_permissions(self) -> None:
        if self.db_path is None or not self.db_path.exists():
            return
        try:
            if os.name != "nt":
                os.chmod(self.db_path, 0o600)
        except Exception:
            pass

    def _auto_vacuum_if_needed(self, conn: sqlite3.Connection) -> None:
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
            if row_count <= _MAX_HISTORY_ROWS:
                return
            delete_count = row_count - _MAX_HISTORY_ROWS
            conn.execute(
                "DELETE FROM clipboard_history WHERE id IN (SELECT id FROM clipboard_history ORDER BY id ASC LIMIT ?)",
                (delete_count,),
            )
            conn.commit()
            logger.info("Auto-cleaned %d old history records (was %d, max %d)", delete_count, row_count, _MAX_HISTORY_ROWS)
        except Exception as exc:
            logger.warning("Failed to auto-clean history: %s", exc)

    def close(self) -> None:
        try:
            lock = self._lock
        except AttributeError:
            return
        with lock:
            conn = self._connection
            if conn is not None:
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.commit()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
                self._connection = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
