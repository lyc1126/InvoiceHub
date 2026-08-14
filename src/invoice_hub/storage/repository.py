from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from invoice_hub.domain.models import utc_now_text


class SQLiteRepository:
    """任务、事件、设置和缓存仓库；不存发票主数据。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                  task_id TEXT PRIMARY KEY,
                  task_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  detail_json TEXT NOT NULL,
                  requested_at TEXT NOT NULL,
                  completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_type TEXT NOT NULL,
                  task_id TEXT,
                  payload_json TEXT NOT NULL,
                  error_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache (
                  key TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, utc_now_text()),
            )

    def set_json_setting(self, key: str, value: Any) -> None:
        self.set_setting(key, json.dumps(value, ensure_ascii=False))

    def get_json_setting(self, key: str, default: Any = None) -> Any:
        raw = self.get_setting(key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def create_task(self, task_id: str, task_type: str, status: str, detail: dict | None = None) -> dict:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO tasks(task_id, task_type, status, detail_json, requested_at, completed_at)
                VALUES(?, ?, ?, ?, ?, NULL)
                """,
                (task_id, task_type, status, json.dumps(detail or {}, ensure_ascii=False), utc_now_text()),
            )
        return self.get_task(task_id)

    def update_task(self, task_id: str, status: str, detail: dict | None = None, completed: bool = False) -> dict:
        with self.session() as conn:
            row = conn.execute("SELECT detail_json FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            merged = json.loads(row["detail_json"] or "{}")
            merged.update(detail or {})
            conn.execute(
                "UPDATE tasks SET status=?, detail_json=?, completed_at=? WHERE task_id=?",
                (status, json.dumps(merged, ensure_ascii=False), utc_now_text() if completed else None, task_id),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return {
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "status": row["status"],
            "detail": json.loads(row["detail_json"] or "{}"),
            "requested_at": row["requested_at"],
            "completed_at": row["completed_at"],
        }

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        now = utc_now_text()
        with self.session() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events(event_type, task_id, payload_json, error_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    task_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(error or {}, ensure_ascii=False),
                    now,
                ),
            )
            seq = int(cursor.lastrowid)
        return {"seq": seq, "event_type": event_type, "task_id": task_id, "payload": payload or {}, "error": error or {}, "ts": now}

    def list_events_after(self, after_seq: int, limit: int = 100) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                (after_seq, limit),
            ).fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "event_type": row["event_type"],
                "task_id": row["task_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "error": json.loads(row["error_json"] or "{}"),
                "ts": row["created_at"],
            }
            for row in rows
        ]

    def event_bounds(self) -> dict[str, int]:
        with self.session() as conn:
            row = conn.execute("SELECT COALESCE(MIN(seq), 0) min_seq, COALESCE(MAX(seq), 0) max_seq FROM events").fetchone()
        return {"min_seq": int(row["min_seq"]), "max_seq": int(row["max_seq"])}
