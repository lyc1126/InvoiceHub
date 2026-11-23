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
import re
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.storage import generations
from invoice_hub.extraction.parsers import SUPPORTED_EXTS
from invoice_hub.monitoring.state import PROCESSED_FILE_NAME, canonical_path as monitor_path_key
from invoice_hub.projections.cost_analysis import COST_DETAIL_CSV_NAME
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.incremental import current_parser_versions
from invoice_hub.services.company_bank import BankFlowReader, build_bank_ledger
from invoice_hub.services.company_bank_layouts import BankLayoutService
from invoice_hub.services.company_tax import CompanyTaxService
from invoice_hub.services.company_compare_details import attach_details
from invoice_hub.services.company_receipts import CompanyReceiptService
from invoice_hub.services.company_deduction import DeductionListReader, build_deduction_check
from invoice_hub.services.company_inventory import build_inventory_check, read_book_inputs
from invoice_hub.services.company_payroll import read_payroll, save_confirmed as save_payroll_months
from invoice_hub.services.company_projects import (
    MAX_PROJECT_NAME,
    ProjectAssignmentStore,
    _clean as _clean_project_name,
    build_project_summary,
    project_fields,
    remark_projects,
)
from invoice_hub.services.company_refresh import CompanyDataRefreshService
from invoice_hub.services.company_same_number import INVOICE_DIR_KEYS, build_same_number_check
from invoice_hub.services.company_settlement import build_settlement_check
from invoice_hub.services import company_vouchers
from invoice_hub.services.invoice_tags import TAG_DEFINITIONS_NAME, InvoiceTagStore
from invoice_hub.services.company_ledger import build_invoice_ledger
from invoice_hub.services.company_opening import account_ledger, read_opening
from invoice_hub.services.company_registry import CompanyRegistryError, CompanyRegistryService
from invoice_hub.services.file_preview import FilePreviewError, MAX_PREVIEW_SELECTION_RECORDS
from invoice_hub.services.invoice_selection import selection_family_key
from invoice_hub.services.invoice_list import InvoiceListService
from invoice_hub.services.source_move import SourceMoveService, period_folder_check
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig, target_profile_for
from invoice_hub.targets.companies import company_outbound_for, company_taxpayer_for

