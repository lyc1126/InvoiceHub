"""Source-linked, rebuildable recognition sessions, separate from TargetProfile projections."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.extraction.parsers import SUPPORTED_EXTS, extract_invoice_record
from invoice_hub.platform.host_rpc import child_environment
from invoice_hub.storage.files import atomic_write_json
from invoice_hub.services.file_preview import FilePreviewError, FilePreviewService, FilePreviewSource

MAX_BYTES = 32 * 1024 * 1024
MAX_HISTORY = 200


class TemporaryRecognitionError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_BYTES:
        raise TemporaryRecognitionError("请选择不超过 32 MB 的 PDF、OFD 或 XML 文件。")
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source(item: dict, root: Path) -> Path:
    path = Path(item["path"])
    return path if path.is_absolute() else root / path


def _available(item: dict, root: Path, *, content: bool = False) -> bool:
    try:
        path = _source(item, root)
        return _signature(path) == item["signature"] and (
            not content or not item.get("digest") or _digest(path) == item["digest"]
        )
    except (OSError, ValueError):
        return False


def recognize_job(job_path: Path, root: Path) -> None:
    job = _read(job_path)
    for item in job["items"]:
        # The worker only reads explicitly selected sources; it never scans or writes watch_dir.
        try:
            if not _available(item, root):
                raise TemporaryRecognitionError("源文件已移动、删除或发生变化，请重新选择。")
            source = _source(item, root)
            digest = _digest(source)
            record = extract_invoice_record(source).model_dump(mode="json")
            if not _available(item, root) or digest != _digest(source):
                raise TemporaryRecognitionError("识别期间源文件发生变化，请重新选择。")
            record.pop("source_path", None)
            item.update(result=record, digest=digest, status="ready" if record.get("invoice_number") or record.get("amount") else "review")
        except Exception:
            item.update(status="error", error="未能读取该文件，可能已移动、删除或发生变化。请重新选择后重试。")
        job["completed"] += 1
        atomic_write_json(job_path, job)
    job.update(status="ready", finished_at=utc_now_text())
    atomic_write_json(job_path, job)


class TemporaryRecognitionService:
    def __init__(self, directory: Path, root: Path, *, previews: FilePreviewService | None = None):
        self.directory, self.root = directory, root
        directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._grants: dict[str, dict] = {}
        self._previews = previews or FilePreviewService()
        self._preview_jobs: dict[tuple[str | None, str], str] = {}
        self._process: subprocess.Popen | None = None
        self._active: str | None = None
        self._started = 0.0
        # A prior backend's half-written session is diagnostic history, never a completed result.
        for path in directory.glob("session-*.json"):
            try:
                job = _read(path)
                if job["status"] == "running":
                    job["status"] = "interrupted"
                    atomic_write_json(path, job)
            except (OSError, ValueError, KeyError):
                continue

    def settings(self) -> dict:
        try:
            value = _read(self.directory / "settings.json")
            return {"batch_limit": min(50, max(1, int(value["batch_limit"]))), "auto_open": value["auto_open"] is True}
        except (OSError, ValueError, KeyError, TypeError):
            return {"batch_limit": 20, "auto_open": True}

    def save_settings(self, value: dict) -> dict:
        if set(value) != {"batch_limit", "auto_open"} or type(value.get("batch_limit")) is not int or not 1 <= value["batch_limit"] <= 50 or type(value.get("auto_open")) is not bool:
            raise TemporaryRecognitionError("每批文件上限应为 1–50，自动打开应为开关值。")
        with self._lock:
            atomic_write_json(self.directory / "settings.json", value)
        return value

    def register(self, paths: list[str]) -> list[dict]:
        if not paths or len(paths) > self.settings()["batch_limit"]:
            raise TemporaryRecognitionError("文件数量超出每批上限，请减少文件或调整设置。")
        selected = []
        seen = set()
        with self._lock:
            self._grants = {key: item for key, item in self._grants.items() if time.monotonic() - item["created"] < 1800}
            if len(self._grants) + len(paths) > 500:
                raise TemporaryRecognitionError("待选文件过多，请刷新页面后稍后重试。", 429)
            for raw in paths:
                path = Path(raw).expanduser().absolute()
                if path.suffix.lower() not in SUPPORTED_EXTS:
                    raise TemporaryRecognitionError("当前支持 PDF、OFD、XML；图片和扫描件需要 OCR，暂不支持。")
                # Retain the selected path rather than following a symlink into a different source directory.
                if path.is_symlink():
                    raise TemporaryRecognitionError("请选择原文件，不支持文件快捷链接。")
                try:
                    signature = _signature(path)
                except OSError:
                    raise TemporaryRecognitionError("源文件不可读取，请重新选择。") from None
                identity = str(path)
                if identity in seen:
                    continue
                seen.add(identity)
                token = uuid.uuid4().hex
                try:
                    stored = str(path.relative_to(self.root))
                except ValueError:
                    stored = str(path)
                item = {"id": token, "path": stored, "name": path.name, "signature": signature, "created": time.monotonic()}
                selected.append(item)
            for item in selected:
                self._grants[item["id"]] = item
        return [{"id": item["id"], "name": item["name"], "size": item["signature"][2]} for item in selected]

    def _path(self, session_id: str) -> Path:
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise TemporaryRecognitionError("识别记录不存在。", 404)
        return self.directory / f"session-{session_id}.json"

    def _load(self, session_id: str) -> dict:
        try:
            return _read(self._path(session_id))
        except (OSError, ValueError):
            raise TemporaryRecognitionError("识别记录不存在或已损坏。", 404) from None

    def _reap(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None and time.monotonic() - self._started < 300:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        job = self._load(self._active)
        if job["status"] == "running":
            job["status"] = "interrupted"
            atomic_write_json(self._path(job["id"]), job)
        if self._process.stdin:
            self._process.stdin.close()
        self._process, self._active = None, None

    def start(self, ids: list[str]) -> dict:
        with self._lock:
            self._reap()
            if self._process:
                raise TemporaryRecognitionError("已有一批文件正在识别，请稍后再试。", 409)
            if not ids or len(ids) > self.settings()["batch_limit"] or len(set(ids)) != len(ids):
                raise TemporaryRecognitionError("请选择数量符合上限且不重复的文件。")
            if len(list(self.directory.glob("session-*.json"))) >= MAX_HISTORY:
                raise TemporaryRecognitionError("历史记录已达 200 条，请先删除不需要的记录。", 409)
            items = []
            for token in ids:
                item = self._grants.get(token)
                if not item or time.monotonic() - item["created"] >= 1800 or not _available(item, self.root):
                    raise TemporaryRecognitionError("文件选择已过期或源文件发生变化，请重新选择。", 409)
                items.append({k: v for k, v in item.items() if k != "created"} | {"status": "pending"})
            if len({item["path"] for item in items}) != len(items):
                raise TemporaryRecognitionError("同一源文件只能添加一次，请移除重复项。")
            session_id = uuid.uuid4().hex
            job = {"id": session_id, "title": items[0]["name"] + (f" 等 {len(items)} 个文件" if len(items) > 1 else ""), "created_at": utc_now_text(), "status": "running", "completed": 0, "items": items}
            path = self._path(session_id)
            atomic_write_json(path, job)
            try:
                self._process = subprocess.Popen([sys.executable, "-m", __name__, str(path), str(self.root)], env=child_environment(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                job["status"] = "interrupted"
                atomic_write_json(path, job)
                raise TemporaryRecognitionError("无法启动识别，请稍后重试。", 503) from None
            self._active, self._started = session_id, time.monotonic()
            return self._public(job)

    def _public(self, job: dict, *, results: bool = False) -> dict:
        missing = [item["name"] for item in job["items"] if not _available(item, self.root, content=results)]
        value = {key: job[key] for key in ("id", "title", "created_at", "status", "completed")}
        value.update(count=len(job["items"]), unavailable=missing)
        if results and not missing:
            value["items"] = [{key: val for key, val in item.items() if key in {"id", "name", "result", "status", "error"}} for item in job["items"]]
        return value

    def history(self) -> list[dict]:
        with self._lock:
            self._reap()
            jobs = []
            for path in self.directory.glob("session-*.json"):
                try:
                    jobs.append(self._public(_read(path)))
                except (OSError, ValueError, KeyError):
                    continue
            return sorted(jobs, key=lambda job: job["created_at"], reverse=True)

    def get(self, session_id: str) -> dict:
        with self._lock:
            self._reap()
            # Do not return even cached invoice fields when any source in this thread is invalid.
            return self._public(self._load(session_id), results=True)

    def _preview_source(self, token: str, session_id: str | None) -> dict:
        if session_id:
            items = self._load(session_id)["items"]
            if any(not _available(item, self.root, content=True) for item in items):
                raise TemporaryRecognitionError("原文件已移动、删除或发生变化，不可查看此记录。", 409)
            item = next((item for item in items if item["id"] == token), None)
        else:
            item = self._grants.get(token)
            if item and time.monotonic() - item["created"] >= 1800:
                item = None
        if not item:
            raise TemporaryRecognitionError("文件选择已过期或不属于此记录，请重新选择。", 404)
        if not _available(item, self.root, content=True):
            raise TemporaryRecognitionError("原文件已移动、删除或发生变化，请重新选择。", 409)
        return item

    def preview(self, token: str, session_id: str | None = None, *, page: int | None = None, text: bool = False):
        # Only picker grants or an existing thread authorize sources outside watch_dir.
        # Validate the whole thread before AND after cache access; cached pixels are never a backup.
        with self._lock:
            item = self._preview_source(token, session_id)
            if not session_id and not item.get("digest"):
                try:
                    item["digest"] = _digest(_source(item, self.root))
                except OSError:
                    raise TemporaryRecognitionError("原文件已移动、删除或无法读取，请重新选择。", 409) from None
            key = (session_id, token)
            job = None
            if key in self._preview_jobs:
                try:
                    job = self._previews.get_job(self._preview_jobs[key])
                except FilePreviewError as exc:
                    if exc.status_code not in {404, 410}:
                        raise
            if job is None:
                job = self._previews.create_job([FilePreviewSource(_source(item, self.root), item["name"])])
                if len(self._preview_jobs) >= 8:
                    self._preview_jobs.pop(next(iter(self._preview_jobs)))
                self._preview_jobs[key] = job.job_id
            entry = job.files[0]
            if page is not None:
                result = self._previews.get_page(job.job_id, 1, page).content
            elif text:
                value = self._previews.get_text(job.job_id, 1)
                result = {"text": value.content, "encoding": value.encoding, "truncated": value.truncated, "had_replacements": value.had_replacements}
            else:
                result = {"name": entry.file_name, "type": entry.preview_type, "pages": entry.page_count, "reason": entry.reason, "size": entry.size}
            self._preview_source(token, session_id)
            if not session_id:
                item["created"] = time.monotonic()  # An open, revalidated preview keeps its selection alive.
            return result

    def rename(self, session_id: str, title: str) -> dict:
        title = title.strip()
        if not title or len(title) > 160 or any(ord(c) < 32 for c in title):
            raise TemporaryRecognitionError("名称应为 1–160 个可见字符。")
        with self._lock:
            self._reap()
            job = self._load(session_id)
            if job["status"] == "running":
                raise TemporaryRecognitionError("识别完成后才能重命名。", 409)
            job["title"] = title
            atomic_write_json(self._path(session_id), job)
            return self._public(job)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._reap()
            if self._load(session_id)["status"] == "running":
                raise TemporaryRecognitionError("识别完成后才能删除记录。", 409)
            self._path(session_id).unlink()  # Only derived session metadata; never source files.

    def close(self) -> None:
        with self._lock:
            self._previews.clear()
            self._preview_jobs.clear()
            if self._process:
                self._started = time.monotonic() - 301
                self._reap()


if __name__ == "__main__":
    # The parent owns this pipe. EOF on backend crash stops orphan writers before a new backend resumes history.
    def parent_closed():
        sys.stdin.buffer.read()
        os._exit(1)
    threading.Thread(target=parent_closed, daemon=True).start()
    deadline = threading.Timer(300, lambda: os._exit(1))
    deadline.daemon = True
    deadline.start()
    recognize_job(Path(sys.argv[1]), Path(sys.argv[2]))
