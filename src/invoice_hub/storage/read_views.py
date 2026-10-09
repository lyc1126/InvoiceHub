"""Rebuildable read views. CSV/source files remain authoritative."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


COST_FIELDS = {"details": "items", "project": "project_summary", "reference": "invoice_reference", "checks": "checks"}


def file_signature(path):
    try:
        stat = Path(path).stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


class ReadViews:
    def __init__(self, workspace):
        self.path = Path(workspace) / "read-views.sqlite3"

    @contextmanager
    def connect(self, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path) if write else self.path.as_uri() + "?mode=ro", uri=not write, timeout=0.2)
        try:
            if write:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
                db.execute("CREATE TABLE IF NOT EXISTS rows (name TEXT, position INTEGER, value TEXT, PRIMARY KEY(name, position))")
            with db:
                yield db
        finally:
            db.close()

    def read(self, name, page=1, page_size=100):
        if not self.path.exists():
            return {}, []
        try:
            with self.connect() as db:
                # Explicit read transaction binds metadata and rows to one revision.
                db.execute("BEGIN")
                row = db.execute("SELECT value FROM metadata WHERE name=?", (name,)).fetchone()
                if not row:
                    return {}, []
                meta = json.loads(row[0])
                query = "SELECT value FROM rows WHERE name=? ORDER BY position"
                args = [name]
                if page_size is not None:
                    query += " LIMIT ? OFFSET ?"
                    args += [page_size, (page - 1) * page_size]
                return meta, [json.loads(row[0]) for row in db.execute(query, args)]
        except (sqlite3.Error, ValueError):
            return {}, []

    @staticmethod
    def _replace(db, name, meta, rows):
        db.execute("DELETE FROM rows WHERE name=?", (name,))
        db.executemany("INSERT INTO rows VALUES (?, ?, ?)", ((name, i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)))
        db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (name, json.dumps(meta, ensure_ascii=False)))

    def save_cost(self, payload, fingerprint):
        revision = uuid.uuid4().hex
        metadata = {key: value for key, value in payload.items() if key not in COST_FIELDS.values()}
        counts = {view: len(payload[field]) for view, field in COST_FIELDS.items()}
        with self.connect(write=True) as db:
            for view, field in COST_FIELDS.items():
                self._replace(db, "cost:" + view, dict(metadata, revision=revision, counts=counts,
                              fingerprint=fingerprint, count=counts[view], provisional=False), payload[field])


class ProgressiveRows:
    """Append small batches, never rewrite a growing projection for every invoice."""

    def __init__(self, workspace, kind):
        self.views = ReadViews(workspace)
        self.kind = "partial:" + kind
        self.meta = dict(revision=uuid.uuid4().hex, state="running", pid=os.getpid(), count=0, processed=0, total=0)
        self.pending = []
        self.last_publish = 0.0

    def __enter__(self):
        with self.views.connect(write=True) as db:
            self.views._replace(db, self.kind, self.meta, [])
        return self

    def add(self, rows, processed, total):
        self.pending.extend(rows)
        self.meta.update(processed=processed, total=total)
        if (self.pending and self.meta["count"] == 0) or time.monotonic() - self.last_publish >= 0.5 or len(self.pending) >= 100:
            self.publish()

    def publish(self):
        with self.views.connect(write=True) as db:
            start = self.meta["count"]
            db.executemany("INSERT INTO rows VALUES (?, ?, ?)",
                           ((self.kind, start + i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(self.pending)))
            self.meta.update(count=start + len(self.pending), updated_at=time.time())
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (self.kind, json.dumps(self.meta)))
        self.pending.clear()
        self.last_publish = time.monotonic()

    def __exit__(self, kind, value, traceback):
        self.meta["state"] = "failed" if kind else "complete"
        self.publish()
