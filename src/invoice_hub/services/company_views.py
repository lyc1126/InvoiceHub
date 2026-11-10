"""Per-company read-only directory views (WS-07 step 2).

For every subfolder in the company registry this service reports the last projection the app
built for that folder (its own TargetProfile, the same one it would get as watch_dir) and, on
request, whether that projection is out of date. Only the active watch_dir is monitored: other
folders are never scanned in the background, rebuilt or written here. The freshness check is a
bounded, read-only signature comparison against the folder's ``processed_files.json``; it does
not use MonitorState, whose constructor creates directories and whose loader repairs files.

Invoice lists for a non-active folder come from a throwaway ``InvoiceListService`` bound to that
folder's profile, of which only the read-only ``list_invoices`` is called. Its rows keep the
homepage shape but are marked read-only: preview, print, rename and delete stay bound to the
active directory and revalidate ``target_id``, so they cannot act on these rows.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.extraction.parsers import SUPPORTED_EXTS
from invoice_hub.monitoring.state import PROCESSED_FILE_NAME, canonical_path as monitor_path_key
from invoice_hub.projections.cost_analysis import COST_DETAIL_CSV_NAME
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.services.company_ledger import build_invoice_ledger
from invoice_hub.services.company_registry import CompanyRegistryError, CompanyRegistryService
from invoice_hub.services.invoice_list import InvoiceListService
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig, target_profile_for
from invoice_hub.targets.companies import company_taxpayer_for

FRESHNESS_MAX_ENTRIES = 20_000
FRESHNESS_MAX_SECONDS = 2.0
FRESHNESS_MESSAGES = {
    "monitored": "当前监控目录，由监控自动保持最新。",
    "fresh": "与上次汇总一致。",
    "stale": "目录内发票已变化，需重新汇总（设为监控目录后会自动汇总）。",
    "never_built": "还没有汇总过，设为监控目录后会自动汇总。",
    "unknown": "无法确认是否最新：缺少上次汇总的文件记录或目录过大。",
    "missing_dir": "目录不存在或不可用。",
}


def _mtime_text(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def _read_processed(state_dir: Path) -> dict[str, dict] | None:
    """The monitor's last file signatures, read without the monitor's repair-on-read."""
    path = state_dir / PROCESSED_FILE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("files") if isinstance(payload.get("files"), dict) else payload
    return {monitor_path_key(key): item for key, item in raw.items() if isinstance(item, dict)}


def _scan_signatures(directory: Path) -> tuple[dict[str, tuple[int, int]], bool, int]:
    """Supported invoice files under ``directory`` -> (mtime_ns, size); bounded, no link following.

    Mirrors ``supported_invoice_files`` (recursive, PDF/OFD/XML, skips ``~$`` lock files).
    Returns (signatures, complete, scanned_entries).
    """
    signatures: dict[str, tuple[int, int]] = {}
    deadline = time.monotonic() + FRESHNESS_MAX_SECONDS
    scanned = 0
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > FRESHNESS_MAX_ENTRIES or time.monotonic() > deadline:
                        return signatures, False, scanned
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                            continue
                        if not entry.is_file() or entry.name.startswith("~$"):
                            continue
                        if Path(entry.name).suffix.lower() not in SUPPORTED_EXTS:
                            continue
                        stat = entry.stat()
                    except OSError:
                        return signatures, False, scanned
                    signatures[monitor_path_key(entry.path)] = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return signatures, False, scanned
    return signatures, True, scanned


def directory_freshness(directory: Path, profile: TargetProfile) -> dict:
    """Compare the folder with the signatures its last projection was built from."""
    result = {"state": "unknown", "added": 0, "updated": 0, "deleted": 0, "scanned_entries": 0, "complete": False}
    summary_exists = (Path(profile.workspace_dir) / "发票汇总.csv").exists()
    processed = _read_processed(Path(profile.state_dir))
    current, complete, scanned = _scan_signatures(directory)
    result.update(scanned_entries=scanned, complete=complete, source_file_count=len(current))
    if not summary_exists:
        result["state"] = "never_built"
        return result
    if processed is None:
        return result
    added = updated = 0
    for key, (mtime_ns, size) in current.items():
        old = processed.get(key)
        if old is None:
            added += 1
        elif int(old.get("mtime_ns") or old.get("mtime") or 0) != mtime_ns or int(old.get("size") or 0) != size:
            updated += 1
    # Deletions are only knowable from a complete listing.
    deleted = sum(1 for key in processed if key not in current) if complete else 0
    result.update(added=added, updated=updated, deleted=deleted)
    if added or updated or deleted:
        result["state"] = "stale"
    elif complete:
        result["state"] = "fresh"
    return result


class CompanyViewService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        db_path: Path,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        registry: CompanyRegistryService,
        active_invoices: Callable[[], InvoiceListService],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._db_path = db_path
        self._config = config
        self._active_profile = active_profile
        self._registry = registry
        self._active_invoices = active_invoices

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def _directory(self, company: dict, key: str) -> tuple[dict, TargetProfile]:
        subdir = next((item for item in company["subdirs"] if item["key"] == key), None)
        if subdir is None:
            raise CompanyRegistryError("COMPANY_DIRECTORY_NOT_FOUND", "未知的子目录类型。", status_code=404, field="key")
        # Same profile the folder would get as watch_dir, so an earlier monitoring run's
        # projection is found here. target_profile_for is pure: it creates nothing.
        return subdir, target_profile_for(self.config, Path(subdir["path"]))

    def _directory_view(self, subdir: dict, profile: TargetProfile, active_id: str, *, check_freshness: bool) -> dict:
        summary_csv = Path(profile.workspace_dir) / "发票汇总.csv"
        cost_csv = Path(subdir["path"]) / COST_DETAIL_CSV_NAME
        active = profile.id == active_id
        view = {
            **subdir,
            "target_id": profile.id,
            "active": active,
            "read_only": not active,
            "projection": {
                "summary_exists": summary_csv.exists(),
                "summary_updated_at": _mtime_text(summary_csv),
                "cost_detail_exists": cost_csv.exists(),
                "cost_detail_updated_at": _mtime_text(cost_csv),
            },
        }
        if subdir["status"] != "present":
            freshness = {"state": "missing_dir"}
        elif active:
            freshness = {"state": "monitored"}
        elif check_freshness:
            freshness = directory_freshness(Path(subdir["path"]), profile)
        else:
            freshness = {"state": "not_checked"}
        freshness["message"] = FRESHNESS_MESSAGES.get(freshness["state"], "")
        view["freshness"] = freshness
        return view

    def company_directories(self, company_id: str, *, check_freshness: bool = True) -> dict:
        payload = self._registry.get_company(company_id)
        company = payload["company"]
        active_id = self.active_profile.id
        directories = []
        for subdir in company["subdirs"]:
            _subdir, profile = self._directory(company, subdir["key"])
            directories.append(self._directory_view(subdir, profile, active_id, check_freshness=check_freshness))
        return {"ok": True, "revision": payload["revision"], "company": company, "directories": directories}

    def directory_invoices(self, company_id: str, key: str, filters: dict | None = None) -> dict:
        company = self._registry.get_company(company_id)["company"]
        subdir, profile = self._directory(company, key)
        filters = dict(filters or {})
        page = filters.pop("page", None)
        page_size = max(1, min(200, int(filters.pop("page_size", None) or 100)))
        payload, read_only = self._list_payload(profile, filters)
        items = payload["items"]
        count = len(items)
        if page is not None:
            last_page = max(1, (count + page_size - 1) // page_size)
            page = max(1, min(int(page), last_page))
            payload.update(page=page, page_size=page_size, items=items[(page - 1) * page_size:page * page_size])
        payload.update(
            company_id=company_id,
            directory_key=key,
            directory=self._directory_view(subdir, profile, self.active_profile.id, check_freshness=False),
            read_only=read_only,
        )
        return payload

    def _list_payload(self, profile: TargetProfile, filters: dict) -> tuple[dict, bool]:
        """Homepage-shaped rows of one folder's projection and whether they are read-only."""
        if profile.id == self.active_profile.id:
            # The active folder keeps every homepage action; hand over to the live service.
            return self._active_invoices().list_invoices(filters), False
        reader = InvoiceListService(
            # Private lock: this reader shares no cache or file with the active services.
            lock=threading.RLock(),
            repo=self.repo,
            db_path=self._db_path,
            active_profile=lambda: profile,
            cost_service=lambda: CostProjectionService(
                Path(profile.watch_dir), Path(profile.workspace_dir), profile.id,
                reference_markup_rate=self.config.reference_markup_rate,
                company_taxpayer=lambda: company_taxpayer_for(self.config, Path(profile.watch_dir)),
            ),
        )
        payload = reader.list_invoices(filters)
        for item in payload["items"]:
            item["detail_url"] = ""
            item["read_only"] = True
        payload["snapshot"]["source_label"] = "上次汇总（非监控目录，只读）"
        return payload, True

    def company_ledger(
        self, company_id: str, *, granularity: str = "month", start: str = "", end: str = "", check_freshness: bool = True
    ) -> dict:
        """进项 (成本发票) and 销项 (开具发票) of one company from their last projections."""
        payload = self._registry.get_company(company_id)
        company = payload["company"]
        active_id = self.active_profile.id
        sources = {}
        rows = {}
        for direction, key in (("input", "cost_invoice_dir"), ("output", "issued_invoice_dir")):
            subdir, profile = self._directory(company, key)
            sources[direction] = self._directory_view(subdir, profile, active_id, check_freshness=check_freshness)
            rows[direction] = self._list_payload(profile, {})[0]["items"] if subdir["status"] == "present" else []
        try:
            ledger = build_invoice_ledger(
                rows["input"], rows["output"], granularity=granularity, start=start, end=end,
                taxpayer_periods=company["taxpayer_periods"],
            )
        except ValueError as exc:
            raise CompanyRegistryError("COMPANY_LEDGER_INVALID", str(exc), status_code=422) from exc
        for direction, label in (("input", "进项（成本发票）"), ("output", "销项（开具发票）")):
            state = sources[direction]["freshness"]["state"]
            if state in {"stale", "never_built", "unknown", "missing_dir"}:
                ledger["warnings"].insert(0, {"code": f"source_{state}", "direction": direction,
                                              "message": f"{label}：{sources[direction]['freshness']['message']}"})
        return {"ok": True, "revision": payload["revision"], "company": company, "sources": sources, **ledger}
