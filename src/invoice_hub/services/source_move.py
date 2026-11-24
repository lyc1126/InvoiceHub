"""Period folder check and confirmed moves of misfiled source files (WS-05 stage 2).

Some company folders are kept in period subfolders (进项抵扣/5月, 已抵扣项/10月份属期抵扣项). A file's
period always comes from its content (the deduction export's 税款所属期, a statement's dates); the
folder name is only compared with it to point out a file that seems to sit in the wrong folder. It
never feeds any calculation.

Moving follows the delete flow: a prepared plan the user confirms, the file signature re-checked
before each move, the intent fsynced to a journal before the rename and the outcome after it. A lost
response only reads the journal; nothing is retried. A move never overwrites, never follows a link,
stays inside the same company subfolder, and does not touch the monitored invoice folder.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.storage import atomic_write_json, read_json_object

MOVE_KEYS = {"input_deduction_dir": (".xlsx",), "bank_flow_dir": (".pdf",)}
NEW_FOLDER = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_WITH_YEAR = re.compile(r"(?P<y>20\d{2})\s*[-年._/]?\s*(?P<m>1[0-2]|0?[1-9])(?!\d)")
_MONTH_ONLY = re.compile(r"^(?P<m>1[0-2]|0?[1-9])\s*月")
EXPIRY_SECONDS = 300


class SourceMoveError(CompanyRegistryError):
    def __init__(self, message: str, *, code: str = "SOURCE_MOVE_INVALID", status_code: int = 422) -> None:
        super().__init__(code, message, status_code=status_code)


def folder_period(name: str) -> tuple[int | None, int] | None:
    """(year or None, month) a folder name suggests ("2026-07", "2026年7月", "6月", "10月份属期抵扣项"), else None."""
    match = _WITH_YEAR.search(name)
    if match:
        return int(match["y"]), int(match["m"])
    match = _MONTH_ONLY.match(name.strip())
    return (None, int(match["m"])) if match else None


def _label(period: tuple[int | None, int]) -> str:
    return f"{period[0]}-{period[1]:02d}" if period[0] else f"{period[1]} 月"


def _agrees(folder: tuple[int | None, int], content: str) -> bool:
    year, month = int(content[:4]), int(content[5:7])
    return folder[1] == month and (folder[0] is None or folder[0] == year)


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
        return True
    except ValueError:
        return False


def _no_links(path: Path, root: Path) -> None:
    for part in (path, *path.parents):
        if part == root:
            return
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise SourceMoveError("链接文件或链接目录不能移动。")


def _signature(path: Path, root: Path, suffixes: tuple[str, ...]) -> list[int]:
    candidate = Path(os.path.abspath(path))
    if not _inside(candidate, root) or candidate == Path(os.path.abspath(root)):
        raise SourceMoveError("只能移动该子目录内的文件。")
    _no_links(candidate, Path(os.path.abspath(root)))
    if candidate.suffix.lower() not in suffixes or not candidate.is_file():
        raise SourceMoveError("文件已移动、删除或不受支持，请刷新核对结果。")
    stat = candidate.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def _content_periods(root: Path, key: str) -> dict[Path, str | None]:
    """File -> YYYY-MM from its content (None: no single period). Unreadable files are left out."""
    out: dict[Path, str | None] = {}
    if key == "input_deduction_dir":
        from invoice_hub.services.company_deduction import DeductionFormatError, parse_deduction_workbook

        for path in sorted(root.rglob("*.xlsx")):
            if path.name.startswith(("~$", ".")) or path.is_symlink():
                continue
            try:
                out[path] = parse_deduction_workbook(path).period
            except (DeductionFormatError, OSError, ValueError, KeyError):
                continue
    else:
        from invoice_hub.bank.workpaper import discover

        # One file at a time: a statement only records its file name, and two folders may hold the same name.
        for path in sorted(root.rglob("*.pdf")):
            if any(part.startswith(".") for part in path.relative_to(root).parts) or path.is_symlink():
                continue
            try:
                statements = discover([path], parse_receipts=False).statements
            except (OSError, ValueError, RuntimeError):
                continue
            if len(statements) == 1:
                statement = statements[0]
                same = statement.period_start.strftime("%Y-%m") == statement.period_end.strftime("%Y-%m")
                out[path] = statement.period_start.strftime("%Y-%m") if same else None
    return out


def period_folder_check(root: Path, key: str) -> dict:
    """Read-only: files in period-named folders whose content says another period, with a target to move to."""
    if key not in MOVE_KEYS:
        raise SourceMoveError("属期文件夹核对只用于进项抵扣与银行流水目录。")
    folders: list[tuple[Path, tuple[int | None, int]]] = []
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        period_hint = folder_period(path.name) if path.is_dir() and not path.is_symlink() else None
        if period_hint:
            folders.append((path, period_hint))
    items = []
    for path, period in _content_periods(root, key).items():
        folder = path.parent
        hint = folder_period(folder.name) if folder != root else None
        status = "unknown" if period is None else "outside" if hint is None else "ok" if _agrees(hint, period) else "mismatch"
        target = ""
        if period:
            existing = next((path for path, hint_of in folders if _agrees(hint_of, period)), None)
            target = existing.name if existing else period
        items.append({
            "file": path.relative_to(root).as_posix(), "name": path.name,
            "folder": "" if folder == root else folder.relative_to(root).as_posix(),
            "folder_period": _label(hint) if hint else "", "content_period": period or "",
            "status": status, "target": target if status in ("mismatch", "outside") else "",
            "target_exists": bool(target) and (root / target).is_dir(),
        })
    items.sort(key=lambda item: (item["status"] != "mismatch", item["file"]))
    return {"key": key, "folders": [{"name": path.name, "period": _label(hint_of)} for path, hint_of in folders],
            "items": items, "mismatched": sum(1 for item in items if item["status"] == "mismatch")}


class SourceMoveService:
    """Durable move plans and per-file outcomes under runtime/local_state/source-moves/."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, job_id: str) -> Path:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise SourceMoveError("移动确认已失效，请重新核对。", status_code=404)
        return self.root / f"{job_id}.json"

    def _save(self, job: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path(job["job_id"]), job)

    def get(self, job_id: str) -> dict:
        job = read_json_object(self._path(job_id))
        if not job:
            raise SourceMoveError("移动记录不存在，请刷新核对结果。", status_code=404)
        journal = self._path(job_id).with_suffix(".jsonl")
        if job["state"] == "running" and journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                    job["files"][event["index"]].update(event["result"])
                except (ValueError, KeyError, IndexError):
                    break  # An interrupted final write is not evidence of completion.
        job["moved_count"] = sum(file["status"] == "moved" for file in job["files"])
        return job

    def _record(self, job: dict, index: int) -> None:
        file = job["files"][index]
        event = {"index": index, "result": {key: file[key] for key in ("status", "message") if key in file}}
        with self._path(job["job_id"]).with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def prepare(self, *, company_id: str, key: str, root: Path, items: list, guard: Path | None) -> dict:
        if key not in MOVE_KEYS:
            raise SourceMoveError("只能整理进项抵扣与银行流水目录的文件。")
        if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
            raise SourceMoveError("没有要移动的文件。")
        root = Path(os.path.abspath(root))
        if guard is not None and (_inside(root, guard) or _inside(guard, root)):
            # The monitored invoice folder belongs to the monitor; its files move only through its own flow.
            raise SourceMoveError("这个目录与当前监控目录重叠，不能在这里移动文件。")
        files, seen = [], set()
        for item in items:
            source = root / str(item.get("file") or "")
            target_name = str(item.get("target") or "")
            existing = root / target_name
            is_new = not existing.exists()
            if is_new and not NEW_FOLDER.match(target_name):
                raise SourceMoveError("新建的属期文件夹须命名为 YYYY-MM。")
            if not is_new and (not existing.is_dir() or existing.is_symlink() or existing.parent != root or not folder_period(target_name)):
                raise SourceMoveError(f"目标“{target_name}”不是该目录下的属期文件夹。")
            signature = _signature(source, root, MOVE_KEYS[key])
            destination = existing / source.name
            if source.parent == existing:
                raise SourceMoveError(f"{source.name} 已在 {target_name} 里。")
            if destination.exists() or str(destination) in seen:
                raise SourceMoveError(f"{target_name} 里已有同名文件 {source.name}，不会覆盖。")
            seen.add(str(destination))
            files.append({"path": str(source), "file": source.relative_to(root).as_posix(), "target": target_name,
                          "new_folder": is_new, "destination": str(destination), "signature": signature, "status": "pending"})
        job = {"job_id": uuid.uuid4().hex, "company_id": company_id, "key": key, "root": str(root),
               "created_at": time.time(), "state": "prepared", "files": files}
        self._save(job)
        return self.get(job["job_id"])

    def commit(self, job_id: str, *, company_id: str, confirmed: object) -> dict:
        if confirmed is not True:
            raise SourceMoveError("移动需要确认。")
        job = self.get(job_id)
        # Replayed or interrupted confirmations only return what was recorded; nothing is redone.
        if job["state"] != "prepared":
            return job
        if job["company_id"] != company_id or time.time() - job["created_at"] > EXPIRY_SECONDS:
            raise SourceMoveError("确认已过期，请重新核对。", code="SOURCE_MOVE_EXPIRED", status_code=409)
        root = Path(job["root"])
        suffixes = MOVE_KEYS[job["key"]]
        for file in job["files"]:
            if _signature(Path(file["path"]), root, suffixes) != file["signature"] or Path(file["destination"]).exists():
                raise SourceMoveError("确认期间文件或目标已变化，未移动任何文件，请刷新核对结果。", code="SOURCE_MOVE_STALE", status_code=409)
        job["state"] = "running"
        self._save(job)
        for index, file in enumerate(job["files"]):
            source, destination = Path(file["path"]), Path(file["destination"])
            try:
                if _signature(source, root, suffixes) != file["signature"]:
                    raise SourceMoveError("文件已变化，后续移动已停止。")
                file["status"] = "moving"
                self._record(job, index)
                destination.parent.mkdir(exist_ok=True)
                _no_links(destination.parent, root)
                if destination.exists():
                    raise SourceMoveError(f"目标已有同名文件 {destination.name}，不会覆盖。")
                os.rename(source, destination)
                file["status"] = "moved"
                self._record(job, index)
            except Exception as exc:
                # Ambiguous outcomes are shown as they are and never retried.
                if file["status"] != "moved":
                    file["status"] = "moved" if destination.exists() and not source.exists() else "failed" if source.exists() else "unknown"
                file["message"] = str(exc)
                job["state"] = "partial"
                self._save(job)
                return self.get(job["job_id"])
        job["state"] = "completed"
        self._save(job)
        return self.get(job["job_id"])

    @staticmethod
    def public(job: dict) -> dict:
        # Paths stay on this machine: the page sees names relative to the company subfolder.
        return {"job_id": job["job_id"], "key": job["key"], "state": job["state"], "moved_count": job.get("moved_count", 0),
                "files": [{"file": file["file"], "target": file["target"], "new_folder": file["new_folder"],
                           "status": file["status"], "message": file.get("message", "")} for file in job["files"]]}
