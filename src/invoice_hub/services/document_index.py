"""Disposable, resumable document catalogs. Source files remain authoritative."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from invoice_hub.domain.models import InvoiceRecord
from invoice_hub.extraction import extract_invoice_record
from invoice_hub.projections.documents import inbound_invoice_options, outbound_invoice_options
from invoice_hub.storage.files import atomic_write_json, read_csv_rows, read_json_object

CACHE_VERSION = 1


def signature(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


def _watch_parent() -> None:
    parent = multiprocessing.parent_process()
    while parent is not None and parent.is_alive():
        time.sleep(1)
    if parent is not None:
        os._exit(0)


def _raise_walk_error(error: OSError) -> None:
    raise error


def build_index(cache: str, outbound: str, detail: str, job_id: str) -> None:
    # Native PDF parsing can hold the GIL. A spawn process isolates it from health,
    # navigation and cancellation; SQLite commits retain only completed file work.
    threading.Thread(target=_watch_parent, daemon=True).start()
    folder = Path(cache)
    status = dict(job_id=job_id, state="running", phase="inbound", processed=0,
                  total=0, reused=0, errors=0, pid=os.getpid())
    last_report = 0.0

    def report(force: bool = False) -> None:
        nonlocal last_report
        if force or time.monotonic() - last_report >= 0.25:
            atomic_write_json(folder / "status.json", status)
            last_report = time.monotonic()

    try:
        report(True)
        csv = Path(detail)
        before = signature(csv)
        inbound = read_json_object(folder / "inbound.json", {})
        if inbound.get("signature") != before or inbound.get("version") != CACHE_VERSION:
            inbound = dict(signature=before, version=CACHE_VERSION,
                           items=inbound_invoice_options(read_csv_rows(csv)))
            if signature(csv) != before:
                raise RuntimeError("Cost details changed during indexing; refresh to retry")
            atomic_write_json(folder / "inbound.json", inbound)
        status["phase"] = "discovering"
        report(True)
        files = []
        if outbound:
            root = Path(outbound).resolve()
            if not root.is_dir():
                raise FileNotFoundError("Outbound directory is unavailable")
            for directory, dirs, names in os.walk(root, followlinks=False, onerror=_raise_walk_error):
                dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()
                           and not (Path(directory) / name).is_junction()]
                for name in names:
                    path = Path(directory) / name
                    if path.suffix.lower() in {".pdf", ".ofd", ".xml"} and not name.startswith("~$"):
                        if not path.is_symlink() and path.resolve().is_relative_to(root):
                            files.append(path)
                status["total"] = len(files)
                report()
        files.sort(key=lambda path: str(path).casefold())
        status.update(phase="extracting", total=len(files))
        report(True)
        with sqlite3.connect(folder / "files.sqlite3", timeout=5) as db:
            # WAL/NORMAL survives worker termination without an fsync per invoice.
            # This is a rebuildable cache; a power loss may discard recent progress.
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, signature TEXT, record TEXT, seen TEXT)")
            records = []
            for path in files:
                fingerprint = json.dumps([CACHE_VERSION, signature(path)])
                cached = db.execute("SELECT signature, record FROM files WHERE path=?", (str(path),)).fetchone()
                record = None
                if cached and cached[0] == fingerprint:
                    try:
                        record = InvoiceRecord.model_validate_json(cached[1])
                        status["reused"] += 1
                    except ValueError:
                        pass
                if record is None:
                    try:
                        record = extract_invoice_record(path)
                        if json.dumps([CACHE_VERSION, signature(path)]) != fingerprint:
                            raise RuntimeError("Source changed during extraction")
                    except Exception as error:
                        status["errors"] += 1
                        if len(status.setdefault("error_files", [])) < 10:
                            status["error_files"].append({"file_name": path.name, "message": str(error)})
                        status["processed"] += 1
                        report()
                        continue
                db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
                           (str(path), fingerprint, record.model_dump_json(), job_id))
                if not cached or cached[0] != fingerprint or status["processed"] % 50 == 0:
                    db.commit()
                records.append((path, record))
                status["processed"] += 1
                report()
            db.execute("DELETE FROM files WHERE seen != ?", (job_id,))
            db.commit()
        items = outbound_invoice_options(Path(outbound) if outbound else None, records=records)
        atomic_write_json(folder / "outbound.json", dict(job_id=job_id, items=items))
        status.update(state="ready", phase="complete", completed_at=time.time())
        report(True)
    except Exception as error:
        status.update(state="failed", message=str(error))
        report(True)


class DocumentIndex:
    def __init__(self, cache_root: Path):
        self.root = cache_root
        self.lock = threading.RLock()
        self.process = None
        self.scope = ""
        self.folder: Path | None = None
        self.job_id = ""
        self.input_signature = None
        self.last_check = 0.0
        self.last_status: dict = {}
        self.outbound_catalog: dict = {}

    def _stop(self) -> None:
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(2)
            if self.process.is_alive():
                raise RuntimeError("Document index worker could not be stopped")
            self.process.close()
            self.process = None

    def close(self) -> None:
        with self.lock:
            self._stop()

    def status(self) -> dict:
        with self.lock:
            result = read_json_object(self.folder / "status.json", {}) if self.folder else {}
            # Windows can transiently refuse a read while the worker replaces the
            # progress file. Keep the last owned status instead of reporting idle.
            if result.get("job_id") == self.job_id and result:
                self.last_status = result.copy()
            else:
                result = self.last_status.copy()
            result.setdefault("state", "idle")
            result.setdefault("job_id", self.job_id)
            alive = self.process is not None and self.process.is_alive()
            if result["state"] == "running" and not alive:
                result.update(state="interrupted", message="Loading interrupted; resume to continue")
            result["running"] = alive and result["state"] == "running"
            return result

    def ensure(self, scope: str, outbound: str, detail: Path, *, restart: bool = False, revalidate: bool = True) -> dict:
        identity = hashlib.sha256(json.dumps([CACHE_VERSION, scope, outbound, str(detail)]).encode()).hexdigest()
        with self.lock:
            current = self.status()
            scope_changed = identity != self.scope
            changed = signature(detail) != self.input_signature
            expired = revalidate and current["state"] == "ready" and time.time() - current.get("completed_at", 0) > 60
            if restart or scope_changed or ((changed or expired) and current["state"] != "cancelled"):
                self._stop()
                self.scope = identity
                self.folder = self.root / identity
                self.folder.mkdir(parents=True, exist_ok=True)
                self.job_id = uuid.uuid4().hex
                self.outbound_catalog = {}
                self.last_status = dict(job_id=self.job_id, state="running", phase="starting")
                self.input_signature = signature(detail)
                self.last_check = time.monotonic()
                atomic_write_json(self.folder / "status.json", dict(job_id=self.job_id, state="running",
                                  phase="starting", processed=0, total=0, reused=0, errors=0))
                self.process = multiprocessing.get_context("spawn").Process(
                    target=build_index, args=(str(self.folder), outbound, str(detail), self.job_id), daemon=True,
                    name="InvoiceHub document index")
                try:
                    self.process.start()
                except Exception:
                    self.process = None
                    atomic_write_json(self.folder / "status.json", dict(job_id=self.job_id, state="failed",
                                      message="Unable to start document index worker"))
                    raise
            result = self.status()
            inbound = read_json_object(self.folder / "inbound.json", {})
            if result["state"] == "ready" and not self.outbound_catalog:
                for _ in range(3):
                    candidate = read_json_object(self.folder / "outbound.json", {})
                    if candidate.get("job_id") == self.job_id and isinstance(candidate.get("items"), list):
                        self.outbound_catalog = candidate
                        break
                    time.sleep(0.01)
                if not self.outbound_catalog:
                    result.update(state="failed", message="Completed catalog is unavailable; resume to rebuild")
            outbound_data = self.outbound_catalog if result["state"] == "ready" else {}
            return dict(index=result,
                        inbound_invoices=inbound.get("items", []) if inbound.get("signature") == self.input_signature else [],
                        outbound_invoices=outbound_data.get("items", []) if outbound_data.get("job_id") == self.job_id else [])

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            if job_id != self.job_id:
                return {"ok": False, "message": "Loading task has changed; refresh its status"}
            self._stop()
            result = self.status()
            result.update(state="cancelled", running=False)
            atomic_write_json(self.folder / "status.json", result)
            return {"ok": True, "index": result}