# Folder pair -> comparison algorithm. Only pairs with a reconciliation relation are listed.
COMPARE_RELATIONS = {
    frozenset(("cost_invoice_dir", "input_deduction_dir")): "deduction",
    frozenset(("cost_invoice_dir", "issued_invoice_dir")): "inventory",
    frozenset(("cost_invoice_dir", "bank_flow_dir")): "settlement_payable",
    frozenset(("issued_invoice_dir", "bank_flow_dir")): "settlement_receivable",
}
# Folder behind each side of a comparison's `records` (same order as frontend/src/relations.ts).
RECORD_SIDES = {
    "deduction": ("cost_invoice_dir", "input_deduction_dir"),
    "inventory": ("cost_invoice_dir", "issued_invoice_dir"),
    "settlement_payable": ("cost_invoice_dir", "bank_flow_dir"),
    "settlement_receivable": ("issued_invoice_dir", "bank_flow_dir"),
}
_MONTH_TEXT = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
FRESHNESS_MAX_ENTRIES = 20_000
FRESHNESS_MAX_SECONDS = 2.0
FRESHNESS_MESSAGES = {
    "monitored": "当前监控目录，新发票会自动读取。",
    "fresh": "已是最新数据。",
    "stale": "文件夹里的发票有变动，点“更新数据”即可重新汇总（设为监控目录会自动更新）。",
    "never_built": "还没读取过数据，点“读取数据”即可直接查看（设为监控目录会自动更新）。",
    "unknown": "暂时无法确认是不是最新，可以点“更新数据”重新读取。",
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
    try:
        summary_exists = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), "发票汇总.csv").exists()
    except ValueError:
        return result
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
        try:
            parser_stale = generations.parser_versions_stale(
                Path(profile.workspace_dir),
                Path(profile.watch_dir),
                current_parser_versions(),
            )
        except ValueError:
            return result
        if parser_stale:
            result["state"] = "stale"
            result["parser_stale"] = True
        else:
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
        bank_reader: BankFlowReader | None = None,
        deduction_reader: DeductionListReader | None = None,
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._db_path = db_path
        self._config = config
        self._active_profile = active_profile
        self._registry = registry
        self._active_invoices = active_invoices
        self.bank_layouts = BankLayoutService(registry)
        self.tax = CompanyTaxService(registry)
        self._bank_reader = bank_reader or BankFlowReader(self.bank_layouts.discover, cache_context=self.bank_layouts.cache_revision)
        self._deduction_reader = deduction_reader or DeductionListReader()
        self._projects = ProjectAssignmentStore()
        self.receipts = CompanyReceiptService(registry)
        # Tag definitions live beside the company registry; marks live in each company folder.
        self._tags = InvoiceTagStore(Path(registry.registry_path).parent / TAG_DEFINITIONS_NAME)
        # Move plans and journals of misfiled source files (WS-05): runtime state, never business data.
        self._moves = SourceMoveService(Path(registry.registry_path).parent / "source-moves")
        # Read-only background invoice refresh for non-monitored company folders; never switches watch_dir.
        self.refresh = CompanyDataRefreshService(
            registry=registry,
            config=self._config,
            active_profile=self._active_profile,
            repo=repo,
            db_path=db_path,
            freshness_check=directory_freshness,
        )

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
        manifest = generations.current(Path(profile.workspace_dir), Path(profile.watch_dir))
        summary_csv = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), "发票汇总.csv", manifest)
        cost_csv = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), COST_DETAIL_CSV_NAME, manifest)
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
        if freshness.get("parser_stale") and not (freshness.get("added") or freshness.get("updated") or freshness.get("deleted")):
            freshness["message"] = "识别规则已更新，点“更新数据”即可重新汇总。"
        else:
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
        tag_filter = str(filters.pop("tag", "") or "")
        payload, read_only = self._list_payload(profile, filters)
        if not read_only:
            payload = self.active_project_fields(payload)
        # Copies: the active folder's rows come from the live homepage service, whose payload
        # must not pick up the company fields or tags added here.
        payload = dict(payload)
        items = [dict(item) for item in payload["items"]]
        payload["items"] = items
        if read_only and key in INVOICE_DIR_KEYS and company.get("root_status") == "present":
            self._attach_company_project_fields(payload, Path(company["root_path"]), profile)
        # Tags are display data only: attached after the list is built, never fed back into it.
        tags_error = ""
        marks: dict[str, list[str]] = {}
        if company.get("root_status") == "present":
            try:
                marks = self._tags.visible_marks(Path(company["root_path"]))
            except CompanyRegistryError as exc:
                tags_error = exc.message
        for item in items:
            item["tags"] = marks.get(str(item.get("invoice_number") or ""), [])
        if tag_filter:
            items = [item for item in items if tag_filter in item["tags"]]
            payload["items"] = items
            payload["count"] = len(items)
            payload["stats"] = {**payload["stats"], "filtered": InvoiceListService._invoice_stats(items)}
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
            tags_error=tags_error,
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
            cost_service=lambda: self._cost_service(profile),
        )
        payload = reader.list_invoices(filters)
        for item in payload["items"]:
            item["detail_url"] = ""
            item["read_only"] = True
        payload["snapshot"]["source_label"] = "上次汇总（非监控目录，只读）"
        return payload, True

    def company_ledger(
        self, company_id: str, *, granularity: str = "month", start: str = "", end: str = "", check_freshness: bool = True,
        include_bank: bool = True,
    ) -> dict:
        """进项 (成本发票) and 销项 (开具发票) from their last projections, plus 银行流水 statements."""
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
        bank = self._bank_ledger(company, granularity=granularity, start=start, end=end) if include_bank else None
        from invoice_hub.services.company_inventory import read_book_inputs
        root = self._company_root(company)
        book = read_book_inputs(root)
        accounts = account_ledger(read_opening(root), book.booked, start=start, end=end, error=book.error)
        return {"ok": True, "revision": payload["revision"], "company": company, "sources": sources, **ledger, "bank": bank, "accounts": accounts}

    def compare(self, company_id: str, a: str, b: str, *, start: str = "", end: str = "") -> dict:
        """Compare two folders of one company by their relation (WS-07 step 4).

        The algorithm follows the pair, not the request: pairs with no reconciliation relation are
        refused, so the page never shows a made-up link between unrelated documents.
        """
        for label, value in (("start", start), ("end", end)):
            if value and not _MONTH_TEXT.match(value):
                raise CompanyRegistryError("COMPANY_COMPARE_INVALID", f"{label} 须为 YYYY-MM。", status_code=422, field=label)
        if start and end and start > end:
            raise CompanyRegistryError("COMPANY_COMPARE_INVALID", "开始月份不能晚于结束月份。", status_code=422, field="start")
        relation = COMPARE_RELATIONS.get(frozenset((a, b)))
        if relation is None:
            raise CompanyRegistryError(
                "COMPANY_COMPARE_UNSUPPORTED", "这两类资料之间没有可勾稽的关系，只能分别查看。", status_code=422, field="b",
            )
        payload = self._registry.get_company(company_id)
        company = payload["company"]
        base = {"ok": True, "revision": payload["revision"], "company": company, "a": a, "b": b,
                "start": start, "end": end, "relation": relation}
        if relation.startswith("settlement_"):
            result = self._compare_settlement(company, base, side=relation.removeprefix("settlement_"), start=start, end=end)
        else:
            handler = self._compare_deduction if relation == "deduction" else self._compare_inventory
            result = handler(company, base, start=start, end=end)
        for side, key in zip(("a", "b"), RECORD_SIDES[relation]):
            self._attach_previews((result.get("records") or {}).get(side), company, key, (result.get("sources") or {}).get(key))
        attach_details(result)
        if result.get("records") and result.get("relation") == "settlement":
            try:
                catalog = self.receipts.catalog(company_id, start=start, end=end)
                visible = {row["id"] for row in result["records"]["b"]}
                result["receipts"] = catalog["records"]
                result["warnings"].extend(catalog["issues"])
                for receipt in result["receipts"]:
                    flow_ids = set(receipt.pop("flow_ids")) & visible
                    related = [row["detail"] for row in result["records"]["b"] if row["id"] in flow_ids]
                    receipt["detail"] = {"label": f"回单 · {receipt['source_file']}", "steps": receipt.pop("steps"),
                                         "record_ids": {"a": sorted({id_ for row in related for id_ in row["record_ids"]["a"]}),
                                                        "b": sorted(flow_ids)}}
            except (FilePreviewError, CompanyRegistryError):
                result["receipts"] = []
                result["warnings"].append({"code": "receipts_unavailable", "message": "银行回单暂不可读取，请核对公司目录后重新核对。"})
        return result

    def _attach_previews(self, records: list[dict] | None, company: dict, key: str, view: dict | None) -> None:
        """Give the monitored folder's invoice records the identities the preview pipeline needs (WS-04).

        Only the active folder: preview-jobs re-validates `invoice_key + source_path` against the current
        watch_dir list, so identities of any other folder would be stale positions of another projection.
        A provisional list has no stable identity yet and gets none.
        """
        if not records or key not in INVOICE_DIR_KEYS or not view or not view.get("active"):
            return
        payload = self._list_payload(self._directory(company, key)[1], {})[0]
        if (payload.get("snapshot") or {}).get("provisional"):
            return
        families: dict[str, list[dict]] = defaultdict(list)
        for item in payload["items"]:
            if item.get("source_path") and item.get("invoice_key"):
                families[selection_family_key(item)].append({"invoice_key": item["invoice_key"], "source_path": item["source_path"]})
        for record in records:
            items = families.get(f"number:{record.get('invoice_number') or ''}")
            if record.get("invoice_number") and items:
                record["preview"] = {"target_id": view["target_id"], "items": items[:MAX_PREVIEW_SELECTION_RECORDS]}

    def same_number(self, company_id: str, a: str, b: str, *, b_company_id: str = "") -> dict:
        """Invoice numbers on both of two invoice folders without a relation, possibly of two companies (WS-04).

        Pairs that do have a reconciliation relation belong to ``compare`` and are refused here, so a
        related pair is never reduced to a bare number match.
        """
        b_company_id = b_company_id or company_id
        for field, key in (("a", a), ("b", b)):
            if key not in INVOICE_DIR_KEYS:
                raise CompanyRegistryError("COMPANY_COMPARE_INVALID", "同号检查只用于发票目录（成本发票、开具发票、费用报销）。",
                                           status_code=422, field=field)
        same_company = b_company_id == company_id
        if same_company and a == b:
            raise CompanyRegistryError("COMPANY_COMPARE_INVALID", "请选择两个不同的目录。", status_code=422, field="b")
        if same_company and frozenset((a, b)) in COMPARE_RELATIONS:
            raise CompanyRegistryError("COMPANY_COMPARE_UNSUPPORTED", "这两类资料有勾稽关系，请用“勾稽”核对。", status_code=422, field="b")
        companies = {"a": self._registry.get_company(company_id)["company"], "b": self._registry.get_company(b_company_id)["company"]}
        keys = {"a": a, "b": b}
        active_id = self.active_profile.id
        sides, rows, labels = {}, {}, {}
        for side in ("a", "b"):
            subdir, view, profile = self._cost_source(companies[side], keys[side], active_id)
            labels[side] = f"{companies[side]['name']} · {subdir['label']}"
            sides[side] = {"company_id": companies[side]["id"], "company_name": companies[side]["name"], "key": keys[side],
                           "label": labels[side], "source": view}
            rows[side] = self._list_payload(profile, {})[0]["items"] if subdir["status"] == "present" else []
        base = {"ok": True, "relation": "same_number", "sides": sides}
        missing = [labels[side] for side in ("a", "b") if sides[side]["source"]["status"] != "present"]
        if missing:
            return {**base, "state": "missing_dir", "message": f"{'、'.join(missing)} 目录不存在。"}
        result = build_same_number_check(rows["a"], rows["b"], a_key=a, b_key=b, same_company=same_company, labels=labels)
        for side in ("a", "b"):
            self._attach_previews(result["records"][side], companies[side], keys[side], sides[side]["source"])
        self._freshness_warnings(result, {side: sides[side]["source"] for side in ("a", "b")}, labels)
        types = {side: companies[side].get("current_taxpayer_type") for side in ("a", "b")}
        if not same_company and types["a"] != types["b"]:
            result["warnings"].append({"code": "taxpayer_differs",
                                       "message": "两家公司的纳税人身份不同（或有一方未设置），税额不可直接比较。"})
        if not rows["a"] and not rows["b"]:
            return {**base, "state": "no_details", "message": "两个目录都还没有汇总过（设为监控目录汇总一次后才有发票）。", **result}
        return {**base, "state": "ok", "message": "", **result}

    def _cost_source(self, company: dict, key: str, active_id: str) -> tuple[dict, dict, TargetProfile]:
        subdir, profile = self._directory(company, key)
        return subdir, self._directory_view(subdir, profile, active_id, check_freshness=True), profile

    @staticmethod
    def _freshness_warnings(result: dict, views: dict[str, dict], labels: dict[str, str]) -> None:
        for key, view in views.items():
            state = view["freshness"]["state"]
            if state in {"stale", "never_built", "unknown", "missing_dir"}:
                result["warnings"].insert(0, {"code": f"source_{state}", "message": f"{labels[key]}：{view['freshness']['message']}"})

    def _compare_deduction(self, company: dict, base: dict, *, start: str, end: str) -> dict:
        active_id = self.active_profile.id
        cost_subdir, cost_view, cost_profile = self._cost_source(company, "cost_invoice_dir", active_id)
        list_subdir = next(item for item in company["subdirs"] if item["key"] == "input_deduction_dir")
        sources = {"cost_invoice_dir": cost_view, "input_deduction_dir": {**list_subdir}}
        base = {**base, "sources": sources}
        cost_rows = self._list_payload(cost_profile, {})[0]["items"] if cost_subdir["status"] == "present" else []
        if list_subdir["status"] != "present":
            return {**base, "state": "missing_dir", "message": FRESHNESS_MESSAGES["missing_dir"]}
        read = self._deduction_reader.read(Path(list_subdir["path"]))
        sources["input_deduction_dir"].update(file_count=read.file_count, cached=read.cached)
        if read.data is None:
            return {**base, "state": "unreadable", "message": read.error}
        result = build_deduction_check(cost_rows, read.data, start=start, end=end)
        self._freshness_warnings(result, {"cost_invoice_dir": cost_view}, {"cost_invoice_dir": "成本发票"})
        return {**base, "state": "ok" if read.data.lists else "no_lists",
                "message": "" if read.data.lists else "进项抵扣目录里没有可识别的用途确认信息导出（.xlsx）。", **result}

    def _compare_inventory(self, company: dict, base: dict, *, start: str, end: str) -> dict:
        active_id = self.active_profile.id
        cost_subdir, cost_view, cost_profile = self._cost_source(company, "cost_invoice_dir", active_id)
        sale_subdir, sale_view, sale_profile = self._cost_source(company, "issued_invoice_dir", active_id)
        base = {**base, "sources": {"cost_invoice_dir": cost_view, "issued_invoice_dir": sale_view}}
        if cost_subdir["status"] != "present" or sale_subdir["status"] != "present":
            return {**base, "state": "missing_dir", "message": "成本发票或开具发票目录不存在。"}
        # Read-only: these folders may not be the watch_dir, so nothing may refresh their projection.
        purchases = self._cost_service(cost_profile).read_only_inputs()
        sales = self._cost_service(sale_profile).read_only_inputs()
        # The opening comes from the books' 序时账 read-back in the company folder (read-only, request time);
        # without one the check starts from zero and says so.
        try:
            book = read_book_inputs(Path(company["root_path"]), company["id"]) if company.get("root_status") == "present" else None
            # The item catalog and taxpayer type belong to the purchase side (the 成本发票 folder).
            result = build_inventory_check(
                purchases["detail_rows"], purchases["check_rows"], sales["detail_rows"],
                item_catalog=purchases["item_catalog"], tax_profile=purchases["tax_profile"], book=book, start=start, end=end,
            )
        except (ValueError, OSError) as exc:
            # A stale confirmed account binding cannot silently return a legacy
            # stock category; the comparison must give the same repair signal as V2.
            raise CompanyRegistryError("COMPANY_STOCK_INVALID", str(exc), status_code=409) from exc
        self._freshness_warnings(result, {"cost_invoice_dir": cost_view, "issued_invoice_dir": sale_view},
                                 {"cost_invoice_dir": "成本发票", "issued_invoice_dir": "开具发票"})
        if not purchases["detail_rows"] and not sales["detail_rows"]:
            return {**base, "state": "no_details", "message": "两个目录都还没有成本明细（设为监控目录汇总一次后才有发票明细行）。", **result}
        return {**base, "state": "ok", "message": "", **result}

    def _compare_settlement(self, company: dict, base: dict, *, side: str, start: str, end: str) -> dict:
        active_id = self.active_profile.id
        key = "cost_invoice_dir" if side == "payable" else "issued_invoice_dir"
        label = "成本发票" if side == "payable" else "开具发票"
        invoice_subdir, invoice_view, invoice_profile = self._cost_source(company, key, active_id)
        bank_subdir = next(item for item in company["subdirs"] if item["key"] == "bank_flow_dir")
        sources = {key: invoice_view, "bank_flow_dir": {**bank_subdir}}
        base = {**base, "relation": "settlement", "side": side, "sources": sources}
        items = []
        if invoice_subdir["status"] == "present":
            items = self._list_payload(invoice_profile, {})[0]["items"]
        from invoice_hub.bank.workpaper import WorkpaperInput
        read = self._bank_reader.read(Path(bank_subdir["path"])) if bank_subdir["status"] == "present" else None
        if read:
            sources["bank_flow_dir"].update(file_count=read.file_count, cached=read.cached)
        data = read.data if read and read.data else WorkpaperInput([], [], [], [])
        result = build_settlement_check(items, data, side=side, own_names={company["name"]}, start=start, end=end,
                                        opening=read_opening(self._company_root(company)))
        self._freshness_warnings(result, {key: invoice_view}, {key: label})
        try:
            manual = self._projects.load(self._company_root(company))["invoices"]
            details = self._cost_service(invoice_profile).read_only_inputs()["detail_rows"] if items else []
            remarks = remark_projects(details)
            for row in result["records"]["a"]:
                fields = project_fields(row["invoice_number"], remarks, manual)
                row.update(project=fields["project"] or None,
                           project_source=fields["project_source"] if fields["project_source"] in {"manual", "remark"} else None)
        except (CompanyRegistryError, OSError, ValueError):
            result["warnings"].append({"code": "projects_unavailable", "message": "项目归属无法读取，请到项目页核对。"})
        state, message = "ok", ""
        if invoice_subdir["status"] != "present" or bank_subdir["status"] != "present":
            state, message = "missing_dir", f"{label}或银行流水目录不存在。"
        elif read and read.data is None:
            state, message = "unreadable", read.error
        elif not data.statements:
            state, message = "no_statements", "银行流水目录里没有可识别的对账单。"
        if state != "ok" or invoice_view["freshness"]["state"] in {"stale", "unknown", "never_built"}:
            for row in result["records"]["a"]:
                row["flow_match"] = None
        return {**base, "state": state, "message": message, **result}

    def _company_root(self, company: dict) -> Path:
        if company.get("root_status") != "present":
            raise CompanyRegistryError("COMPANY_ROOT_UNAVAILABLE", "公司资料夹不存在或不可用。", status_code=409)
        return Path(company["root_path"])

    def company_projects(self, company_id: str, *, granularity: str = "month", start: str = "", end: str = "") -> dict:
        """Project summary (WS-03): remark project names, manual assignments win, 未归属 kept apart."""
        payload = self._registry.get_company(company_id)
        company = payload["company"]
        root = self._company_root(company)
        assignments = self._projects.load(root)
        active_id = self.active_profile.id
        rows, details, sources = {}, {}, {}
        for direction, key in (("input", "cost_invoice_dir"), ("output", "issued_invoice_dir")):
            subdir, view, profile = self._cost_source(company, key, active_id)
            sources[direction] = view
            present = subdir["status"] == "present"
            rows[direction] = self._list_payload(profile, {})[0]["items"] if present else []
            details[direction] = self._cost_service(profile).read_only_inputs()["detail_rows"] if present else []
        try:
            result = build_project_summary(
                rows["input"], rows["output"], input_details=details["input"], output_details=details["output"],
                manual=assignments["invoices"],
                aliases=assignments["aliases"],
                granularity=granularity, start=start, end=end,
            )
        except ValueError as exc:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", str(exc)) from exc
        self._freshness_warnings(result, {"cost_invoice_dir": sources["input"], "issued_invoice_dir": sources["output"]},
                                 {"cost_invoice_dir": "成本发票", "issued_invoice_dir": "开具发票"})
        return {"ok": True, "revision": payload["revision"], "company": company, "sources": sources,
                "assignments_revision": assignments["revision"], **result}

    def _attach_company_project_fields(self, result: dict, root: Path, profile: TargetProfile) -> None:
        # Enrich copied rows of a company's cost/issued directory without mutating cached payloads.
        for row in result["items"]:
            row.setdefault("project", "")
            row.setdefault("project_source", "none")
        try:
            remarks = remark_projects(self._cost_service(profile).read_only_inputs()["detail_rows"])
            loaded = self._projects.load(root)
            manual, aliases = loaded["invoices"], loaded["aliases"]
            for row in result["items"]:
                family = selection_family_key(row)
                number = family.split(":", 1)[1] if family.startswith("number:") else ""
                row.update(project_fields(number, remarks, manual, aliases))
        except (CompanyRegistryError, OSError, ValueError):
            result["projects_error"] = "项目归属无法读取，未显示项目；请到公司项目页核对。"
            for row in result["items"]:
                row["project"] = ""
                row["project_source"] = "unavailable"

    def active_project_fields(self, payload: dict) -> dict:
        # Enrich copies after paging; project edits must be visible without invalidating the
        # invoice identity cache, and must never change selection totals or write projections.
        profile = self.active_profile
        result = {**payload, "items": [{**row, "project": "", "project_source": "none"} for row in payload["items"]]}
        if payload.get("target_id") != profile.id:
            return result
        try:
            company = next((company for company in self._registry.list_companies()["companies"]
                            if company.get("monitored_subdir_key") in INVOICE_DIR_KEYS and company.get("monitored")), None)
            remarks = remark_projects(self._cost_service(profile).read_only_inputs()["detail_rows"])
            loaded = self._projects.load(self._company_root(company)) if company else {"invoices": {}, "aliases": {}}
            manual, aliases = loaded["invoices"], loaded["aliases"]
            for row in result["items"]:
                # The ledger also accepts a unique 20-digit filename family when the
                # format has no header number; all copies must show the same project.
                family = selection_family_key(row)
                number = family.split(":", 1)[1] if family.startswith("number:") else ""
                row.update(project_fields(number, remarks, manual, aliases))
        except (CompanyRegistryError, OSError, ValueError):
            result["projects_error"] = "项目归属无法读取，未显示项目；请到公司项目页核对。"
            for row in result["items"]:
                row["project_source"] = "unavailable"
        return result

    def save_project_assignments(self, company_id: str, body: object) -> dict:
        # Written into the company folder on the user's explicit save only; rebuilds never touch it.
        company = self._registry.get_company(company_id)["company"]
        saved = self._projects.update(self._company_root(company), body)
        return {"ok": True, "assignments_revision": saved["revision"], "count": len(saved["invoices"])}

    def _compute_project_rename_preview(self, company_id: str, body: object) -> tuple[dict, dict, dict | None, Path]:
        import hashlib
        import json as _json
        from invoice_hub.services.cost_records import read_company_state
        from invoice_hub.services.cost_service_costs import SERVICE_COST_FILE, normalize_costs

        if not isinstance(body, dict):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "请求格式不正确。")
        revision = body.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "缺少项目归属版本号 revision。", field="revision")
        from_name = _clean_project_name(body.get("from_name"))
        to_name = _clean_project_name(body.get("to_name"))
        if not from_name or len(from_name) > MAX_PROJECT_NAME:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"原项目名称须为 1—{MAX_PROJECT_NAME} 个字。", field="from_name")
        if not to_name or len(to_name) > MAX_PROJECT_NAME:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"新项目名称须为 1—{MAX_PROJECT_NAME} 个字。", field="to_name")
        if from_name == to_name:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "新项目名称不能与原名称相同。", field="to_name")
        sync_service_costs = body.get("sync_service_costs", True)
        if not isinstance(sync_service_costs, bool):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "sync_service_costs 必须是布尔值。", field="sync_service_costs")

        company = self._registry.get_company(company_id)["company"]
        root = self._company_root(company)
        current = self._projects.load(root)
        if revision != current["revision"]:
            raise CompanyRegistryError("COMPANY_PROJECTS_CONFLICT", "项目归属已被修改，请刷新后重试。", status_code=409, field="revision")

        summary = self.company_projects(company_id, granularity="month", start="", end="")
        manual_count = sum(1 for item in summary["invoices"] if item["project"] == from_name and item["source"] == "manual")
        remark_count = sum(1 for item in summary["invoices"] if item["project"] == from_name and item["source"] == "remark")
        stored_manual_count = sum(
            1 for row in current["invoices"].values()
            if isinstance(row, dict) and row.get("unassigned") is not True and _clean_project_name(row.get("project")) == from_name
        )

        # Check linked manual service costs so renaming a project never silently splits service revenue and cost.
        service_state: dict | None = None
        service_cost_count = 0
        service_costs_revision: int | None = None
        if (root / SERVICE_COST_FILE).exists():
            try:
                loaded_service = read_company_state(root, SERVICE_COST_FILE, company_id, "costs")
                normalized_costs = normalize_costs(loaded_service["costs"])
                service_state = {**loaded_service, "costs": normalized_costs}
                service_costs_revision = int(loaded_service["revision"])
                service_cost_count = sum(1 for row in normalized_costs.values() if row["project"] == from_name)
            except (OSError, ValueError) as exc:
                raise CompanyRegistryError(
                    "COMPANY_PROJECTS_UNREADABLE",
                    f"关联的服务成本文件无法读取，未执行重命名：{exc}",
                    status_code=409,
                ) from exc

        known_projects = set(summary["project_names"])
        if from_name not in known_projects and stored_manual_count == 0 and service_cost_count == 0:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"未找到项目「{from_name}」。", field="from_name")

        merges_into_existing = to_name in known_projects
        preview_core = {
            "company_id": company_id,
            "revision": current["revision"],
            "from_name": from_name,
            "to_name": to_name,
            "manual_count": manual_count,
            "remark_count": remark_count,
            "stored_manual_count": stored_manual_count,
            "total_invoices": manual_count + remark_count,
            "merges_into_existing": merges_into_existing,
            "sync_service_costs": sync_service_costs,
            "service_cost_count": service_cost_count,
            "service_costs_revision": service_costs_revision,
        }
        preview_hash = hashlib.sha256(
            _json.dumps(preview_core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"ok": True, **preview_core, "preview_hash": preview_hash}, current, service_state, root

    def preview_project_rename(self, company_id: str, body: object) -> dict:
        preview, _current, _service_state, _root = self._compute_project_rename_preview(company_id, body)
        return preview

    def rename_project(self, company_id: str, body: object) -> dict:
        from datetime import datetime
        from invoice_hub.services.company_costs import PRICING_LOCK
        from invoice_hub.services.company_files import write_state
        from invoice_hub.services.cost_service_costs import SERVICE_COST_FILE
        from invoice_hub.storage import atomic_write_json

        if not isinstance(body, dict) or body.get("confirm") is not True:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "项目重命名需要明确确认。", field="confirm")
        expected_hash = str(body.get("preview_hash") or "").strip()
        if not expected_hash:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "缺少 preview_hash，请先预览影响。", field="preview_hash")
        expected_sc_rev = body.get("service_costs_revision")
        if expected_sc_rev is not None and (isinstance(expected_sc_rev, bool) or not isinstance(expected_sc_rev, int)):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "service_costs_revision 格式不正确。", field="service_costs_revision")

        # Lock order: PRICING_LOCK -> self._projects._lock to stay deadlock-free with cost reports.
        with PRICING_LOCK, self._projects._lock:
            preview, current, service_state, root = self._compute_project_rename_preview(company_id, body)
            if expected_sc_rev is not None and expected_sc_rev != preview["service_costs_revision"]:
                raise CompanyRegistryError("COMPANY_PROJECTS_CONFLICT", "关联的服务成本记录已变化，请重新预览。", status_code=409)
            if expected_hash != preview["preview_hash"]:
                raise CompanyRegistryError("COMPANY_PROJECTS_CONFLICT", "项目数据已变化，请重新预览后再确认重命名。", status_code=409)
            now = datetime.now().isoformat(timespec="seconds")
            updated_projects, manual_updated = self._projects.apply_rename(current, preview["from_name"], preview["to_name"], now)
            atomic_write_json(self._projects.path(root), updated_projects)

            service_costs_updated = 0
            if preview["sync_service_costs"] and service_state is not None and preview["service_cost_count"] > 0:
                next_costs = {}
                for rec_id, row in service_state["costs"].items():
                    if row["project"] == preview["from_name"]:
                        next_costs[rec_id] = {**row, "project": preview["to_name"]}
                        service_costs_updated += 1
                    else:
                        next_costs[rec_id] = row
                write_state(
                    root,
                    SERVICE_COST_FILE,
                    {
                        "version": 1,
                        "revision": service_state["revision"] + 1,
                        "company_id": company_id,
                        "costs": next_costs,
                    },
                )

            return {
                "ok": True,
                "from_name": preview["from_name"],
                "to_name": preview["to_name"],
                "assignments_revision": updated_projects["revision"],
                "manual_updated": manual_updated,
                "remark_count": preview["remark_count"],
                "merges_into_existing": preview["merges_into_existing"],
                "service_costs_updated": service_costs_updated,
            }

    # ---- voucher draft review (WS-05 stage 1): the CLI's review workbook in 做账草稿/, edited in place.
    def cost_tax_profile(self, company_id: str, month: str = "") -> dict:
        from invoice_hub.projections.cost_analysis import effective_tax_profile, reference_tax_profile_from_status
        from invoice_hub.projections.costs import _read_reference_status_payload
        from invoice_hub.targets.companies import taxpayer_type_for, current_month

        company = self._registry.get_company(company_id)["company"]
        subdir, profile = self._directory(company, "cost_invoice_dir")
        status_path = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), "成本开票状态.json")
        # A read-only identity lookup must not adopt another company's status through a
        # replaced directory or state-file link. The registry's availability is authoritative.
        if subdir["status"] != "present" or status_path.is_symlink():
            raise CompanyRegistryError("COMPANY_DIRECTORY_UNAVAILABLE", "本公司成本目录或状态文件不可用，请核对资料夹。", status_code=409)
        selected_month = month or current_month()
        taxpayer_type = taxpayer_type_for(company["taxpayer_periods"], selected_month)
        saved = reference_tax_profile_from_status(_read_reference_status_payload(status_path))
        effective = effective_tax_profile(saved, {
            "company_id": company_id, "company_name": company["name"], "month": selected_month,
            "taxpayer_type": taxpayer_type,
        })
        # Historical context is a read-only lookup, not a workbook rewrite or a second target.
        payload = effective.api_payload()
        payload.update(company_id=company_id, month=selected_month,
                       source="company" if taxpayer_type else "fallback")
        return {"ok": True, **payload}

    def voucher_drafts(self, company_id: str) -> dict:
        company = self._registry.get_company(company_id)["company"]
        root = self._company_root(company)
        return {"ok": True, **company_vouchers.draft_index(root), "inputs": company_vouchers.draft_inputs(root),
                **company_vouchers.export_formats(root)}

    @staticmethod
    def _voucher_bank_dir(company: dict) -> Path:
        # Use the registry's bank mapping just like the workspace ledger; a renamed
        # subfolder must not silently send generation back to the old standard path.
        subdir = next(item for item in company["subdirs"] if item["key"] == "bank_flow_dir")
        if subdir["status"] != "present":
            raise company_vouchers.VoucherDraftError("VOUCHER_DRAFT_INVALID", "银行流水目录不可用，请核对公司目录映射。")
        return Path(subdir["path"])

    def _voucher_invoice_inputs(self, company: dict) -> dict:
        subdir, profile = self._directory(company, "cost_invoice_dir")
        if subdir["status"] != "present":
            return {}
        workspace, source = Path(profile.workspace_dir), Path(profile.watch_dir)
        manifest = generations.current(workspace, source)
        path = generations.resolve(workspace, source, "成本发票明细.csv", manifest)
        # The immutable CSV lives in the workspace generation, but its company
        # catalog remains in the mapped source. Pass them together, never guess
        # a catalog from the generation's parent or another company's active target.
        return {"invoice_csv": path, "reference_status": source / "成本开票状态.json"} if manifest or path.is_file() else {}

    def _voucher_invoice_csv(self, company: dict) -> Path | None:
        return self._voucher_invoice_inputs(company).get("invoice_csv")

    def generate_voucher_draft(self, company_id: str, body: object) -> dict:
        # Only on the user's confirm: writes 做账草稿/ the way `voucher_cli draft` does, backing up an existing table.
        company = self._registry.get_company(company_id)["company"]
        if not isinstance(body, dict):
            raise company_vouchers.VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
        return {"ok": True, **company_vouchers.generate_draft(self._company_root(company), body, bank_dir=self._voucher_bank_dir(company),
                                                            **self._voucher_invoice_inputs(company))}

    def voucher_draft(self, company_id: str, name: str) -> dict:
        company = self._registry.get_company(company_id)["company"]
        return {"ok": True, **company_vouchers.read_draft(self._company_root(company), name, invoice_csv=self._voucher_invoice_csv(company))}

    def save_voucher_draft(self, company_id: str, name: str, body: object) -> dict:
        # Written only on the user's explicit save, into the workbook the export command reads.
        company = self._registry.get_company(company_id)["company"]
        if not isinstance(body, dict):
            raise company_vouchers.VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
        return {"ok": True, **company_vouchers.save_draft(self._company_root(company), name, body, invoice_csv=self._voucher_invoice_csv(company))}

    # ---- 工资社保 (WS-05 stage 3): read-only parsing; 申报数据.json is written only on the user's confirm.
    def payroll(self, company_id: str, *, reveal: bool = False) -> dict:
        company = self._registry.get_company(company_id)["company"]
        root = self._company_root(company)
        subdir = next((item for item in company["subdirs"] if item["key"] == "payroll_social_dir"), None)
        folder = Path(subdir["path"]) if subdir and subdir["status"] == "present" else None
        return {"ok": True, "folder": subdir["relative_path"] if subdir else "", "folder_present": folder is not None,
                **read_payroll(root, folder, reveal=reveal)}

    def save_payroll(self, company_id: str, body: object) -> dict:
        company = self._registry.get_company(company_id)["company"]
        if not isinstance(body, dict):
            raise CompanyRegistryError("PAYROLL_INVALID", "请求格式不对。")
        return {"ok": True, **save_payroll_months(self._company_root(company), body)}

    # ---- period folders (WS-05 stage 2): content period vs. folder name, and confirmed moves.
    def _present_subdir(self, company_id: str, key: str) -> tuple[dict, Path]:
        company = self._registry.get_company(company_id)["company"]
        subdir, _profile = self._directory(company, key)
        if subdir["status"] != "present":
            raise CompanyRegistryError("COMPANY_DIRECTORY_MISSING", "这个子目录不存在或不可用。", status_code=409)
        return company, Path(subdir["path"])

    def period_folders(self, company_id: str, key: str) -> dict:
        _company, root = self._present_subdir(company_id, key)
        return {"ok": True, **period_folder_check(root, key)}

    def prepare_source_move(self, company_id: str, body: object) -> dict:
        if not isinstance(body, dict):
            raise CompanyRegistryError("SOURCE_MOVE_INVALID", "请求格式不对。")
        key = str(body.get("key") or "")
        _company, root = self._present_subdir(company_id, key)
        job = self._moves.prepare(company_id=company_id, key=key, root=root, items=body.get("items"),
                                  guard=Path(self.active_profile.watch_dir))
        return {"ok": True, **self._moves.public(job)}

    def confirm_source_move(self, company_id: str, job_id: str, body: object) -> dict:
        confirmed = body.get("confirmed") if isinstance(body, dict) else None
        job = self._moves.commit(job_id, company_id=company_id, confirmed=confirmed)
        return {"ok": True, **self._moves.public(job)}

    def source_move(self, company_id: str, job_id: str) -> dict:
        job = self._moves.get(job_id)
        if job["company_id"] != company_id:
            raise CompanyRegistryError("SOURCE_MOVE_INVALID", "移动记录不属于这家公司。", status_code=404)
        return {"ok": True, **self._moves.public(job)}

    def rebook_voucher_invoice(self, company_id: str, name: str, body: object) -> dict:
        # Corrects where an invoice is booked (generated data, 做账草稿/记入期调整.json), then regenerates; no source file moves.
        company = self._registry.get_company(company_id)["company"]
        if not isinstance(body, dict):
            raise company_vouchers.VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
        return {"ok": True, **company_vouchers.rebook_invoice(self._company_root(company), name, body, bank_dir=self._voucher_bank_dir(company),
                                                            **self._voucher_invoice_inputs(company))}

    def export_voucher_draft(self, company_id: str, name: str, body: object) -> dict:
        # Only on the user's confirm; files go to the company folder's 做账草稿/, for manual import into the books.
        company = self._registry.get_company(company_id)["company"]
        if not isinstance(body, dict):
            raise company_vouchers.VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
        from invoice_hub.services.company_export_jobs import run_export_job
        return {"ok": True, **run_export_job(self._company_root(company), name, body)}

    def voucher_export_job(self, company_id: str, name: str, token: str) -> dict:
        from invoice_hub.services.company_export_jobs import get_export_job
        company = self._registry.get_company(company_id)["company"]
        return {"ok": True, **get_export_job(self._company_root(company), name, token)}

    def invoice_tags(self, *, include_usage: bool = False) -> dict:
        with self._lock:
            result = {"ok": True, **self._tags.definitions()}
            if not include_usage:
                return result
            numbers = {tag["id"]: set() for tag in result["tags"]}
            unavailable = []
            for company in self._registry.list_companies()["companies"]:
                try:
                    root = self._company_root(company)
                    marks = self._tags.visible_marks(root)
                except (CompanyRegistryError, OSError):
                    unavailable.append({"id": company["id"], "name": company["name"]})
                    continue
                for number, ids in marks.items():
                    for tag_id in ids:
                        if tag_id in numbers:
                            numbers[tag_id].add(number)
            # Numbers are global across registered folders. Offline folders make this a
            # known subtotal, never evidence that an otherwise unseen tag has zero uses.
            result.update(usage={key: len(value) for key, value in numbers.items()},
                          usage_unavailable=unavailable, usage_complete=not unavailable)
            return result

    def save_invoice_tags(self, body: object) -> dict:
        _saved, removed = self._tags.save_definitions(body)
        purged, failed = 0, []
        if removed:
            # A deleted tag disappears from every company folder; offline folders are listed and
            # their stale marks stay hidden because reads ignore unknown tag ids.
            for company in self._registry.list_companies()["companies"]:
                if company.get("root_status") != "present":
                    failed.append(company["name"])
                    continue
                try:
                    purged += int(self._tags.purge(Path(company["root_path"]), removed))
                except (CompanyRegistryError, OSError):
                    failed.append(company["name"])
        return {**self.invoice_tags(include_usage=True), "purged_companies": purged, "purge_failed": failed}

    def company_invoice_tags(self, company_id: str) -> dict:
        company = self._registry.get_company(company_id)["company"]
        root = self._company_root(company)
        return {"ok": True, "revision": self._tags.marks(root)["revision"], "invoices": self._tags.visible_marks(root)}

    def save_company_invoice_tags(self, company_id: str, body: object) -> dict:
        company = self._registry.get_company(company_id)["company"]
        root = self._company_root(company)
        saved = self._tags.save_marks(root, body)
        return {"ok": True, "revision": saved["revision"], "invoices": self._tags.visible_marks(root)}

    def _cost_service(self, profile: TargetProfile) -> CostProjectionService:
        return CostProjectionService(
            Path(profile.watch_dir), Path(profile.workspace_dir), profile.id,
            reference_markup_rate=self.config.reference_markup_rate,
            company_taxpayer=lambda: company_taxpayer_for(self.config, Path(profile.watch_dir)),
            company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
        )

    def _bank_ledger(self, company: dict, *, granularity: str, start: str, end: str) -> dict:
        # Bank figures sit beside the invoice ledger, not inside it: its checks_ok stays about
        # invoices, and a bank folder that cannot be read never hides the invoice totals.
        subdir = next(item for item in company["subdirs"] if item["key"] == "bank_flow_dir")
        base = {"path": subdir["path"], "status": subdir["status"]}
        if subdir["status"] != "present":
            return {**base, "state": "missing_dir", "message": FRESHNESS_MESSAGES["missing_dir"]}
        read = self._bank_reader.read(Path(subdir["path"]))
        base.update(file_count=read.file_count, cached=read.cached)
        if read.data is None:
            return {**base, "state": "unreadable", "message": read.error}
        if not read.data.statements:
            return {**base, "state": "no_statements", "message": "没有可识别的银行对账单（目前支持中国银行 PDF）。",
                    **build_bank_ledger(read.data, granularity=granularity, start=start, end=end)}
        return {**base, "state": "ok", "message": "",
                **build_bank_ledger(read.data, granularity=granularity, start=start, end=end)}
