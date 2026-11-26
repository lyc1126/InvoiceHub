"""Invoice list: summary CSV cache, manual overrides, filters/stats, consistency, detail, open.

Split out of ``AppState`` (ENG-03); routes call it as ``state.invoices`` (ENG-08), and background
sync, rebuild, rename, delete and directory switches call ``clear_invoice_cache``. The summary CSV is a rebuildable projection; ``mtime_ns +
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
from decimal import Decimal, InvalidOperation
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
from invoice_hub.services.invoice_selection import (
    file_format_from_source, invoice_number_from_filename, selection_family_key, selection_money_value,
)
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_csv_rows, read_json_object, write_csv_rows
from invoice_hub.storage import generations
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
        return generations.resolve(Path(self.active_profile.workspace_dir), Path(self.active_profile.watch_dir), "发票汇总.csv")

    def invoice_summary_xlsx(self) -> Path:
        return generations.resolve(Path(self.active_profile.workspace_dir), Path(self.active_profile.watch_dir), "发票汇总.xlsx")

    def manual_overrides_path(self) -> Path:
        return Path(self.active_profile.state_dir) / "manual_overrides.json"

    def clear_invoice_cache(self) -> None:
        self._invoice_cache_key = None
        self._invoice_cache_rows = []

    def _summary_rows(self, path=None) -> list[dict[str, str]]:
        path = path or self.invoice_summary_csv()
        if not path.exists():
            self.clear_invoice_cache()
            return []
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
        if key != self._invoice_cache_key:
            self._invoice_cache_rows = read_csv_rows(path)
            self._invoice_cache_key = key
        return [dict(row) for row in self._invoice_cache_rows]

    def _write_summary_rows(self, rows: list[dict[str, str]]) -> None:
        workspace, source = Path(self.active_profile.workspace_dir), Path(self.active_profile.watch_dir)
        write_csv_rows(workspace / "发票汇总.csv", SUMMARY_HEADERS, rows)
        write_summary_xlsx(workspace / "发票汇总.xlsx", rows)
        generations.publish_exports(workspace, source, generations.SUMMARY)
        self.clear_invoice_cache()

    def _manual_override_items(self) -> dict:
        payload = read_json_object(self.manual_overrides_path(), {"items": {}})
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

    @staticmethod
    def _normalize_date_ymd(value: object) -> str:
        match = re.match(r"^\s*(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", str(value or ""))
        if not match:
            return ""
        year, month, day = (int(part) for part in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return ""
        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _parse_filter_decimal(raw: object, label: str) -> Decimal | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{label} 必须是有效数字。") from exc
        if not value.is_finite():
            raise ValueError(f"{label} 必须是有限数字。")
        return value

    @staticmethod
    def _normalize_tax_rate_label(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.endswith("%"):
            inner = text[:-1].strip()
            try:
                num = Decimal(inner)
                if num.is_finite():
                    normalized = format(num.normalize(), "f")
                    if "." in normalized:
                        normalized = normalized.rstrip("0").rstrip(".")
                    return f"{normalized}%"
            except InvalidOperation:
                return text
        try:
            num = Decimal(text)
            if num.is_finite() and Decimal("0") <= num <= Decimal("1"):
                pct = (num * Decimal("100")).normalize()
                normalized = format(pct, "f")
                if "." in normalized:
                    normalized = normalized.rstrip("0").rstrip(".")
                return f"{normalized}%"
        except InvalidOperation:
            pass
        return text

    @classmethod
    def collect_filter_options(cls, items: list[dict]) -> dict:
        projects: set[str] = set()
        tax_rates: set[str] = set()
        invoice_types: set[str] = set()
        business_types: set[str] = set()
        has_unassigned_project = False
        has_missing_tax_rate = False
        has_duplicates = False
        for item in items:
            proj = str(item.get("project") or "").strip()
            if proj:
                projects.add(proj)
            else:
                has_unassigned_project = True
            rate = cls._normalize_tax_rate_label(item.get("tax_rate"))
            if rate:
                tax_rates.add(rate)
            else:
                has_missing_tax_rate = True
            itype = str(item.get("invoice_type") or "").strip()
            if itype:
                invoice_types.add(itype)
            btype = str(item.get("business_type") or "").strip()
            if btype:
                business_types.add(btype)
            if item.get("duplicate") or item.get("status") == "重复发票":
                has_duplicates = True

        def _rate_sort_key(rate_text: str) -> tuple[int, Decimal, str]:
            if rate_text.endswith("%"):
                try:
                    return (0, Decimal(rate_text[:-1]), rate_text)
                except InvalidOperation:
                    pass
            return (1, Decimal("0"), rate_text)

        return {
            "projects": sorted(projects, key=lambda v: v.casefold()),
            "tax_rates": sorted(tax_rates, key=_rate_sort_key),
            "invoice_types": sorted(invoice_types),
            "business_types": sorted(business_types),
            "has_unassigned_project": has_unassigned_project,
            "has_missing_tax_rate": has_missing_tax_rate,
            "has_duplicates": has_duplicates,
        }

    @classmethod
    def filter_invoice_items(cls, items: list[dict], filters: dict | None) -> list[dict]:
        filters = filters or {}
        keyword = str(filters.get("keyword") or "").strip().casefold()
        scope = str(filters.get("search_scope") or "all")
        search_field_map = {
            "invoice": ("seller", "invoice_number"),
            "filename": ("source_file",),
            "all": ("seller", "invoice_number", "source_file"),
            "buyer": ("buyer", "invoice_number"),
            "party": ("seller", "buyer", "invoice_number"),
            "workspace": (
                "seller",
                "buyer",
                "invoice_number",
                "source_file",
                "project",
                "amount",
                "tax_rate",
                "invoice_type",
                "business_type",
                "invoice_date",
            ),
        }
        if scope not in search_field_map:
            raise ValueError(f"不支持的搜索范围：{scope}")
        search_fields = search_field_map[scope]
        # Legacy scopes keep single-substring semantics for classic API compatibility;
        # new workspace/party/buyer scopes support whitespace-separated multi-token AND matching.
        multi_token = scope in {"workspace", "party", "buyer"}
        tokens = [token for token in keyword.split() if token] if (keyword and multi_token) else ([keyword] if keyword else [])
        file_ext = str(filters.get("file_ext") or "").strip().casefold()
        status = str(filters.get("status") or "").strip()
        invoice_type = str(filters.get("invoice_type") or "").strip()
        business_type = str(filters.get("business_type") or "").strip()
        classification_filter = str(filters.get("classification_status") or "").strip()
        raw_date_from = str(filters.get("date_from") or "").strip()
        raw_date_to = str(filters.get("date_to") or "").strip()
        date_from = cls._normalize_date_ymd(raw_date_from) or raw_date_from
        date_to = cls._normalize_date_ymd(raw_date_to) or raw_date_to
        amount_min = cls._parse_filter_decimal(filters.get("amount_min"), "最小金额")
        amount_max = cls._parse_filter_decimal(filters.get("amount_max"), "最大金额")
        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            raise ValueError("最小金额不能大于最大金额。")
        tax_rate_filter = str(filters.get("tax_rate") or "").strip()
        tax_rate_target = "" if tax_rate_filter in {"", "__missing__"} else cls._normalize_tax_rate_label(tax_rate_filter).casefold()
        project_filter = str(filters.get("project") or "").strip()

        def matches(item: dict) -> bool:
            # Match each field separately, never across field boundaries.
            if tokens:
                field_values = [str(item.get(key) or "").casefold() for key in search_fields]
                if scope == "workspace":
                    norm_rate = cls._normalize_tax_rate_label(item.get("tax_rate")).casefold()
                    if norm_rate:
                        field_values.append(norm_rate)
                for token in tokens:
                    if not any(token in value for value in field_values):
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
            if date_from or date_to:
                norm_date = cls._normalize_date_ymd(item.get("invoice_date"))
                if not norm_date:
                    return False
                if date_from and norm_date < date_from:
                    return False
                if date_to and norm_date > date_to:
                    return False
            if amount_min is not None or amount_max is not None:
                amount_value = selection_money_value(item.get("amount"))
                if amount_value is None:
                    return False
                if amount_min is not None and amount_value < amount_min:
                    return False
                if amount_max is not None and amount_value > amount_max:
                    return False
            if tax_rate_filter:
                norm_rate = cls._normalize_tax_rate_label(item.get("tax_rate")).casefold()
                if tax_rate_filter == "__missing__":
                    if norm_rate:
                        return False
                elif norm_rate != tax_rate_target:
                    return False
            if project_filter:
                proj = str(item.get("project") or "").strip()
                if project_filter == "__unassigned__":
                    if proj:
                        return False
                elif proj != project_filter:
                    return False
            return True

        return [item for item in items if matches(item)]

    def _filter_invoice_items(self, items: list[dict], filters: dict | None) -> list[dict]:
        return self.filter_invoice_items(items, filters)

    @classmethod
    def sort_invoice_items(
        cls,
        items: list[dict],
        *,
        sort_by: str = "",
        sort_dir: str = "",
        date_sort: str = "",
    ) -> list[dict]:
        active_by = str(sort_by or "").strip()
        active_dir = str(sort_dir or "").strip()
        if not active_by and date_sort in {"asc", "desc"}:
            active_by = "invoice_date"
            active_dir = date_sort
        if not active_by:
            return items
        if active_dir not in {"asc", "desc"}:
            active_dir = "desc" if active_by in {"invoice_date", "amount"} else "asc"
        reverse = active_dir == "desc"

        if active_by == "invoice_date":
            def _date_key(item: dict) -> tuple[int, int, int] | None:
                norm = cls._normalize_date_ymd(item.get("invoice_date"))
                if not norm:
                    return None
                return (int(norm[0:4]), int(norm[5:7]), int(norm[8:10]))

            present = [item for item in items if _date_key(item) is not None]
            missing = [item for item in items if _date_key(item) is None]
            return sorted(present, key=_date_key, reverse=reverse) + missing

        if active_by == "amount":
            present = [item for item in items if selection_money_value(item.get("amount")) is not None]
            missing = [item for item in items if selection_money_value(item.get("amount")) is None]
            return sorted(present, key=lambda item: selection_money_value(item.get("amount")), reverse=reverse) + missing

        if active_by in {"seller", "buyer", "source_file"}:
            present = [item for item in items if str(item.get(active_by) or "").strip()]
            missing = [item for item in items if not str(item.get(active_by) or "").strip()]
            return sorted(present, key=lambda item: str(item.get(active_by) or "").strip().casefold(), reverse=reverse) + missing

        return items

    @staticmethod
    def _invoice_stats(items: list[dict]) -> dict:
        # The directory view calls this again after tags, before paging. Match selection totals:
        # one invoice family contributes only when its legal face amounts agree across formats.
        families: dict[str, set[Decimal]] = {}
        for item in items:
            values = families.setdefault(selection_family_key(item), set())
            if (value := selection_money_value(item.get("amount"))) is not None:
                values.add(value)
        valid = [next(iter(values)) for values in families.values() if len(values) == 1]
        return {
            "total": len(items),
            "recognized": sum(1 for item in items if item.get("status") == "已识别"),
            "needs_review": sum(1 for item in items if item.get("status") == "待核对"),
            "duplicates": sum(1 for item in items if item.get("duplicate")),
            "total_amount": format(sum(valid, Decimal("0")).quantize(Decimal("0.01")), ".2f"),
            "total_amount_valid_count": len(valid),
            "total_amount_missing_count": sum(not values for values in families.values()),
            "total_amount_conflict_count": sum(len(values) > 1 for values in families.values()),
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
            path = self.invoice_summary_csv()
            key = [self.active_profile.id, str(path), file_signature(path),
                   file_signature(self.manual_overrides_path())]
            if key != self._invoice_payload_key:
                self._invoice_payload = self._build_invoice_payload(rows=self._summary_rows(path), source_path=path)
                self._invoice_payload_key = key
            payload = dict(self._invoice_payload)
            snapshot = dict(payload["snapshot"], revision=hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20], provisional=False)
            # Only the paged browsing surface may consume unfinished rows. Selection,
            # detail, print and export continue to use the finalized CSV identities.
            if "page" in filters and not path.exists():
                meta, rows = ReadViews(self.active_profile.workspace_dir).read("partial:invoices", page_size=None)
                if meta:
                    if meta.get("state") == "running" and not is_pid_alive(meta.get("pid")):
                        meta["state"] = "interrupted"
                    payload = self._build_invoice_payload(rows=rows)
                    snapshot.update(provisional=True, revision=meta["revision"], progress=meta, source_label="正在整理的临时结果")
            items = self._filter_invoice_items(payload["items"], filters)
            items = self.sort_invoice_items(
                items,
                sort_by=str(filters.get("sort_by") or ""),
                sort_dir=str(filters.get("sort_dir") or ""),
                date_sort=str(filters.get("date_sort") or ""),
            )
            count = len(items)
            payload.update(count=count, items=items, stats={"all": payload["stats"]["all"], "filtered": self._invoice_stats(items)}, snapshot=snapshot)
            if "page" in filters:
                page_size = max(1, min(200, int(filters.get("page_size") or 100)))
                page = max(1, min(int(filters["page"]), max(1, (count + page_size - 1) // page_size)))
                payload.update(page=page, page_size=page_size, items=items[(page - 1) * page_size:page * page_size])
            return payload

    def _build_invoice_payload(self, filters=None, rows=None, source_path=None) -> dict:
        summary_path = Path(source_path or self.invoice_summary_csv())
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
                "source_path": str(summary_path),
                "source_label": "活动档案汇总",
                "source_exists": summary_path.exists(),
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
            read_csv_rows(self.cost_service().read_detail_path()),
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
            rows = read_csv_rows(generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), "发票汇总.csv"))
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
            generations.publish_exports(Path(profile.workspace_dir), Path(profile.watch_dir), generations.SUMMARY)
        with self._lock:
            if profile_identity == _profile_identity(self.active_profile):
                self.clear_invoice_cache()
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
