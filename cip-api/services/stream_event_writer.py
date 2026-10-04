"""
Stream Event Writer (same design as sdlc-api/automation/services/stream_event_writer.py).

Every agent pushes progress events here; the SSE endpoint reads them by task_id and cursor.
SQLite in WAL mode lets the writer and the SSE readers work at the same time.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import aiosqlite


class StreamStatus(str, Enum):
    SYSTEM_START = "SYSTEM_START"
    START = "START"
    PROGRESS = "PROGRESS"
    COMMAND = "COMMAND"
    END = "END"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    SYSTEM_END = "SYSTEM_END"


class StreamEventWriter:
    """Singleton writer for stream events."""

    _instance: Optional["StreamEventWriter"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._conn = None
        return cls._instance

    async def initialize(self, db_path: str | Path):
        """Open the database (WAL mode) and create the table."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(str(db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS stream_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                ts REAL NOT NULL DEFAULT (strftime('%s','now')),
                node TEXT, parent TEXT, status TEXT, message TEXT, data TEXT
            )""")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_cursor ON stream_events(task_id, id)")
        await self._conn.commit()

    async def push(self, task_id: str, node: str, status: StreamStatus | str, message: str = "",
                   parent: str = "", data: Any = None) -> None:
        """Push one event."""
        if self._conn is None:
            return
        await self._conn.execute(
            "INSERT INTO stream_events (task_id, node, parent, status, message, data) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, node, parent, getattr(status, "value", status), message[:4000],
             json.dumps(data, default=str)[:200_000] if data is not None else None),
        )
        await self._conn.commit()

    async def read(self, task_id: str, after_id: int = 0, limit: int = 500) -> list[dict]:
        """Events of a task after a cursor (for SSE)."""
        if self._conn is None:
            return []
        async with self._conn.execute(
            "SELECT id, ts, node, parent, status, message, data FROM stream_events WHERE task_id=? AND id>? ORDER BY id LIMIT ?",
            (task_id, after_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "ts": r[1], "node": r[2], "parent": r[3], "status": r[4], "message": r[5],
                 "data": json.loads(r[6]) if r[6] else None} for r in rows]

    async def close(self):
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


stream_writer = StreamEventWriter()
