"""Homepage invoice selection: identity rules, revalidation and the selection summary.

Split out of ``AppState`` (ENG-03); routes call it as ``state.selection`` (ENG-08). ``invoice_key`` is a row
position that is reused after a rebuild, so every selection carries ``source_path`` and is
rechecked against the *current* invoice list before any use; a mismatch is a stale
selection, never a silent re-target. The pure helpers below define one invoice family
(invoice number, then the 20-digit number in the file name, then the source path), shared
by totals, documents, preview and print.

The invoice list itself (caching, consistency, rebuild) belongs to ``InvoiceListService`` and
arrives as a callback, as do the active profile and the cost detail path; all are read per call.
The summary holds AppState's own RLock so validation and the result share one directory
generation.
"""

from __future__ import annotations

import re
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.extraction import is_valid_money
from invoice_hub.projections.cost_analysis import selection_cost_breakdown
from invoice_hub.services.errors import StaleInvoiceSelectionError
from invoice_hub.storage import read_csv_rows


def invoice_number_from_filename(item: dict) -> str:
    file_name = str(item.get("file_name") or item.get("source_file") or "").strip()
    matched = re.search(r"(?<!\d)(\d{20})(?!\d)", file_name)
    return matched.group(1) if matched else ""


def selection_source_identity(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/").rstrip("/")
    try:
        path = Path(text)
        if path.is_absolute():
            normalized = str(path.resolve(strict=False)).replace("\\", "/").rstrip("/")
    except (OSError, RuntimeError):
        pass
    return normalized.casefold()


def selection_family_key(item: dict) -> str:
    invoice_number = str(item.get("invoice_number") or "").strip()
    if invoice_number:
        return f"number:{invoice_number}"
    filename_number = invoice_number_from_filename(item)
    if filename_number:
        return f"number:{filename_number}"
    source_identity = selection_source_identity(item.get("source_path") or item.get("file_path"))
    if not source_identity:
        source_identity = selection_source_identity(item.get("source_file") or item.get("file_name"))
    return f"source:{source_identity}"


def selection_money_value(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if not is_valid_money(text):
        return None
    normalized = text.replace(",", "").replace("¥", "").replace("￥", "")
    matched = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not matched:
        return None
    try:
        return Decimal(matched.group(0))
    except InvalidOperation:
        return None


def file_format_from_source(source_file: str, source_path: str = "") -> str:
    for raw in (source_file, source_path):
        suffix = Path(str(raw or "").strip()).suffix.lower().lstrip(".")
        if suffix in {"pdf", "ofd", "xml"}:
            return suffix
    return ""


class InvoiceSelectionService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        active_profile: Callable[[], TargetProfile],
        list_invoices: Callable[[], dict],
        cost_detail_csv: Callable[[], Path],
    ) -> None:
        self._lock = lock
        self._active_profile = active_profile
        self._list_invoices = list_invoices
        self._cost_detail_csv = cost_detail_csv

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def validated_invoice_selection(self, payload: dict, *, max_items: int, operation: str) -> tuple[dict, list[dict]]:
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        if payload.get("target_id") is not None and payload["target_id"] != self.active_profile.id:
            raise StaleInvoiceSelectionError("活动目录已切换，请刷新后重新勾选。")
        requested_items = payload.get("items")
        if not isinstance(requested_items, list) or not requested_items:
            raise ValueError("请至少勾选一张发票。")
        if len(requested_items) > max_items:
            raise ValueError(f"单次最多{operation} {max_items} 条发票记录。")

        current_payload = self._list_invoices()
        current_by_key = {str(item.get("invoice_key") or ""): item for item in current_payload["items"]}
        selected_items = []
        seen_keys: set[str] = set()
        for requested in requested_items:
            if not isinstance(requested, dict):
                raise ValueError("每条勾选记录必须包含 invoice_key 和 source_path。")
            raw_key = requested.get("invoice_key")
            source_path = requested.get("source_path")
            if isinstance(raw_key, bool) or not isinstance(raw_key, (str, int)):
                raise ValueError("invoice_key 格式不正确。")
            if not isinstance(source_path, str) or not source_path.strip():
                raise ValueError("source_path 不能为空。")
            invoice_key = str(raw_key).strip()
            if not invoice_key:
                raise ValueError("invoice_key 不能为空。")
            if invoice_key in seen_keys:
                raise ValueError("同一发票记录不能重复提交。")
            seen_keys.add(invoice_key)

            current = current_by_key.get(invoice_key)
            current_path = str((current or {}).get("source_path") or (current or {}).get("file_path") or "")
            if current is None or selection_source_identity(current_path) != selection_source_identity(source_path):
                raise StaleInvoiceSelectionError("勾选内容已过期，请刷新发票列表后重新勾选。")
            selected_items.append(current)
        return current_payload, selected_items

    def _selection_metric_total(self, families: list[list[dict]], field: str) -> dict:
        total = Decimal("0")
        valid_invoice_count = 0
        missing_invoice_count = 0
        conflict_invoice_count = 0
        for family_items in families:
            values = {
                value
                for item in family_items
                if (value := selection_money_value(item.get(field))) is not None
            }
            if not values:
                missing_invoice_count += 1
            elif len(values) > 1:
                conflict_invoice_count += 1
            else:
                total += next(iter(values))
                valid_invoice_count += 1
        return {
            "value": float(total.quantize(Decimal("0.01"))),
            "valid_invoice_count": valid_invoice_count,
            "missing_invoice_count": missing_invoice_count,
            "conflict_invoice_count": conflict_invoice_count,
        }

    def _selection_cost_family(self, family_key: str, items: list[dict]) -> dict:
        extracted_numbers = []
        for item in items:
            number = str(item.get("invoice_number") or "").strip()
            if number and number not in extracted_numbers:
                extracted_numbers.append(number)
        invoice_numbers = extracted_numbers
        if not invoice_numbers:
            invoice_numbers = []
            for item in items:
                number = invoice_number_from_filename(item)
                if number and number not in invoice_numbers:
                    invoice_numbers.append(number)
        return {
            "family_key": family_key,
            "source_invoices": [{"invoice_key": str(item["invoice_key"]),
                "source_path": str(item.get("source_path") or item.get("file_path") or ""),
                "file_name": str(item.get("source_file") or item.get("file_name") or ""),
                "invoice_number": str(item.get("invoice_number") or ""),
                "target_id": self.active_profile.id} for item in items],
            "invoice_numbers": invoice_numbers,
            "source_paths": [str(item.get("source_path") or item.get("file_path") or "") for item in items],
            "source_files": [str(item.get("source_file") or item.get("file_name") or "") for item in items],
        }

    def invoice_selection_summary(self, payload: dict) -> dict:
        # Keep captured target, source validation and the published result in one directory generation.
        with self._lock:
            current_payload, selected_items = self.validated_invoice_selection(
                payload, max_items=1000, operation="汇总"
            )

            grouped: dict[str, list[dict]] = {}
            for item in selected_items:
                family_key = selection_family_key(item)
                grouped.setdefault(family_key, []).append(item)
            families = list(grouped.values())
            cost_families = [self._selection_cost_family(key, items) for key, items in grouped.items()]
            cost_rows = read_csv_rows(self._cost_detail_csv())

            return {
                "ok": True,
                "selection": {
                    "record_count": len(selected_items),
                    "invoice_count": len(families),
                    "collapsed_record_count": len(selected_items) - len(families),
                },
                "totals": {
                    "pretax_amount": self._selection_metric_total(families, "pretax_amount"),
                    "tax_amount": self._selection_metric_total(families, "tax_amount"),
                    "total_with_tax": self._selection_metric_total(families, "amount"),
                },
                "cost_breakdown": selection_cost_breakdown(cost_rows, cost_families),
                "snapshot": current_payload["snapshot"],
            }
