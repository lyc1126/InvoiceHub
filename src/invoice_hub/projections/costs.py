from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from invoice_hub.storage.read_views import ReadViews, ProgressiveRows, file_signature
from typing import Any, Callable

from invoice_hub.domain import CostAnalysisSnapshot, CostSyncStatus
from invoice_hub.domain.models import utc_now_text
from invoice_hub.projections.cost_analysis import (
    CHECK_HEADERS,
    COST_DETAIL_CSV_NAME,
    COST_REFERENCE_STATUS_NAME,
    COST_SUMMARY_XLSX_NAME,
    DEFAULT_REFERENCE_MARKUP_RATE,
    DETAIL_HEADERS,
    INVOICE_REFERENCE_HEADERS,
    PROJECT_SPEC_SUMMARY_HEADERS,
    ReferenceTaxProfile,
    average_unit_price,
    detail_rows_with_tax_average,
    build_cost_analysis_outputs,
    normalize_reference_markup_percent,
    normalize_reference_markup_rate,
    project_spec_summary,
    reference_output_average_unit_price_with_tax,
    reference_markup_display,
    reference_markup_multiplier,
    reference_markup_percent_text,
    average_unit_price_with_tax,
    purchase_reference_average_unit_price_with_tax,
    STATUS_PRESERVED_KEYS,
    canonical_outbound_items,
    canonical_reference_rows,
    input_tax_index,
    item_catalog_from_status,
    item_catalog_overview,
    merged_status_item,
    parse_item_catalog,
    parse_reference_exclusions,
    reference_exclusions_from_status,
    reference_invoice_id,
    _tax_rate_from_percent,
    outbound_overview,
    outbound_reference_fields,
    parse_reference_tax_profile,
    reference_cost_basis,
    reference_cost_basis_text,
    reference_tax_profile_from_status,
    effective_tax_profile,
    TAXPAYER_LABELS,
    _write_workbook,
)
from invoice_hub.projections.cost_outbound import OUTBOUND_SUMMARY_NAME, _empty_summary as _empty_outbound_summary, load_outbound_summary, read_outbound_summary
from invoice_hub.storage.files import atomic_write_json, read_csv_rows, read_json_object, write_csv_rows

COST_SOURCE_EXTS = {".pdf", ".ofd", ".xml"}


def _decimal(value: object) -> Decimal:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _user_quantity(value: object) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return Decimal("0")
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", text):
        raise ValueError(f"已开数量不是有效数字: {value}")
    try:
        quantity = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"已开数量不是有效数字: {value}") from exc
    if not quantity.is_finite():
        raise ValueError(f"已开数量不是有效数字: {value}")
    return quantity


def _decimal_text(value: Decimal, places: str = "0.001") -> str:
    rounded = value.quantize(Decimal(places))
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _float_number(value: Decimal, places: str = "0.01") -> float:
    return float(value.quantize(Decimal(places)))


