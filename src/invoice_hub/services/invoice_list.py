"""Invoice list: summary CSV cache, manual overrides, filters/stats, consistency, detail, open.

Moved out of ``AppState`` (ENG-03) without behaviour changes; AppState keeps the public names
(and ``_clear_invoice_cache``, which background sync, rebuild, rename, delete and directory
switches call) and forwards here. The summary CSV is a rebuildable projection; ``mtime_ns +
size`` only keys this process's read cache, never the truth of a source invoice. Manual edits
write the override file and the projection under the TargetProfile's monitor sync lock, and
only clear the cache or emit events when that profile is still the active one.

The active profile is read on every call; list building holds AppState's own RLock so a
directory switch cannot mix two generations in one payload.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.extraction import BUSINESS_TYPES, INVOICE_TYPES, is_valid_money
from invoice_hub.extraction.classification import (
    CLASSIFICATION_STATUS_CONFLICT,
    CLASSIFICATION_STATUS_NEEDS_REVIEW,
    CLASSIFICATION_STATUS_OK,
)
from invoice_hub.monitoring.state import MonitorState, is_pid_alive
from invoice_hub.platform import open_local_path
from invoice_hub.projections.cost_analysis import invoice_cost_breakdown
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import SUMMARY_HEADERS, write_summary_xlsx
from invoice_hub.services.invoice_selection import file_format_from_source, invoice_number_from_filename
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_csv_rows, read_json_object, write_csv_rows
from invoice_hub.storage.read_views import ReadViews, file_signature
from invoice_hub.targets.paths import profile_identity as _profile_identity


class InvoiceListService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        db_path: Path,
        active_profile: Callable[[], TargetProfile],
        cost_service: Callable[[], CostProjectionService],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._db_path = db_path
        self._profile_provider = active_profile
        self.cost_service = cost_service
        self._invoice_cache_key: tuple[int, int] | None = None
        self._invoice_cache_rows: list[dict[str, str]] = []
        self._invoice_payload_key = None
        self._invoice_payload = None

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def invoice_summary_csv(self) -> Path:
        return Path(self.active_profile.workspace_dir) / "发票汇总.csv"

    def invoice_summary_xlsx(self) -> Path:
        return Path(self.active_profile.workspace_dir) / "发票汇总.xlsx"

    def _manual_overrides_path(self) -> Path:
        return Path(self.active_profile.state_dir) / "manual_overrides.json"

    def _clear_invoice_cache(self) -> None:
        self._invoice_cache_key = None
        self._invoice_cache_rows = []

    def _summary_rows(self) -> list[dict[str, str]]:
        path = self.invoice_summary_csv()
        if not path.exists():
            self._clear_invoice_cache()
            return []
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
        if key != self._invoice_cache_key:
            self._invoice_cache_rows = read_csv_rows(path)
            self._invoice_cache_key = key
        return [dict(row) for row in self._invoice_cache_rows]

    def _write_summary_rows(self, rows: list[dict[str, str]]) -> None:
        write_csv_rows(self.invoice_summary_csv(), SUMMARY_HEADERS, rows)
        write_summary_xlsx(self.invoice_summary_xlsx(), rows)
        self._clear_invoice_cache()

    def _manual_override_items(self) -> dict:
        payload = read_json_object(self._manual_overrides_path(), {"items": {}})
        items = payload.get("items")
        return items if isinstance(items, dict) else {}

    def _identity_for_row(self, row: dict[str, str], index: int) -> str:
        return (row.get("文件路径") or "").strip() or str(index)

    def _apply_manual_overrides(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        overrides = self._manual_override_items()
        if not overrides:
            return rows
        for index, row in enumerate(rows):
            override = overrides.get(self._identity_for_row(row, index)) or {}
            fields = override.get("fields") if isinstance(override, dict) else {}
            if isinstance(fields, dict):
                for key in ("销售方", "开票金额", "发票号码"):
                    if key in fields:
                        row[key] = str(fields.get(key) or "")
                row["手改状态"] = "已手改"
        return rows

    def _invoice_status(self, row: dict[str, str], duplicate: bool) -> str:
        if duplicate:
            return "重复发票"
        if str(row.get("类型识别状态") or "").strip() != CLASSIFICATION_STATUS_OK:
            return "待核对"
        required = (row.get("销售方"), row.get("发票号码"))
        return "已识别" if all(str(value or "").strip() for value in required) and is_valid_money(str(row.get("开票金额") or "")) else "待核对"

    def _filter_invoice_items(self, items: list[dict], filters: dict | None) -> list[dict]:
        filters = filters or {}
        keyword = str(filters.get("keyword") or "").strip().casefold()
        search_fields = {
            "invoice": ("seller", "invoice_number"),
            "filename": ("source_file",),
            "all": ("seller", "invoice_number", "source_file"),
        }[str(filters.get("search_scope") or "all")]
        file_ext = str(filters.get("file_ext") or "").strip().casefold()
        status = str(filters.get("status") or "").strip()
        invoice_type = str(filters.get("invoice_type") or "").strip()
        business_type = str(filters.get("business_type") or "").strip()
        classification_filter = str(filters.get("classification_status") or "").strip()
        date_from = str(filters.get("date_from") or "").strip()
        date_to = str(filters.get("date_to") or "").strip()

        def matches(item: dict) -> bool:
            # The homepage defaults to visible invoice fields; legacy API callers
            # retain filename matching. Match each field separately, never across boundaries.
            if keyword and not any(keyword in str(item.get(key) or "").casefold() for key in search_fields):
                return False
            if file_ext and not str(item.get("source_file") or "").casefold().endswith(file_ext):
                return False
            if status and item.get("status") != status:
                return False
            if invoice_type and item.get("invoice_type") != invoice_type:
                return False
            if business_type and item.get("business_type") != business_type:
                return False
            if classification_filter and item.get("classification_status") != classification_filter:
                return False
            invoice_date = str(item.get("invoice_date") or "")
            if date_from and invoice_date and invoice_date < date_from:
                return False
            if date_to and invoice_date and invoice_date > date_to:
                return False
            return True

        return [item for item in items if matches(item)]

    def _invoice_stats(self, items: list[dict]) -> dict:
        total_amount = 0.0
        for item in items:
            if not is_valid_money(str(item.get("amount") or "")):
                continue
            try:
                total_amount += float(str(item.get("amount") or "0").replace(",", ""))
            except ValueError:
                pass
        return {
            "total": len(items),
            "recognized": sum(1 for item in items if item.get("status") == "已识别"),
            "needs_review": sum(1 for item in items if item.get("status") == "待核对"),
            "duplicates": sum(1 for item in items if item.get("duplicate")),
            "total_amount": round(total_amount, 2),
        }

    def _consistency_group_key(self, item: dict) -> str:
        invoice_number = str(item.get("invoice_number") or "").strip()
        if invoice_number:
            return f"invoice:{invoice_number}"
        filename_number = invoice_number_from_filename(item)
        if filename_number:
            return f"filename:{filename_number}"
        return ""

    @staticmethod
    def _first_non_empty(items: list[dict], field: str) -> str:
        for item in items:
            value = str(item.get(field) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _invoice_number_from_pair_key(pair_key: str) -> str:
        return pair_key.split(":", 1)[1] if ":" in pair_key else pair_key

    @staticmethod
    def _invoice_type_from_row(value: str, file_format: str) -> str:
        text = str(value or "").strip()
        if file_format and text.casefold() == file_format.casefold():
            return ""
        return text if text in INVOICE_TYPES else ""

    def _build_consistency_groups(self, items: list[dict]) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for item in items:
            pair_key = self._consistency_group_key(item)
            if pair_key:
                grouped.setdefault(pair_key, []).append(dict(item))

        groups = []
        check_fields = (
            ("invoice_type", "发票大类"),
            ("business_type", "特定业务类型"),
            ("seller", "销售方"),
            ("buyer", "购买方"),
            ("amount", "开票金额"),
            ("tax_rate", "税率"),
            ("pretax_amount", "除税价"),
            ("tax_amount", "税金"),
            ("invoice_date", "开票时间"),
        )
        for pair_key, group_items in grouped.items():
            formats = sorted({str(item.get("file_type") or "").lower() for item in group_items if str(item.get("file_type") or "").strip()})
            if len(group_items) < 2 or len(formats) < 2:
                continue
            mismatches = []
            for field, label in check_fields:
                unique_values = []
                for item in group_items:
                    value = str(item.get(field) or "").strip()
                    if value and value not in unique_values:
                        unique_values.append(value)
                if len(unique_values) > 1:
                    mismatches.append({"field": label, "values": unique_values})
            groups.append(
                {
                    "pair_key": pair_key,
                    "invoice_number": self._first_non_empty(group_items, "invoice_number") or self._invoice_number_from_pair_key(pair_key),
                    "formats": formats,
                    "file_count": len(group_items),
                    "consistent": len(mismatches) == 0,
                    "mismatch_fields": mismatches,
                    "items": [
                        {
                            "invoice_key": item.get("invoice_key", ""),
                            "detail_url": item.get("detail_url", ""),
                            "file_name": item.get("file_name") or item.get("source_file") or "",
                            "file_type": item.get("file_type", ""),
                            "invoice_type": item.get("invoice_type", ""),
                            "business_type": item.get("business_type", ""),
                            "classification_status": item.get("classification_status", ""),
                            "classification_issue": item.get("classification_issue", ""),
                            "seller": item.get("seller", ""),
                            "buyer": item.get("buyer", ""),
                            "amount": item.get("amount", ""),
                            "tax_rate": item.get("tax_rate", ""),
                            "invoice_date": item.get("invoice_date", ""),
                            "invoice_number": item.get("invoice_number", ""),
                            "has_manual_override": item.get("has_manual_override", False),
                        }
                        for item in sorted(group_items, key=lambda value: (str(value.get("file_type") or ""), str(value.get("file_name") or "")))
                    ],
                }
            )
        groups.sort(key=lambda group: (group["consistent"], group["invoice_number"], group["pair_key"]))
        return groups

    def _find_consistency_group(self, items: list[dict], pair_key: str) -> dict | None:
        if not pair_key:
            return None
        for group in self._build_consistency_groups(items):
            if group["pair_key"] == pair_key:
                return group
        return None

    def consistency_report(self, only_mismatch: bool = False) -> dict:
        invoice_payload = self.list_invoices()
        groups = self._build_consistency_groups(invoice_payload["items"])
        if only_mismatch:
            groups = [group for group in groups if not group["consistent"]]
        inconsistent = sum(1 for group in groups if not group["consistent"])
        return {
            "ok": True,
            "groups": groups,
            "stats": {
                "total_groups": len(groups),
                "consistent_groups": len(groups) - inconsistent,
                "inconsistent_groups": inconsistent,
            },
            "snapshot": invoice_payload["snapshot"],
        }

    def list_invoices(self, filters: dict | None = None) -> dict:
        filters = filters or {}
        with self._lock:
            key = [self.active_profile.id, str(self.invoice_summary_csv()), file_signature(self.invoice_summary_csv()),
                   file_signature(self._manual_overrides_path())]
            if key != self._invoice_payload_key:
                self._invoice_payload = self._build_invoice_payload()
                self._invoice_payload_key = key
            payload = dict(self._invoice_payload)
            snapshot = dict(payload["snapshot"], revision=hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20], provisional=False)
            # Only the paged browsing surface may consume unfinished rows. Selection,
            # detail, print and export continue to use the finalized CSV identities.
            if "page" in filters and not self.invoice_summary_csv().exists():
                meta, rows = ReadViews(self.active_profile.workspace_dir).read("partial:invoices", page_size=None)
                if meta:
                    if meta.get("state") == "running" and not is_pid_alive(meta.get("pid")):
                        meta["state"] = "interrupted"
                    payload = self._build_invoice_payload(rows=rows)
                    snapshot.update(provisional=True, revision=meta["revision"], progress=meta, source_label="正在整理的临时结果")
            items = self._filter_invoice_items(payload["items"], filters)
            if filters.get("date_sort") in {"asc", "desc"}:
                def date_key(item):
                    match = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(item.get("invoice_date") or ""))
                    return tuple(map(int, match.groups())) if match else ()
                dated = [item for item in items if date_key(item)]
                undated = [item for item in items if not date_key(item)]
                items = sorted(dated, key=date_key, reverse=filters["date_sort"] == "desc") + undated
            count = len(items)
            payload.update(count=count, items=items, stats={"all": payload["stats"]["all"], "filtered": self._invoice_stats(items)}, snapshot=snapshot)
            if "page" in filters:
                page_size = max(1, min(200, int(filters.get("page_size") or 100)))
                page = max(1, min(int(filters["page"]), max(1, (count + page_size - 1) // page_size)))
                payload.update(page=page, page_size=page_size, items=items[(page - 1) * page_size:page * page_size])
            return payload

    def _build_invoice_payload(self, filters=None, rows=None) -> dict:
        rows = self._apply_manual_overrides(self._summary_rows() if rows is None else rows)
        items = []
        seen_numbers: dict[str, int] = {}
        for index, row in enumerate(rows):
            number = (row.get("发票号码") or "").strip()
            duplicate = bool(number and seen_numbers.get(number, 0) > 0)
            seen_numbers[number] = seen_numbers.get(number, 0) + 1
            status = self._invoice_status(row, duplicate)
            source_file = row.get("文件名", "")
            source_path = row.get("文件路径", "")
            file_format = file_format_from_source(source_file, source_path)
            invoice_type = self._invoice_type_from_row(row.get("发票类型", ""), file_format)
            business_type_value = str(row.get("特定业务类型") or "").strip()
            business_type = business_type_value if business_type_value in BUSINESS_TYPES else ""
            classification_value = str(row.get("类型识别状态") or "").strip()
            classification_status_value = (
                classification_value
                if classification_value
                in {
                    CLASSIFICATION_STATUS_OK,
                    CLASSIFICATION_STATUS_NEEDS_REVIEW,
                    CLASSIFICATION_STATUS_CONFLICT,
                }
                else CLASSIFICATION_STATUS_NEEDS_REVIEW
            )
            item = {
                "invoice_key": str(index),
                "source_file": source_file,
                "file_name": source_file,
                "source_path": source_path,
                "file_path": source_path,
                "file_type": file_format,
                "file_format": file_format,
                "invoice_type": invoice_type,
                "business_type": business_type,
                "classification_status": classification_status_value,
                "classification_issue": row.get("类型识别说明", ""),
                "invoice_number": number,
                "invoice_date": row.get("开票时间", ""),
                "seller": row.get("销售方", ""),
                "buyer": row.get("购买方", ""),
                "amount": row.get("开票金额", ""),
                "tax_rate": row.get("税率", ""),
                "pretax_amount": row.get("除税价", ""),
                "tax_amount": row.get("税金", ""),
                "duplicate": duplicate,
                "duplicate_label": "重复发票" if duplicate else "",
                "status": status,
                "detail_url": f"/invoices/{index}",
                "has_manual_override": row.get("手改状态") == "已手改",
            }
            items.append(item)
        filtered = self._filter_invoice_items(items, filters)
        return {
            "ok": True,
            "count": len(filtered),
            "items": filtered,
            "stats": {"all": self._invoice_stats(items), "filtered": self._invoice_stats(filtered)},
            "snapshot": {
                "source_path": str(self.invoice_summary_csv()),
                "source_label": "活动档案汇总",
                "source_exists": self.invoice_summary_csv().exists(),
                "target_id": self.active_profile.id,
                "from_cache": False,
            },
            "target_id": self.active_profile.id,
            "watch_dir": self.active_profile.watch_dir,
        }

    def invoice_detail(self, invoice_key: str) -> dict:
        items = self.list_invoices()["items"]
        try:
            item = dict(items[int(invoice_key)])
        except Exception:
            raise KeyError(invoice_key)
        pair_key = self._consistency_group_key(item)
        source_path = Path(str(item.get("file_path") or ""))
        try:
            source_stat = source_path.stat()
            source_exists = source_path.is_file()
            source_size = source_stat.st_size if source_exists else 0
            source_modified = source_stat.st_mtime if source_exists else None
        except OSError:
            source_exists = False
            source_size = 0
            source_modified = None
        editable = {
            "销售方": {"source_value": item.get("seller", ""), "manual_value": item.get("seller", "")},
            "开票金额": {"source_value": item.get("amount", ""), "manual_value": item.get("amount", "")},
            "发票号码": {"source_value": item.get("invoice_number", ""), "manual_value": item.get("invoice_number", "")},
        }
        item.update(
            {
                "source_exists": source_exists,
                "source_size_bytes": source_size,
                "source_modified_at": self._format_file_mtime(source_modified),
            }
        )
        cost_breakdown = invoice_cost_breakdown(
            read_csv_rows(self.cost_service().detail_csv),
            invoice_number=item.get("invoice_number", ""),
            source_path=item.get("file_path", ""),
            source_file=item.get("source_file", ""),
        )
        payload = {
            "ok": True,
            "item": item,
            "invoice": item,
            "editable_fields": editable,
            "consistency": self._find_consistency_group(items, pair_key),
            "cost_breakdown": cost_breakdown,
            "snapshot": self.list_invoices()["snapshot"],
        }
        payload["invoice"]["editable_fields"] = editable
        payload["invoice"]["cost_breakdown"] = cost_breakdown
        return payload

    @staticmethod
    def _format_file_mtime(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return datetime.fromtimestamp(float(value)).replace(microsecond=0).isoformat(sep=" ")

    def _rewrite_summary_with_overrides(self) -> None:
        rows = self._apply_manual_overrides(self._summary_rows())
        if rows:
            self._write_summary_rows(rows)

    def update_manual_fields(self, invoice_key: str, payload: dict | None) -> dict:
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            profile_identity = _profile_identity(profile)
        monitor_state = MonitorState(profile, self._db_path, sync_interval_seconds=60)
        with monitor_state.sync_write_lock():
            rows = read_csv_rows(monitor_state.summary_csv)
            try:
                index = int(invoice_key)
                row = rows[index]
            except Exception:
                raise KeyError(invoice_key)
            fields = dict((payload or {}).get("fields") or payload or {})
            allowed = {"销售方", "开票金额", "发票号码"}
            cleaned = {key: str(value or "").strip() for key, value in fields.items() if key in allowed}
            if not cleaned:
                return {"ok": True, "updated": False, "invoice_key": invoice_key}
            for key, value in cleaned.items():
                row[key] = value
            identity = self._identity_for_row(row, index)
            overrides = read_json_object(monitor_state.manual_overrides_file, {"items": {}})
            items = overrides.setdefault("items", {})
            items[identity] = {
                "invoice_key": invoice_key,
                "source_path": row.get("文件路径", ""),
                "fields": cleaned,
                "updated_at": utc_now_text(),
            }
            atomic_write_json(monitor_state.manual_overrides_file, overrides)
            write_csv_rows(monitor_state.summary_csv, SUMMARY_HEADERS, rows)
            write_summary_xlsx(monitor_state.summary_xlsx, rows)
        with self._lock:
            if profile_identity == _profile_identity(self.active_profile):
                self._clear_invoice_cache()
                self.append_event(
                    "invoice.manual_fields_updated",
                    {"invoice_key": invoice_key, "fields": sorted(cleaned), "target_id": profile.id},
                )
        return {"ok": True, "updated": True, "invoice_key": invoice_key, "fields": cleaned}

    def open_invoice_file(self, invoice_key: str) -> dict:
        item = self.invoice_detail(invoice_key)["item"]
        path = Path(str(item.get("file_path") or ""))
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件不存在: {path}"}
        open_local_path(path)
        self.append_event("invoice.local_file_opened", {"invoice_key": invoice_key, "file_path": str(path)})
        return {"ok": True, "opened": True, "invoice_key": invoice_key, "file_path": str(path), "file_name": path.name}

    def open_invoice_location(self, invoice_key: str) -> dict:
        item = self.invoice_detail(invoice_key)["item"]
        path = Path(str(item.get("file_path") or ""))
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件不存在: {path}"}
        folder = path.parent
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件夹不存在: {folder}"}
        open_local_path(folder)
        self.append_event("invoice.local_file_location_opened", {"invoice_key": invoice_key, "file_path": str(path), "folder_path": str(folder)})
        return {"ok": True, "opened": True, "invoice_key": invoice_key, "file_path": str(path), "folder_path": str(folder), "file_name": path.name}
