"""Durable export receipts: a lost response is resolved by GET, never by replay."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from invoice_hub.services.company_vouchers import VoucherDraftError, _draft_path, export_draft
from invoice_hub.storage import atomic_write_json

# export_draft raises these from its own checks before export() runs, so nothing was written.
# VOUCHER_DRAFT_UNREADABLE wraps export() itself (possibly mid-write) and must stay unknown.
_REJECTED_BEFORE_WRITE = {"VOUCHER_DRAFT_INVALID", "VOUCHER_DRAFT_BOOKS_UNAVAILABLE", "VOUCHER_DRAFT_CONFLICT"}


def _path(root: Path, token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9-]{36}", token):
        raise VoucherDraftError("VOUCHER_EXPORT_JOB_INVALID", "导出任务编号无效。")
    folder = root / "做账草稿" / "导出记录"
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (folder.parent, folder)):
        raise VoucherDraftError("VOUCHER_EXPORT_JOB_INVALID", "导出记录目录不能为链接。")
    return folder / f"{token}.json"


def _sync(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def get_export_job(root: Path, name: str, token: str) -> dict:
    path = _path(root, token)
    if not path.exists():
        raise VoucherDraftError("VOUCHER_EXPORT_JOB_NOT_FOUND", "未找到执行记录；结果仍待核对，请勿重复导出。", status_code=404)
    try:
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            raise ValueError()
        job = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(job, dict) or job.get("name") != name or job.get("state") not in {"unknown", "completed", "rejected"}:
            raise ValueError()
        return job
    except (OSError, ValueError):
        raise VoucherDraftError("VOUCHER_EXPORT_JOB_CORRUPT", "执行记录无法读取，请人工核对，禁止重放。", status_code=409) from None


def run_export_job(root: Path, name: str, body: dict) -> dict:
    # Legacy CLI/API callers keep their contract; the workspace always supplies a token.
    if body.get("dry_run") is True or not body.get("request_id"):
        return export_draft(root, name, body)
    if body.get("confirm") is not True:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "导出需要确认。")
    _draft_path(root, name)
    token = str(body["request_id"])
    path = _path(root, token)
    path.parent.mkdir(parents=True, exist_ok=True)
    intent = {"name": name, "request_id": token, "state": "unknown", "message": "执行结果待核对，请读取结果；不会重复导出。"}
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(intent, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return get_export_job(root, name, token)
    # Persist the directory entry before any workbook or history can be written. A crash
    # during export leaves an unknown receipt, including partially written multi-month output.
    _sync(path)
    try:
        result = export_draft(root, name, body)
    except VoucherDraftError as exc:
        # A definite pre-write refusal is recorded so the page can release the token; the
        # same token still never replays. Anything else keeps the unknown receipt.
        if exc.code in _REJECTED_BEFORE_WRITE:
            atomic_write_json(path, {**intent, "state": "rejected", "code": exc.code, "message": f"未导出：{exc.message}"})
            _sync(path)
        raise
    job = {**intent, **result, "state": "completed", "message": "导出结果已记录。"}
    atomic_write_json(path, job)
    _sync(path)
    return job