def _reference_key_values(*values: object) -> list[str]:
    return [re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ").strip()).strip() for value in values]


def _legacy_plain_reference_key(*values: object) -> str:
    return "|".join(str(value or "").strip() for value in values)


def _reference_key_from_values(*values: object) -> str:
    raw = "\x1f".join(_reference_key_values(*values))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _reference_key(row: dict[str, Any]) -> str:
    return _reference_key_from_values(
        row.get("发票代码(**内文字)", ""),
        row.get("内部项目名称", ""),
        row.get("规格型号", ""),
        row.get("单位", ""),
    )


def _reference_aliases(row: dict[str, Any]) -> list[str]:
    values = [
        row.get("发票代码(**内文字)", ""),
        row.get("内部项目名称", ""),
        row.get("规格型号", ""),
        row.get("单位", ""),
    ]
    aliases = [
        _reference_key_from_values(*values),
        _legacy_plain_reference_key(*values),
        "|".join(_reference_key_values(*values)),
    ]
    result = []
    for alias in aliases:
        if alias and alias not in result:
            result.append(alias)
    return result


def _normalize_status_item(raw_key: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized_key = str(normalized.get("reference_key") or normalized.get("key") or raw_key or "").strip()
    if normalized_key:
        normalized.setdefault("reference_key", normalized_key)
    field_aliases = {
        "locked_reference_amount": "invoiced_reference_amount",
        "locked_reference_tax_amount": "invoiced_reference_tax",
        "locked_reference_total_with_tax": "invoiced_reference_total_with_tax",
    }
    for old_field, new_field in field_aliases.items():
        if str(normalized.get(new_field) or "").strip() == "" and str(normalized.get(old_field) or "").strip() != "":
            normalized[new_field] = normalized[old_field]
    if str(normalized.get("reference_markup_rate") or "").strip() == "" and str(normalized.get("markup_rate") or "").strip() != "":
        normalized["reference_markup_rate"] = normalized["markup_rate"]
    return normalized


def _read_reference_status(path: Path) -> dict[str, dict]:
    payload = _read_reference_status_payload(path)
    items = payload.get("items", payload)
    if not isinstance(items, dict):
        return {}
    normalized: dict[str, dict] = {}
    for key, item in items.items():
        if not isinstance(item, dict):
            continue
        raw_key = str(key or "").strip()
        normalized_key = str(item.get("reference_key") or item.get("key") or raw_key).strip()
        if not normalized_key:
            continue
        normalized[normalized_key] = _normalize_status_item(normalized_key, item)
    return normalized


def _read_reference_status_payload(path: Path) -> dict:
    payload = read_json_object(path, {})
    return payload if isinstance(payload, dict) else {}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "locked", "已锁定", "锁定"}


def _has_text(value: object) -> bool:
    return str(value or "").strip() != ""


def _row_markup_meta(status: dict[str, Any], fallback_rate: object, fallback_locked: bool = False) -> dict[str, Any]:
    rate = normalize_reference_markup_rate(fallback_rate)
    if _has_text(status.get("reference_markup_rate_percent")):
        rate = normalize_reference_markup_percent(status.get("reference_markup_rate_percent"))
    elif _has_text(status.get("reference_markup_rate")):
        rate = normalize_reference_markup_rate(status.get("reference_markup_rate"), fallback_rate)
    elif _has_text(status.get("markup_rate")):
        rate = normalize_reference_markup_rate(status.get("markup_rate"), fallback_rate)
    locked = _truthy(status.get("reference_markup_locked", fallback_locked))
    return {
        "rate": rate,
        "display": reference_markup_display(rate),
        "percent": reference_markup_percent_text(rate),
        "locked": locked,
    }


def _write_reference_status(
    path: Path,
    items: dict[str, dict],
    reference_markup_rate: object = DEFAULT_REFERENCE_MARKUP_RATE,
    reference_markup_locked: bool = False,
    tax_profile: ReferenceTaxProfile | None = None,
    item_catalog: dict[str, dict] | None = None,
    reference_exclusions: dict[str, dict] | None = None,
) -> None:
    markup_rate = normalize_reference_markup_rate(reference_markup_rate)
    normalized = {key: dict(value) for key, value in sorted(items.items()) if key and isinstance(value, dict)}
    payload = {
        "version": 1,
        "updated_at": utc_now_text(),
        "reference_markup_rate": _decimal_text(markup_rate, "0.000001"),
        "reference_markup_rate_percent": reference_markup_percent_text(markup_rate),
        "reference_markup_locked": bool(reference_markup_locked),
        "items": normalized,
    }
    # Saving row status without touching company settings keeps whatever the company saved.
    existing = _read_reference_status_payload(path)
    for preserved in STATUS_PRESERVED_KEYS:
        if isinstance(existing.get(preserved), dict):
            payload[preserved] = existing[preserved]
    if tax_profile is not None and tax_profile.configured:
        payload["tax_profile"] = tax_profile.status_payload()
    if item_catalog is not None:
        if item_catalog:
            payload["item_catalog"] = {"version": 1, "items": item_catalog}
        else:
            payload.pop("item_catalog", None)
    if reference_exclusions is not None:
        if reference_exclusions.get("keys") or reference_exclusions.get("invoices"):
            payload["reference_exclusions"] = {"version": 1, **reference_exclusions}
        else:
            payload.pop("reference_exclusions", None)
    atomic_write_json(path, payload)


def _valid_invoice_number(value: object) -> str:
    match = re.search(r"(?<!\d)(\d{8,20})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def _cost_source_groups_from_summary(summary_csv: Path) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for row in read_csv_rows(summary_csv):
        source = row.get("文件路径") or row.get("source_path") or row.get("源文件") or ""
        if Path(str(source)).suffix.lower() not in COST_SOURCE_EXTS:
            continue
        invoice_number = _valid_invoice_number(row.get("发票号码") or row.get("invoice_number"))
        group_key = f"invoice:{invoice_number}" if invoice_number else f"source:{Path(str(source))}"
        keys = groups.setdefault(group_key, set())
        keys.update(_source_keys(str(source)))
        if invoice_number:
            keys.add(f"invoice:{invoice_number}")
    return groups


def _source_keys(value: str) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    path = Path(text)
    keys = {str(path)}
    if path.name:
        keys.add(path.name.casefold())
    return keys


def _sources_from_rows(rows: list[dict]) -> set[str]:
    sources = set()
    for row in rows:
        source = row.get("源文件") or row.get("source_file") or ""
        if source:
            sources.add(str(Path(str(source))))
    return sources


def _keys_from_rows(rows: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        source = row.get("源文件") or row.get("source_file") or row.get("源文件名") or ""
        keys.update(_source_keys(str(source)))
        invoice_number = _valid_invoice_number(row.get("发票号码") or row.get("invoice_number"))
        if invoice_number:
            keys.add(f"invoice:{invoice_number}")
    return keys


def _reference_sources(rows: list[dict]) -> list[dict]:
    """Invoices behind one 开票参考 row, for the 来源 dialog (one line per invoice, not per detail line)."""
    sources: dict[str, dict] = {}
    for row in rows:
        invoice_id = reference_invoice_id(row)
        item = sources.setdefault(invoice_id, {
            "id": invoice_id,
            "invoice_number": str(row.get("发票号码") or ""),
            "source": Path(str(row.get("源文件") or "")).name,
            "seller": str(row.get("销售方") or ""),
            "invoice_date": str(row.get("开票日期") or ""),
            "quantity": Decimal("0"),
            "amount": Decimal("0"),
        })
        item["quantity"] += _decimal(row.get("数量"))
        item["amount"] += _decimal(row.get("金额(除税)"))
    return [
        {**item, "quantity": _decimal_text(item["quantity"], "0.001"), "amount": _decimal_text(item["amount"], "0.01")}
        for item in sorted(sources.values(), key=lambda value: (value["invoice_date"], value["invoice_number"]))
    ]


class CostProjectionService:
    def __init__(
        self,
        watch_dir: Path,
        workspace_dir: Path,
        target_id: str,
        reference_markup_rate: str = "0.08",
        *,
        company_taxpayer: Callable[[], dict | None] | None = None,
    ):
        self.watch_dir = Path(watch_dir)
        # Registry lookup (targets.companies.company_taxpayer_for) supplied by every caller —
        # API, monitor daemon, background child, manual rebuild — so the workbook and the page
        # price the reference with the same taxpayer type. None means "no registry company".
        self._company_taxpayer = company_taxpayer
        self.workspace_dir = Path(workspace_dir)
        self.target_id = target_id
        self.reference_markup_rate = reference_markup_rate
        self.detail_csv = self.watch_dir / COST_DETAIL_CSV_NAME
        self.summary_xlsx = self.watch_dir / COST_SUMMARY_XLSX_NAME
        self.status_json = self.watch_dir / COST_REFERENCE_STATUS_NAME
        self.summary_csv = self.workspace_dir / "发票汇总.csv"
        self.outbound_summary_json = self.workspace_dir / OUTBOUND_SUMMARY_NAME

    def rebuild(self, progress: Callable[[int, int], None] | None = None) -> dict:
        # Retain a consistent complete generation before replacing any projection.
        # Read-only pages can use it while the monitor owns the write lock.
        if self.detail_csv.exists():
            self.cache_snapshot()
        with ProgressiveRows(self.workspace_dir, "costs") as preview:
            result = build_cost_analysis_outputs(
                self.watch_dir,
                self.watch_dir,
                invoice_metadata=self._summary_metadata(),
                reference_markup_rate=self._markup_meta()["rate"],
                progress=progress,
                on_rows=preview.add,
                outbound_items=self._outbound_items(),
                company_taxpayer=self.company_taxpayer,
            )
        self.cache_snapshot()
        return result

    def company_taxpayer(self) -> dict | None:
        return self._company_taxpayer() if self._company_taxpayer else None

    def read_fingerprint(self):
        # The registry taxpayer type changes prices without touching any projection file, so it
        # is part of the read generation; otherwise the paged view keeps serving old prices.
        return [str(self.watch_dir.resolve()), self.target_id, str(self.reference_markup_rate), self.company_taxpayer(),
                *[file_signature(path) for path in (self.detail_csv, self.summary_xlsx, self.status_json, self.summary_csv,
                                                    self.outbound_summary_json)]]

    def cache_snapshot(self):
        views = ReadViews(self.workspace_dir)
        meta, _ = views.read("cost:details", page_size=0)
        if meta.get("fingerprint") != self.read_fingerprint():
            snapshot = self.snapshot().model_dump(mode="json")
            views.save_cost(snapshot, self.read_fingerprint())

    def _markup_meta(self) -> dict[str, Any]:
        payload = _read_reference_status_payload(self.status_json)
        rate = normalize_reference_markup_rate(payload.get("reference_markup_rate", self.reference_markup_rate))
        return {
            "rate": rate,
            "display": reference_markup_display(rate),
            "percent": reference_markup_percent_text(rate),
            "locked": _truthy(payload.get("reference_markup_locked", False)),
        }

    def _outbound_items(self) -> dict[str, dict]:
        items = load_outbound_summary(self.workspace_dir).get("items")
        return items if isinstance(items, dict) else {}

    def refresh_outbound(self, outbound_dir: str | Path | None, progress: Callable[[int, int], None] | None = None) -> dict:
        """Re-read the issued-invoice folder (manual 重新汇总 only) and rewrite the workbook with the comparison.

        Monitor-driven rebuilds reuse the last saved summary, so the outbound folder is never
        watched and a stale summary is shown with its read time rather than silently dropped.
        """
        try:
            summary = read_outbound_summary(outbound_dir, self.watch_dir, read_csv_rows(self.detail_csv), self.workspace_dir, progress)
        except Exception as exc:
            # A broken sales file must not fail the cost rebuild; keep the reason visible on the page.
            summary = {**_empty_outbound_summary(str(outbound_dir or ""), f"读取开具发票失败：{exc}")}
            atomic_write_json(self.outbound_summary_json, summary)
        self._refresh_workbook_from_current_detail(self._markup_meta()["rate"])
        return summary

    def _outbound_overview(self, invoice_reference: list[dict]) -> dict:
        summary = load_outbound_summary(self.workspace_dir)
        # Matched / unmatched must use the same 品目表 grouping as the reference rows.
        summary = {**summary, "items": canonical_outbound_items(summary.get("items"), self._item_catalog(), self._exclusions())}
        return outbound_overview(summary, [row["key"] for row in invoice_reference], invoice_reference)

    def _exclusions(self) -> dict[str, dict]:
        return reference_exclusions_from_status(_read_reference_status_payload(self.status_json))

    def _exclusions_overview(self, detail_rows: list[dict]) -> dict:
        exclusions = self._exclusions()
        present_keys = {_reference_key(row) for row in canonical_reference_rows(detail_rows, self._item_catalog())}
        present_invoices = {reference_invoice_id(row) for row in detail_rows}
        keys = [{"key": key, **info, "present": key in present_keys} for key, info in sorted(exclusions["keys"].items())]
        invoices = [{"id": key, **info, "present": key in present_invoices} for key, info in sorted(exclusions["invoices"].items())]
        return {"keys": keys, "invoices": invoices, "count": len(keys) + len(invoices)}

    def _merge_exclusions(self, requested: dict[str, list[str]], detail_rows: list[dict]) -> dict[str, dict]:
        """Keep display info for each removed row / invoice so the restore list stays readable later."""
        saved = self._exclusions()
        rows_by_key: dict[str, dict] = {}
        for row in canonical_reference_rows(detail_rows, self._item_catalog()):
            rows_by_key.setdefault(_reference_key(row), row)
        invoices_by_id: dict[str, dict] = {}
        for row in detail_rows:
            invoices_by_id.setdefault(reference_invoice_id(row), row)
        now = utc_now_text()
        keys = {}
        for key in requested["keys"]:
            row = rows_by_key.get(key)
            keys[key] = saved["keys"].get(key) or {
                "item_code": str((row or {}).get("发票代码(**内文字)") or ""),
                "item_name": str((row or {}).get("内部项目名称") or ""),
                "spec": str((row or {}).get("规格型号") or ""),
                "unit": str((row or {}).get("单位") or ""),
                "excluded_at": now,
            }
        invoices = {}
        for invoice_id in requested["invoices"]:
            row = invoices_by_id.get(invoice_id)
            invoices[invoice_id] = saved["invoices"].get(invoice_id) or {
                "invoice_number": str((row or {}).get("发票号码") or ""),
                "source": Path(str((row or {}).get("源文件") or "")).name,
                "seller": str((row or {}).get("销售方") or ""),
                "invoice_date": str((row or {}).get("开票日期") or ""),
                "excluded_at": now,
            }
        return {"keys": keys, "invoices": invoices}

    def _item_catalog(self) -> dict[str, dict]:
        return item_catalog_from_status(_read_reference_status_payload(self.status_json))

    def read_only_inputs(self) -> dict:
        """Detail rows, 发票校验 rows, item catalog and tax profile of the last projection, nothing else.

        For folders that are not the active watch_dir (WS-07 comparisons): unlike ``snapshot`` it
        never refreshes the schema or rewrites the workbook, so reading cannot change the folder.
        """
        return {
            "detail_rows": read_csv_rows(self.detail_csv),
            "check_rows": self._read_workbook_sheet("发票校验", CHECK_HEADERS),
            "item_catalog": self._item_catalog(),
            "tax_profile": self._tax_profile(),
        }

    def _tax_profile(self) -> ReferenceTaxProfile:
        return effective_tax_profile(
            reference_tax_profile_from_status(_read_reference_status_payload(self.status_json)), self.company_taxpayer()
        )

    def refresh_workbook_tax_profile(self) -> bool:
        """Rewrite the workbook after the registry changed this company's taxpayer type."""
        if not self.detail_csv.exists():
            return False
        self._refresh_workbook_from_current_detail(self._markup_meta()["rate"])
        return True

    def _summary_metadata(self) -> list[dict]:
        rows = []
        for row in read_csv_rows(self.summary_csv):
            rows.append(
                {
                    "源文件": row.get("文件路径", ""),
                    "销售方": row.get("销售方", ""),
                    "购买方": row.get("购买方", ""),
                    "发票号码": row.get("发票号码", ""),
                    "开票日期": row.get("开票时间", ""),
                    "开票金额": row.get("开票金额", ""),
                    "除税价": row.get("除税价", ""),
                    "税金": row.get("税金", ""),
                    "发票大类": row.get("发票类型", ""),
                    "特定业务类型": row.get("特定业务类型", ""),
                    "类型识别状态": row.get("类型识别状态", ""),
                    "类型识别说明": row.get("类型识别说明", ""),
                }
            )
        return rows

    def _refresh_workbook_from_current_detail(self, reference_markup_rate: object) -> None:
        if not self.detail_csv.exists():
            return
        detail_rows = read_csv_rows(self.detail_csv)
        checks = self._read_workbook_sheet("发票校验", CHECK_HEADERS)
        _write_workbook(
            self.summary_xlsx,
            detail_rows,
            checks,
            status_items=_read_reference_status(self.status_json),
            reference_markup_rate=reference_markup_rate,
            tax_profile=self._tax_profile(),
            outbound_items=self._outbound_items(),
            item_catalog=self._item_catalog(),
            exclusions=self._exclusions(),
        )

    def _read_csv_headers(self) -> list[str]:
        if not self.detail_csv.exists():
            return []
        try:
            with self.detail_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                first_line = handle.readline().strip("\r\n")
        except OSError:
            return []
        if not first_line:
            return []
        return [item.strip() for item in first_line.split(",")]

    def _workbook_headers(self, sheet_name: str) -> list[str]:
        if not self.summary_xlsx.exists():
            return []
        wb = None
        try:
            from openpyxl import load_workbook

            wb = load_workbook(self.summary_xlsx, data_only=True, read_only=True)
            if sheet_name not in wb.sheetnames:
                return []
            ws = wb[sheet_name]
            row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            return [str(cell or "").strip() for cell in row]
        except Exception:
            return []
        finally:
            if wb is not None:
                wb.close()

    def needs_schema_refresh(self) -> bool:
        if self.detail_csv.exists() and any(header not in self._read_csv_headers() for header in DETAIL_HEADERS):
            return True
        if self.summary_xlsx.exists():
            required = {
                "发票明细": DETAIL_HEADERS,
                "项目规格汇总": PROJECT_SPEC_SUMMARY_HEADERS,
                "开票参考": INVOICE_REFERENCE_HEADERS,
                "发票校验": CHECK_HEADERS,
            }
            for sheet_name, headers in required.items():
                actual = self._workbook_headers(sheet_name)
                if any(header not in actual for header in headers):
                    return True
        return False

    def refresh_schema_from_current_detail(self) -> bool:
        if not self.detail_csv.exists():
            return False
        detail_rows = read_csv_rows(self.detail_csv)
        markup = self._markup_meta()
        checks = self._read_workbook_sheet("发票校验", CHECK_HEADERS)
        status_items = _read_reference_status(self.status_json)
        workbook_status = self._read_reference_status_from_workbook()
        for key, workbook_item in workbook_status.items():
            if key not in status_items:
                status_items[key] = workbook_item
                continue
            for field, value in workbook_item.items():
                if str(status_items[key].get(field) or "").strip() == "" and str(value or "").strip() != "":
                    status_items[key][field] = value

        write_csv_rows(self.detail_csv, DETAIL_HEADERS, detail_rows_with_tax_average(detail_rows))
        _write_workbook(
            self.summary_xlsx,
            detail_rows,
            checks,
            status_items=status_items,
            reference_markup_rate=markup["rate"],
            tax_profile=self._tax_profile(),
            outbound_items=self._outbound_items(),
            item_catalog=self._item_catalog(),
            exclusions=self._exclusions(),
        )
        return True

    def snapshot(self, from_cache: bool = False) -> CostAnalysisSnapshot:
        if self.needs_schema_refresh():
            try:
                self.refresh_schema_from_current_detail()
            except OSError:
                pass
        detail_rows = detail_rows_with_tax_average(read_csv_rows(self.detail_csv))
        checks = self._read_workbook_sheet("发票校验", CHECK_HEADERS)
        project_summary = self._project_summary_rows()
        markup = self._markup_meta()
        tax_profile = self._tax_profile()
        invoice_reference = self._build_reference_rows(detail_rows, check_rows=checks, tax_profile=tax_profile)
        sync = self._sync_status(detail_rows, checks)
        mismatch_count = sum(1 for row in checks if str(row.get("校验状态") or "").strip() != "通过")
        return CostAnalysisSnapshot(
            watch_dir=str(self.watch_dir),
            source_dir=str(self.watch_dir),
            target_id=self.target_id,
            output_detail_csv_path=str(self.detail_csv),
            output_summary_xlsx_path=str(self.summary_xlsx),
            reference_status_path=str(self.status_json),
            reference_status_exists=self.status_json.exists(),
            reference_markup_rate=markup["display"],
            reference_tax_profile=tax_profile.api_payload(),
            item_catalog=item_catalog_overview(detail_rows, self._item_catalog()),
            reference_exclusions=self._exclusions_overview(detail_rows),
            outbound_summary=self._outbound_overview(invoice_reference),
            detail_count=len(detail_rows),
            check_count=len(checks),
            mismatch_count=mismatch_count,
            from_cache=from_cache,
            items=detail_rows,
            project_summary=project_summary,
            invoice_reference=invoice_reference,
            checks=checks,
            reference_status_stats=self._reference_stats(invoice_reference),
            sync=sync,
        )

    def _project_summary_rows(self) -> list[dict]:
        detail_rows = read_csv_rows(self.detail_csv)
        if detail_rows:
            return project_spec_summary(detail_rows)
        return self._read_workbook_sheet("项目规格汇总", PROJECT_SPEC_SUMMARY_HEADERS)

    def save_reference_status(self, payload: dict) -> dict:
        current = _read_reference_status(self.status_json)
        fallback_markup = self._markup_meta()
        # Unconsumed workbook read kept as-is until ENG-02 decides whether save should
        # merge workbook-only statuses like rebuild() does; removing it changes failure behaviour.
        workbook_status = self._read_reference_status_from_workbook()  # noqa: F841
        tax_profile_changed = "tax_profile" in payload
        saved_tax_profile = parse_reference_tax_profile(payload.get("tax_profile")) if tax_profile_changed else None
        company = self.company_taxpayer()
        if saved_tax_profile is not None and company and saved_tax_profile.taxpayer_type != company["taxpayer_type"]:
            raise ValueError(
                f"纳税人类型以公司清单为准（{company['company_name']}：{TAXPAYER_LABELS[company['taxpayer_type']]}），"
                "请在公司清单修改；这里只能修改销项税率。"
            )
        tax_profile = effective_tax_profile(saved_tax_profile, company) if saved_tax_profile is not None else self._tax_profile()
        catalog_changed = "item_catalog" in payload
        item_catalog = parse_item_catalog(payload.get("item_catalog")) if catalog_changed else self._item_catalog()
        exclusions_changed = "reference_exclusions" in payload
        requested_exclusions = parse_reference_exclusions(payload.get("reference_exclusions")) if exclusions_changed else None
        checks = self._read_workbook_sheet("发票校验", CHECK_HEADERS)
        detail_rows = read_csv_rows(self.detail_csv)
        if catalog_changed:
            current = self._migrate_statuses_to_catalog(detail_rows, current, checks, tax_profile, item_catalog)
        reference_rows = self._build_reference_rows(
            detail_rows, current, check_rows=checks, tax_profile=tax_profile, item_catalog=item_catalog
        )
        by_key = {row["key"]: row for row in reference_rows}
        for item in payload.get("items", []):
            key = str(item.get("key") or "").strip()
            if not key or key not in by_key:
                continue
            row = by_key[key]
            # Already resolved through member keys by _build_reference_rows (merged groups included).
            existing = dict(self._reference_statuses.get(key) or {})
            existing_markup = _row_markup_meta(existing, fallback_markup["rate"], fallback_markup["locked"])
            quantity = _decimal(row.get("quantity"))
            if "invoiced_quantity" in item:
                invoiced_quantity = _user_quantity(item.get("invoiced_quantity"))
                quantity_changed = _decimal(existing.get("invoiced_quantity")) != invoiced_quantity
            else:
                invoiced_quantity = _decimal(existing.get("invoiced_quantity"))
                quantity_changed = False
            if invoiced_quantity < 0:
                raise ValueError("已开数量不能小于 0")
            if invoiced_quantity > quantity:
                raise ValueError(f"已开数量不能大于数量合计: {_decimal_text(quantity, '0.001')}")
            if _has_text(item.get("reference_markup_rate_percent")):
                row_rate = normalize_reference_markup_percent(item.get("reference_markup_rate_percent"))
            elif _has_text(item.get("markup_rate")):
                row_rate = normalize_reference_markup_percent(item.get("markup_rate"))
            elif _has_text(item.get("reference_markup_rate")):
                row_rate = normalize_reference_markup_rate(item.get("reference_markup_rate"), fallback_markup["rate"])
            else:
                row_rate = existing_markup["rate"]
            if "reference_markup_locked" in item:
                row_locked = _truthy(item.get("reference_markup_locked"))
            elif "locked" in item:
                row_locked = _truthy(item.get("locked"))
            else:
                row_locked = existing_markup["locked"]
            row_multiplier = reference_markup_multiplier(row_rate)
            reference_average_unit_price = _decimal(row.get("reference_cost_unit_price")) * row_multiplier
            reference_amount = reference_average_unit_price * quantity
            reference_tax = reference_amount * tax_profile.output_tax_rate
            reference_total = reference_amount + reference_tax
            ratio = Decimal("0") if quantity == 0 else invoiced_quantity / quantity
            status = "已开具" if invoiced_quantity >= quantity and quantity > 0 else ("未开具" if invoiced_quantity == 0 else "部分开具")
            for alias in _reference_aliases(row):
                if alias != key:
                    current.pop(alias, None)
            for member in row.get("member_keys") or []:
                saved = current.get(member)
                if member != key and isinstance(saved, dict) and len(saved.get("member_keys") or [member]) <= 1:
                    current.pop(member, None)  # folded into this merged group's saved status

            def locked_part(field: str, current_total: Decimal) -> Decimal:
                if invoiced_quantity <= 0:
                    return Decimal("0")
                if quantity_changed or not _has_text(existing.get(field)):
                    return current_total * ratio
                return max(_decimal(existing.get(field)), Decimal("0"))

            keep_item = (
                invoiced_quantity > 0
                or row_rate != fallback_markup["rate"]
                or row_locked != fallback_markup["locked"]
            )
            if not keep_item:
                current.pop(key, None)
                continue
            current[key] = {
                "reference_key": key,
                "member_keys": row.get("member_keys") or [key],
                "item_code": row.get("发票代码(**内文字)", ""),
                "item_name": row.get("内部项目名称", ""),
                "spec": row.get("规格型号", ""),
                "unit": row.get("单位", ""),
                "invoiced_quantity": str(invoiced_quantity),
                "quantity_total": _decimal_text(quantity, "0.001"),
                "reference_amount_total": _decimal_text(reference_amount, "0.000001"),
                "reference_tax_total": _decimal_text(reference_tax, "0.000001"),
                "reference_total_with_tax": _decimal_text(reference_total, "0.000001"),
                "reference_markup_rate": _decimal_text(row_rate, "0.000001"),
                "reference_markup_rate_percent": reference_markup_percent_text(row_rate),
                "reference_markup_locked": row_locked,
                "invoiced_reference_amount": _decimal_text(locked_part("invoiced_reference_amount", reference_amount), "0.000001"),
                "invoiced_reference_tax": _decimal_text(locked_part("invoiced_reference_tax", reference_tax), "0.000001"),
                "invoiced_reference_total_with_tax": _decimal_text(locked_part("invoiced_reference_total_with_tax", reference_total), "0.000001"),
                "invoice_status": status,
                "updated_at": utc_now_text(),
            }
        _write_reference_status(
            self.status_json,
            current,
            reference_markup_rate=fallback_markup["rate"],
            reference_markup_locked=fallback_markup["locked"],
            tax_profile=saved_tax_profile,
            item_catalog=item_catalog if catalog_changed else None,
            reference_exclusions=self._merge_exclusions(requested_exclusions, detail_rows) if exclusions_changed else None,
        )
        self._refresh_workbook_from_current_detail(fallback_markup["rate"])
        return {"ok": True, "reference_status_path": str(self.status_json), "workbook_updated": self.summary_xlsx.exists()}

    def _migrate_statuses_to_catalog(
        self,
        detail_rows: list[dict],
        current: dict[str, dict],
        checks: list[dict],
        tax_profile: ReferenceTaxProfile,
        item_catalog: dict[str, dict],
    ) -> dict[str, dict]:
        """Re-key saved 已开 status once when the 品目表 changes, so the file matches the new grouping.

        Merged groups add up their members' saved status; split groups take a quantity share of the
        old merged status. Both keep `merge_note` until the user saves the row, and statuses of names
        that left the 开票参考 (e.g. marked 费用) stay untouched so switching back restores them.
        """
        rows = self._build_reference_rows(detail_rows, current, check_rows=checks, tax_profile=tax_profile, item_catalog=item_catalog)
        migrated = dict(current)
        group_keys = {row["key"] for row in rows}
        for row in rows:
            status = self._reference_statuses.get(row["key"]) or {}
            for member in row["member_keys"]:
                if member != row["key"]:
                    migrated.pop(member, None)
            if status:
                migrated[row["key"]] = {
                    **status,
                    "reference_key": row["key"],
                    "member_keys": row["member_keys"],
                    "quantity_total": _decimal_text(_decimal(row.get("quantity")), "0.001"),
                }
        # A merged status saved under a name no longer used has been shared out above.
        for key in [key for key, item in migrated.items() if key not in group_keys and len(item.get("member_keys") or []) > 1]:
            migrated.pop(key, None)
        return migrated

    def _read_workbook_sheet(self, sheet_name: str, headers: list[str]) -> list[dict]:
        if not self.summary_xlsx.exists():
            return []
        wb = None
        try:
            from openpyxl import load_workbook

            wb = load_workbook(self.summary_xlsx, data_only=True, read_only=True)
            if sheet_name not in wb.sheetnames:
                return []
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
        except Exception:
            return []
        finally:
            if wb is not None:
                wb.close()
        if not rows:
            return []
        header_row = [str(cell or "") for cell in rows[0]]
        effective_headers = header_row if any(header_row) else headers
        result = []
        for values in rows[1:]:
            result.append(
                {
                    effective_headers[i]: values[i] if i < len(values) and values[i] is not None else ""
                    for i in range(len(effective_headers))
                }
            )
        return result

    def _build_reference_rows(
        self,
        detail_rows: list[dict],
        status_items: dict[str, dict] | None = None,
        check_rows: list[dict] | None = None,
        tax_profile: ReferenceTaxProfile | None = None,
        item_catalog: dict[str, dict] | None = None,
    ) -> list[dict]:
        status_items = status_items if status_items is not None else _read_reference_status(self.status_json)
        workbook_status = self._read_reference_status_from_workbook()
        fallback_markup = self._markup_meta()
        tax_profile = tax_profile or self._tax_profile()
        item_catalog = self._item_catalog() if item_catalog is None else item_catalog
        # Same formula as cost_analysis._invoice_reference_summary; the workbook and this API must agree.
        deductibility = input_tax_index(check_rows)
        exclusions = self._exclusions()
        outbound_items = canonical_outbound_items(self._outbound_items(), item_catalog, exclusions)
        self._reference_statuses: dict[str, dict] = {}
        grouped: dict[str, dict] = {}
        for row in canonical_reference_rows(detail_rows, item_catalog, exclusions):
            key = _reference_key(row)
            if key not in grouped:
                grouped[key] = {
                    "key": key,
                    "发票代码(**内文字)": row.get("发票代码(**内文字)", ""),
                    "内部项目名称": row.get("内部项目名称", ""),
                    "规格型号": row.get("规格型号", ""),
                    "单位": row.get("单位", ""),
                    "quantity": Decimal("0"),
                    "amount": Decimal("0"),
                    "tax_amount": Decimal("0"),
                    "total_with_tax": Decimal("0"),
                    "source_rows": [],
                    "aliases": _reference_aliases(row),
                    "members": {},
                }
            grouped[key]["source_rows"].append(row)
            member = grouped[key]["members"].setdefault(row["_member_key"], {"quantity": Decimal("0"), "raw": row["_raw_values"]})
            member["quantity"] += _decimal(row.get("数量"))
            grouped[key]["quantity"] += _decimal(row.get("数量"))
            grouped[key]["amount"] += _decimal(row.get("金额(除税)"))
            grouped[key]["tax_amount"] += _decimal(row.get("税金"))
            grouped[key]["total_with_tax"] += _decimal(row.get("价税合计"))
        result = []
        for key, row in grouped.items():
            quantity = row["quantity"]
            members = row["members"]

            def lookup(alias: str, members=members) -> dict:
                raw = members.get(alias, {}).get("raw")
                aliases = _reference_aliases(dict(zip(("发票代码(**内文字)", "内部项目名称", "规格型号", "单位"), raw))) if raw else [alias]
                return self._status_for_reference({"key": alias, "aliases": aliases}, status_items, workbook_status)

            # Status saved before a 品目表 merge or spec normalisation is found through member keys.
            status = merged_status_item(status_items, key, {k: v["quantity"] for k, v in members.items()}, lookup)
            self._reference_statuses[key] = status
            rate_percent = row["source_rows"][0].get("_output_tax_rate_percent") or ""
            output_tax_rate = _tax_rate_from_percent(rate_percent) if rate_percent else tax_profile.output_tax_rate
            markup = _row_markup_meta(status, fallback_markup["rate"], fallback_markup["locked"])
            markup_multiplier = reference_markup_multiplier(markup["rate"])
            avg_price = average_unit_price(row.get("source_rows") or [])
            avg_price_with_tax = average_unit_price_with_tax(row.get("source_rows") or [])
            purchase_avg_price_with_tax = purchase_reference_average_unit_price_with_tax(row.get("source_rows") or [])
            cost_basis = reference_cost_basis(row.get("source_rows") or [], tax_profile, deductibility)
            cost_price = cost_basis["unit_price"]
            reference_avg_price_with_tax = reference_output_average_unit_price_with_tax(cost_price, markup["rate"], output_tax_rate)
            reference_base_amount = cost_price * quantity if cost_price is not None and quantity > 0 else Decimal("0")
            reference_amount = reference_base_amount * markup_multiplier
            reference_tax = reference_amount * output_tax_rate
            reference_total = reference_amount + reference_tax
            invoiced_quantity = _decimal(status.get("invoiced_quantity"))
            if invoiced_quantity > quantity:
                invoiced_quantity = quantity
            locked_amount = self._locked_reference_part(status, "invoiced_reference_amount", reference_amount, quantity, invoiced_quantity)
            locked_tax = self._locked_reference_part(status, "invoiced_reference_tax", reference_tax, quantity, invoiced_quantity)
            locked_total = self._locked_reference_part(status, "invoiced_reference_total_with_tax", reference_total, quantity, invoiced_quantity)
            outbound = outbound_reference_fields(outbound_items.get(key), quantity, invoiced_quantity, cost_price)
            invoice_status = status.get("invoice_status") or ("已开具" if quantity > 0 and invoiced_quantity >= quantity else ("未开具" if invoiced_quantity == 0 else "部分开具"))
            result.append(
                {
                    **{k: v for k, v in row.items() if not isinstance(v, Decimal) and k not in {"aliases", "source_rows", "members"}},
                    "member_keys": sorted(members),
                    "sources": _reference_sources(row["source_rows"]),
                    "merge_note": str(status.get("merge_note") or ""),
                    "reference_output_tax_rate": _decimal_text(output_tax_rate, "0.000001"),
                    "reference_output_tax_rate_percent": _decimal_text(output_tax_rate * Decimal("100"), "0.001"),
                    "quantity": float(quantity),
                    "average_unit_price": float(avg_price) if avg_price is not None else 0,
                    "average_unit_price_with_tax": float(avg_price_with_tax) if avg_price_with_tax is not None else 0,
                    "purchase_reference_average_unit_price_with_tax": float(purchase_avg_price_with_tax) if purchase_avg_price_with_tax is not None else 0,
                    "reference_cost_unit_price": float(cost_price) if cost_price is not None else 0,
                    "reference_cost_basis": cost_basis["label"],
                    "reference_cost_note": cost_basis["note"],
                    "reference_cost_basis_text": reference_cost_basis_text(cost_basis),
                    "amount": float(row["amount"]),
                    "tax_amount": float(row["tax_amount"]),
                    "total_with_tax": float(row["total_with_tax"]),
                    "markup_rate": markup["display"],
                    "reference_markup_rate": _decimal_text(markup["rate"], "0.000001"),
                    "reference_markup_rate_percent": markup["percent"],
                    "reference_markup_locked": markup["locked"],
                    "reference_average_unit_price": float(reference_amount / quantity) if quantity else 0,
                    "reference_average_unit_price_with_tax": float(reference_avg_price_with_tax) if reference_avg_price_with_tax is not None else 0,
                    "reference_amount": float(reference_amount),
                    "reference_tax_amount": float(reference_tax),
                    "reference_total_with_tax": float(reference_total),
                    "invoiced_quantity": float(invoiced_quantity),
                    "uninvoiced_quantity": float(max(Decimal("0"), quantity - invoiced_quantity)),
                    "invoice_status": invoice_status,
                    "invoiced_reference_amount": float(locked_amount),
                    "invoiced_reference_tax_amount": float(locked_tax),
                    "invoiced_reference_total_with_tax": float(locked_total),
                    "uninvoiced_reference_amount": float(max(Decimal("0"), reference_amount - locked_amount)),
                    "uninvoiced_reference_tax": float(max(Decimal("0"), reference_tax - locked_tax)),
                    "uninvoiced_reference_total_with_tax": float(max(Decimal("0"), reference_total - locked_total)),
                    "status_updated_at": str(status.get("updated_at") or ""),
                    "outbound_quantity": float(outbound["outbound_quantity"]),
                    "outbound_amount": float(outbound["outbound_amount"]),
                    "outbound_unit_price": float(outbound["outbound_unit_price"]) if outbound["outbound_unit_price"] is not None else None,
                    "outbound_invoice_count": outbound["outbound_invoice_count"],
                    "actual_markup_rate": _decimal_text(outbound["actual_markup_rate"], "0.000001") if outbound["actual_markup_rate"] is not None else "",
                    "actual_markup_text": outbound["actual_markup_text"],
                    "outbound_compare": outbound["outbound_compare"],
                    "outbound_compare_text": outbound["outbound_compare_text"],
                    "outbound_suggested_quantity": float(outbound["outbound_suggested_quantity"]),
                }
            )
        return sorted(result, key=lambda item: item["key"])

    def _status_for_reference(self, row: dict, status_items: dict[str, dict], workbook_status: dict[str, dict]) -> dict:
        status: dict[str, Any] = {}
        for alias in row.get("aliases") or [row.get("key", "")]:
            if alias in status_items:
                status = dict(status_items[alias])
                break
        workbook_item = workbook_status.get(row.get("key", ""))
        if workbook_item:
            if not status:
                status = dict(workbook_item)
            else:
                for field in (
                    "invoiced_reference_amount",
                    "invoiced_reference_tax",
                    "invoiced_reference_total_with_tax",
                    "reference_markup_rate",
                    "reference_markup_rate_percent",
                    "reference_markup_locked",
                    "updated_at",
                ):
                    if str(status.get(field) or "").strip() == "" and str(workbook_item.get(field) or "").strip() != "":
                        status[field] = workbook_item[field]
        if status:
            status = _normalize_status_item(str(row.get("key") or ""), status)
        return status

    def _locked_reference_part(
        self,
        status: dict,
        field: str,
        current_total: Decimal,
        quantity: Decimal,
        invoiced_quantity: Decimal,
    ) -> Decimal:
        if invoiced_quantity <= 0:
            return Decimal("0")
        value = _decimal(status.get(field))
        if value == 0 and str(status.get(field) or "").strip() == "":
            value = Decimal("0") if quantity <= 0 else current_total * invoiced_quantity / quantity
        if value < 0:
            return Decimal("0")
        return value

    def _read_reference_status_from_workbook(self) -> dict[str, dict]:
        rows = self._read_workbook_sheet("开票参考", INVOICE_REFERENCE_HEADERS)
        result: dict[str, dict] = {}
        for row in rows:
            key = _reference_key_from_values(
                row.get("发票代码(**内文字)", ""),
                row.get("内部项目名称", ""),
                row.get("规格型号", ""),
                row.get("单位", ""),
            )
            if not key:
                continue
            invoiced_quantity = _decimal(row.get("已开数量"))
            markup_text = str(row.get("参考加价率") or "").strip()
            if invoiced_quantity <= 0 and not markup_text:
                continue
            markup_rate = normalize_reference_markup_rate(markup_text, self.reference_markup_rate)
            quantity = _decimal(row.get("数量合计"))
            reference_total = _decimal(row.get("价税合计"))
            locked_total = _decimal(row.get("已开参考价税合计"))
            ratio = Decimal("0") if reference_total <= 0 else locked_total / reference_total
            result[key] = {
                "reference_key": key,
                "item_code": str(row.get("发票代码(**内文字)") or ""),
                "item_name": str(row.get("内部项目名称") or ""),
                "spec": str(row.get("规格型号") or ""),
                "unit": str(row.get("单位") or ""),
                "invoiced_quantity": _decimal_text(invoiced_quantity, "0.001"),
                "quantity_total": _decimal_text(quantity, "0.001"),
                "reference_total_with_tax": _decimal_text(reference_total, "0.000001"),
                "reference_markup_rate": _decimal_text(markup_rate, "0.000001"),
                "reference_markup_rate_percent": reference_markup_percent_text(markup_rate),
                "reference_markup_locked": False,
                "invoiced_reference_amount": _decimal_text(_decimal(row.get("金额(除税)合计")) * ratio, "0.000001"),
                "invoiced_reference_tax": _decimal_text(_decimal(row.get("税金合计")) * ratio, "0.000001"),
                "invoiced_reference_total_with_tax": _decimal_text(locked_total, "0.000001"),
                "updated_at": str(row.get("状态更新时间") or ""),
            }
        return result

    def _reference_stats(self, rows: list[dict]) -> dict:
        invoiced_count = sum(1 for row in rows if row.get("invoice_status") == "已开具")
        partial_count = sum(1 for row in rows if row.get("invoice_status") == "部分开具")
        not_invoiced_count = sum(1 for row in rows if row.get("invoice_status") == "未开具")
        inventory_total_with_tax = sum(float(row.get("total_with_tax") or 0) for row in rows)
        return {
            "row_count": len(rows),
            "total": len(rows),
            "not_invoiced": not_invoiced_count,
            "partial": partial_count,
            "invoiced": invoiced_count,
            "inventory_total_with_tax": inventory_total_with_tax,
            "project_total_with_tax": inventory_total_with_tax,
            "reference_total_with_tax": sum(float(row.get("reference_total_with_tax") or 0) for row in rows),
            "invoiced_reference_total_with_tax": sum(float(row.get("invoiced_reference_total_with_tax") or 0) for row in rows),
            "uninvoiced_reference_amount": sum(float(row.get("uninvoiced_reference_amount") or 0) for row in rows),
            "uninvoiced_reference_total_with_tax": sum(float(row.get("uninvoiced_reference_total_with_tax") or 0) for row in rows),
        }

    def _sync_status(self, detail_rows: list[dict], checks: list[dict]) -> CostSyncStatus:
        source_groups = _cost_source_groups_from_summary(self.summary_csv)
        parsed_keys = _keys_from_rows(detail_rows)
        checked_keys = _keys_from_rows(checks)
        parsed = _sources_from_rows(detail_rows)
        checked = _sources_from_rows(checks)
        review_checks = [row for row in checks if str(row.get("校验状态") or "").strip() != "通过"]
        review_keys = _keys_from_rows(review_checks)
        review_sources = _sources_from_rows(review_checks)
        if not source_groups and not detail_rows and not checks:
            return CostSyncStatus(sync_state="empty")
        if not self.detail_csv.exists() and not self.summary_xlsx.exists():
            return CostSyncStatus(source_invoice_count=len(source_groups), sync_state="not_generated", pending_count=len(source_groups))
        if source_groups:
            pending = {source for source, keys in source_groups.items() if not keys.intersection(parsed_keys)}
            checked_groups = {source for source, keys in source_groups.items() if keys.intersection(checked_keys)}
            parsed_groups = {source for source, keys in source_groups.items() if keys.intersection(parsed_keys)}
            review_groups = {source for source, keys in source_groups.items() if keys.intersection(review_keys)}
            not_parsed = checked_groups - parsed_groups
            source_count = len(source_groups)
            parsed_count = len(parsed_groups)
            checked_count = len(checked_groups)
            review_count = len(review_groups)
        else:
            pending = set()
            not_parsed = checked - parsed
            source_count = len(parsed or checked)
            parsed_count = len(parsed)
            checked_count = len(checked)
            review_count = len(review_sources)
        state = "fresh"
        if pending:
            state = "pending"
        if not_parsed or review_count:
            state = "needs_review"
        return CostSyncStatus(
            source_invoice_count=source_count,
            parsed_invoice_count=parsed_count,
            checked_invoice_count=checked_count,
            missing_count=len(pending),
            pending_count=len(pending),
            not_parsed_count=len(not_parsed),
            review_count=review_count,
            sync_state=state,
        )
