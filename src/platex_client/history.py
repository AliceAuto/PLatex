from __future__ import annotations

from contextlib import closing
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

from .models import ClipboardEvent


@dataclass(slots=True)
class HistoryStore:
    db_path: Path | None = None

    def __post_init__(self) -> None:
        if self.db_path is None:
            base_dir = Path(user_data_dir("PLatexClient", "Copilot"))
            base_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = base_dir / "history.sqlite3"
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
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
            connection.execute("CREATE INDEX IF NOT EXISTS idx_clipboard_history_created_at ON clipboard_history(created_at DESC)")
            connection.commit()

    def add(self, event: ClipboardEvent) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO clipboard_history (
                    created_at, image_hash, image_width, image_height,
                    latex, source, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.created_at.astimezone(timezone.utc).isoformat(),
                    event.image_hash,
                    event.image_width,
                    event.image_height,
                    event.latex,
                    event.source,
                    event.status,
                    event.error,
                ),
            )
            connection.commit()

    def latest(self) -> ClipboardEvent | None:
        rows = self.list_recent(limit=1)
        return rows[0] if rows else None

    def list_recent(self, limit: int = 20) -> list[ClipboardEvent]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
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