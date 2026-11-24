"""Confirmation plans and durable per-file outcomes, never invoice storage."""
from __future__ import annotations

import os
import json
import time
import uuid
from pathlib import Path

from invoice_hub.platform.trash import move_to_trash
from invoice_hub.storage import atomic_write_json, read_json_object


class TrashError(ValueError):
    pass


def source_signature(path: Path, watch_dir: Path) -> list[int]:
    root = watch_dir.resolve()
    candidate = Path(os.path.abspath(path))
    if not candidate.is_relative_to(root) or candidate == root:
        raise TrashError("只能删除当前发票目录内的勾选源文件。")
    # Do not follow a symlink/junction to another file, including parent directories.
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise TrashError("链接文件或链接目录不能通过此操作删除。")
    if candidate.suffix.lower() not in {".pdf", ".ofd", ".xml"} or not candidate.is_file():
        raise TrashError("源文件已移动、删除或不受支持，请刷新列表。")
    stat = candidate.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


class InvoiceTrashService:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, job_id: str) -> Path:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise TrashError("删除确认已失效，请重新选择。")
        return self.root / f"{job_id}.json"

    def _save(self, job: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path(job["job_id"]), job)

    def get(self, job_id: str) -> dict:
        job = read_json_object(self._path(job_id))
        if not job:
            raise TrashError("删除记录不存在，请刷新列表并核对源文件。")
        journal = self._path(job_id).with_suffix(".jsonl")
        if job["state"] == "running" and journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                    job["files"][event["index"]].update(event["result"])
                except (ValueError, KeyError, IndexError):
                    break  # An interrupted final write is not evidence of completion.
            job["trashed_count"] = sum(file["status"] == "trashed" for file in job["files"])
        return job

    def _record_file(self, job: dict, index: int) -> None:
        file = job["files"][index]
        event = {"index": index, "result": {key: file[key] for key in ("status", "message") if key in file}}
        # Append only this outcome: rewriting the full selection after each move makes
        # large batches quadratic. Fsync the intent before calling the native API.
        with self._path(job["job_id"]).with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def prepare(self, target_id: str, watch_dir: Path, items: list[dict]) -> dict:
        files = {}
        for item in items:
            path = Path(item["source_path"])
            files.setdefault(str(path), {"path": str(path), "name": str(path.relative_to(watch_dir)),
                "signature": source_signature(path, watch_dir), "status": "pending"})
        job = {"job_id": uuid.uuid4().hex, "target_id": target_id, "created_at": time.time(),
               "state": "prepared", "files": list(files.values()), "trashed_count": 0}
        self._save(job)
        return job

    def commit(self, job_id: str, target_id: str, watch_dir: Path) -> dict:
        job = self.get(job_id)
        # Replayed or interrupted commits only return recorded outcomes. A replacement
        # at the same filename must never be picked up by retrying the confirmation.
        if job["state"] != "prepared":
            return job
        if job["target_id"] != target_id or time.time() - job["created_at"] > 300:
            raise TrashError("目录已切换或确认已过期，请重新勾选。")
        for file in job["files"]:
            if source_signature(Path(file["path"]), watch_dir) != file["signature"]:
                raise TrashError("确认期间源文件已变化，未删除任何文件，请刷新列表。")
        job["state"] = "running"
        self._save(job)
        for index, file in enumerate(job["files"]):
            try:
                if source_signature(Path(file["path"]), watch_dir) != file["signature"]:
                    raise TrashError("源文件已变化，后续操作已停止。")
                file["status"] = "moving"
                self._record_file(job, index)
                move_to_trash(Path(file["path"]))
                file["status"] = "trashed"
                job["trashed_count"] += 1
                self._record_file(job, index)
            except Exception as exc:
                # A native failure can be ambiguous: expose it and stop, never retry.
                if file["status"] != "trashed":
                    file["status"] = "failed" if Path(file["path"]).exists() else "unknown"
                file["message"] = str(exc)
                job["state"] = "partial"
                self._save(job)
                return job
        job["state"] = "completed"
        self._save(job)
        return job

    @staticmethod
    def public(job: dict) -> dict:
        return {**{key: job[key] for key in ("job_id", "state", "target_id", "trashed_count")},
                "files": [{key: value for key, value in file.items() if key in {"name", "status", "message"}}
                          for file in job["files"]]}
