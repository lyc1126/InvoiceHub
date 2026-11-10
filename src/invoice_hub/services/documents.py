"""Inbound/outbound document use cases: defaults, catalog state, previews, export and open.

Split out of ``AppState`` (ENG-03); routes call it as ``state.documents`` (ENG-08).

What arrives as a callback: the active TargetProfile (owned by AppState), the cost detail
path and the configured outbound directory (settings own its persistence); homepage
selections are rechecked through ``InvoiceSelectionService``. Each is read on every call, never captured,
because watch_dir/outbound switches replace them and a stale value would export documents
for the previous directory. Writers take AppState's own RLock, so exports stay serialised
with directory switches.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.platform import open_local_path
from invoice_hub.projections.documents import (
    DocumentError,
    build_inbound_preview,
    build_outbound_preview,
    clean_document_defaults,
    inbound_export_path,
    merge_document_defaults,
    outbound_export_path,
    write_inbound_workbook,
    write_outbound_workbook,
)
from invoice_hub.services.document_index import DocumentIndex, InboundDetails
from invoice_hub.services.errors import StaleInvoiceSelectionError
from invoice_hub.services.invoice_selection import InvoiceSelectionService, selection_family_key
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_json_object
from invoice_hub.storage.read_views import file_signature
from invoice_hub.targets.paths import path_is_under_root


class DocumentService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        document_index: DocumentIndex,
        inbound_details: InboundDetails,
        defaults_path: Path,
        active_profile: Callable[[], TargetProfile],
        cost_detail_csv: Callable[[], Path],
        outbound_dir: Callable[[], str],
        recent_outbound_dirs: Callable[[], list[str]],
        selection: InvoiceSelectionService,
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._document_index = document_index
        self._inbound_details = inbound_details
        # Server-produced filename metadata keyed by (target, outbound dir, number); see
        # outbound_document_export_status for why only unchanged sources may reuse it.
        self._outbound_preview_metadata: dict = {}
        self._defaults_path = defaults_path
        self._active_profile = active_profile
        self._cost_detail_csv = cost_detail_csv
        self._outbound_dir = outbound_dir
        self._recent_outbound_dirs = recent_outbound_dirs
        self._selection = selection

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def _document_defaults_path(self) -> Path:
        return self._defaults_path

    def document_defaults(self) -> dict[str, dict[str, str]]:
        return clean_document_defaults(read_json_object(self._document_defaults_path(), {}))

    def save_document_defaults(self, payload: dict | None) -> dict:
        with self._lock:
            defaults = merge_document_defaults(self.document_defaults(), payload or {})
            atomic_write_json(self._document_defaults_path(), defaults)
            self.append_event("documents.defaults_updated", {"target_id": self.active_profile.id})
        return {"ok": True, "defaults": defaults, "defaults_path": str(self._document_defaults_path())}

    def document_state(self, *, restart: bool = False, revalidate: bool = True, selection_only: bool = False) -> dict:
        with self._lock:
            return self._document_state_locked(restart=restart, revalidate=revalidate, selection_only=selection_only)

    def _document_state_locked(self, *, restart: bool, revalidate: bool, selection_only: bool = False) -> dict:
        defaults = self.document_defaults()
        outbound_dir = self._outbound_dir()
        profile = self.active_profile.model_copy(deep=True)
        detail = Path(profile.watch_dir) / "成本发票明细.csv"
        # A homepage selection already identifies its invoices. Do not start an
        # unrelated outbound scan merely to obtain defaults and directory identity.
        catalog = ({"index": {"state": "idle"}, "inbound_invoices": [], "outbound_invoices": []}
                   if selection_only else self._document_index.ensure(profile.id, outbound_dir, detail, restart=restart, revalidate=revalidate))
        return {
            "ok": True,
            "watch_dir": profile.watch_dir,
            "target_id": profile.id,
            "cost_detail_csv_path": str(detail),
            "cost_detail_exists": detail.exists(),
            "selection_only": selection_only,
            "defaults": defaults,
            "outbound_invoice_dir": outbound_dir,
            "outbound_dir_validation": self.inspect_document_dir(Path(outbound_dir)) if outbound_dir else self.inspect_document_dir(None),
            "recent_outbound_invoice_dirs": self._recent_outbound_dirs(),
            **catalog,
        }

    def inspect_document_dir(self, directory: Path | None) -> dict:
        if directory is None or not str(directory):
            return {
                "ok": True,
                "path": "",
                "exists": False,
                "is_dir": False,
                "readable": False,
                "supported_count": 0,
                "can_use": False,
                "summary": "尚未保存开具发票目录。",
            }
        path = Path(directory)
        exists = path.exists()
        is_dir = path.is_dir()
        supported_count = 0
        if exists and is_dir:
            try:
                # Directory picking/saving only validates access. Recursive discovery
                # belongs to the cancellable index process, never the API event loop.
                with os.scandir(path) as entries:
                    next(entries, None)
                supported_count = None
                readable = True
            except OSError:
                readable = False
        else:
            readable = False
        can_use = bool(exists and is_dir and readable)
        if can_use:
            summary = "目录可用，文件数量由后台加载统计。"
        elif not exists:
            summary = "目录不存在。"
        elif not is_dir:
            summary = "路径不是文件夹。"
        else:
            summary = "目录不可读取，请检查权限。"
        return {
            "ok": True,
            "path": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "readable": readable,
            "supported_count": supported_count,
            "can_use": can_use,
            "summary": summary,
        }

    def _document_defaults_from_payload(self, payload: dict | None) -> dict:
        return payload.get("defaults") if isinstance((payload or {}).get("defaults"), dict) else {}

    def _validated_inbound_selection(self, payload: dict) -> dict[str, list[dict]]:
        if not isinstance(payload, dict) or not payload.get("target_id"):
            raise DocumentError("缺少当前发票目录标识，请返回首页重新勾选。")
        if payload["target_id"] != self.active_profile.id:
            raise StaleInvoiceSelectionError("发票目录已切换，请返回首页重新勾选。")
        _, selected = self._selection.validated_invoice_selection(payload, max_items=1000, operation="开具入库单")
        root = Path(self.active_profile.watch_dir).resolve()
        grouped: dict[str, list[dict]] = {}
        for item in selected:
            source = Path(item.get("source_path") or item.get("file_path") or "").resolve()
            if not source.is_relative_to(root) or not source.is_file():
                raise StaleInvoiceSelectionError("勾选源文件已移除或超出当前目录，请重新勾选。")
            grouped.setdefault(selection_family_key(item), []).append(item)
        return grouped

    def document_inbound_selection(self, payload: dict) -> dict:
        # The homepage handoff is only a draft. Recheck identities in the current target
        # here and again at export, so a directory switch cannot export another invoice.
        with self._lock:
            grouped = self._validated_inbound_selection(payload)
            numbers = [family.removeprefix("number:") for family in grouped if family.startswith("number:")]
            options = {item["invoice_number"]: item for item in self._inbound_details.read(self._cost_detail_csv(), numbers)}
            entries = []
            root = Path(self.active_profile.watch_dir) / "入库单"
            for family, items in grouped.items():
                number = family.removeprefix("number:") if family.startswith("number:") else ""
                option = options.get(number)
                entry = {
                    "invoice_number": number,
                    "seller": items[0].get("seller") or "",
                    "ready": bool(option) and not option.get("blocked", False),
                    "message": option.get("message", "") if option else ("未找到成本明细，请重新汇总后重试。" if number else "未识别发票号码，无法开具入库单。"),
                    "selection": {"target_id": self.active_profile.id, "items": [
                        {"invoice_key": item["invoice_key"], "source_path": item.get("source_path") or item.get("file_path")}
                        for item in items
                    ]},
                }
                if option:
                    entry.update(option)
                    path = inbound_export_path(Path(self.active_profile.watch_dir), option)
                    status = self._document_export_status(path, root)
                    entry["export_status"] = status
                    if not status["ok"] or not root.resolve().is_relative_to(Path(self.active_profile.watch_dir).resolve()):
                        entry.update(ready=False, message="入库单输出目录超出当前发票目录。")
                entries.append(entry)
            return {"ok": True, "target_id": self.active_profile.id, "items": entries,
                    "record_count": sum(len(items) for items in grouped.values()), "invoice_count": len(entries)}

    def document_inbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        merged_defaults = merge_document_defaults(self.document_defaults(), {"inbound": (defaults or {})})
        return build_inbound_preview(self._inbound_details.invoice_rows(self._cost_detail_csv(), invoice_number.strip()), invoice_number, merged_defaults)

    def document_outbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        outbound_dir = self._outbound_dir()
        if not outbound_dir:
            raise DocumentError("请先保存开具发票目录")
        merged_defaults = merge_document_defaults(self.document_defaults(), {"outbound": (defaults or {})})
        catalog = self.document_state(revalidate=False)
        option = next((item for item in catalog["outbound_invoices"] if item["invoice_number"] == invoice_number), None)
        if option is None:
            raise KeyError(invoice_number)
        fingerprint = [(path, file_signature(path)) for path in option["source_files"]]
        preview = build_outbound_preview(Path(outbound_dir), invoice_number, merged_defaults,
                                         source_files=[Path(path) for path in option["source_files"]])
        preview["provisional"] = catalog["index"]["state"] != "ready"
        if fingerprint != [(path, file_signature(path)) for path in option["source_files"]]:
            raise DocumentError("源发票在预览期间发生变化，请重新预览。")
        key = (self.active_profile.id, outbound_dir, invoice_number)
        with self._lock:
            if len(self._outbound_preview_metadata) >= 128:
                self._outbound_preview_metadata.clear()
            self._outbound_preview_metadata[key] = (fingerprint, {"invoice_number": preview["invoice_number"], "invoice_date": preview["invoice_date"]})
        return preview

    def _inbound_document_target(self, payload: dict | None = None, include_defaults: bool = True) -> tuple[str, dict, Path, Path]:
        payload = payload or {}
        invoice_number = str(payload.get("invoice_number") or "").strip()
        defaults = self._document_defaults_from_payload(payload) if include_defaults else {}
        preview = self.document_inbound_preview(invoice_number, defaults)
        path = inbound_export_path(Path(self.active_profile.watch_dir), preview)
        root = (Path(self.active_profile.watch_dir) / "入库单").resolve()
        return invoice_number, preview, path, root

    def _outbound_document_target(self, payload: dict | None = None, include_defaults: bool = True) -> tuple[str, dict, Path, Path]:
        payload = payload or {}
        invoice_number = str(payload.get("invoice_number") or "").strip()
        defaults = self._document_defaults_from_payload(payload) if include_defaults else {}
        preview = self.document_outbound_preview(invoice_number, defaults)
        outbound_dir = Path(self._outbound_dir())
        path = outbound_export_path(outbound_dir, preview)
        root = (outbound_dir / "出库单").resolve()
        return invoice_number, preview, path, root

    @staticmethod
    def _document_path_occupied(path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        try:
            with path.open("a+b"):
                return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _document_export_status(self, path: Path, root: Path) -> dict:
        resolved = Path(path).resolve()
        folder = resolved.parent
        if not path_is_under_root(resolved, root):
            return {"ok": False, "exists": False, "occupied": False, "path": str(resolved), "folder_path": str(folder), "message": "单据路径超出允许目录"}
        exists = resolved.exists() and resolved.is_file()
        occupied = self._document_path_occupied(resolved) if exists else False
        return {
            "ok": True,
            "exists": exists,
            "occupied": occupied,
            "path": str(resolved),
            "file_path": str(resolved),
            "file_name": resolved.name,
            "folder_path": str(folder),
            "message": "文件被占用，请关闭后再操作。" if occupied else ("单据已导出。" if exists else "单据尚未导出。"),
        }

    def inbound_document_export_status(self, payload: dict | None = None) -> dict:
        invoice_number = str((payload or {}).get("invoice_number") or "").strip()
        options = self._inbound_details.read(self._cost_detail_csv(), [invoice_number])
        if not options:
            raise KeyError(invoice_number)
        if options[0].get("blocked"):
            raise DocumentError(options[0]["message"])
        root = Path(self.active_profile.watch_dir) / "入库单"
        rows = self._inbound_details.invoice_rows(self._cost_detail_csv(), invoice_number)
        path = inbound_export_path(Path(self.active_profile.watch_dir), {"invoice_number": invoice_number, "invoice_date": rows[0].get("开票日期", "")})
        status = self._document_export_status(path, root)
        status["invoice_number"] = invoice_number
        return status

    def outbound_document_export_status(self, payload: dict | None = None) -> dict:
        invoice_number = str((payload or {}).get("invoice_number") or "").strip()
        catalog = self.document_state(revalidate=False)
        option = next((item for item in catalog["outbound_invoices"] if item["invoice_number"] == invoice_number), None)
        if option is None:
            raise KeyError(invoice_number)
        directory = Path(self._outbound_dir()).resolve()
        if any(not Path(source).resolve().is_relative_to(directory) or not Path(source).is_file() for source in option["source_files"]):
            raise DocumentError("源文件已移除或超出开具目录，请刷新列表。")
        root = directory / "出库单"
        fingerprint = [(source, file_signature(source)) for source in option["source_files"]]
        key = (self.active_profile.id, self._outbound_dir(), invoice_number)
        cached = self._outbound_preview_metadata.get(key)
        # Reuse only server-produced filename metadata from unchanged sources. A
        # direct status request or changed source must establish that metadata first.
        metadata = cached[1] if cached and cached[0] == fingerprint else self.document_outbound_preview(invoice_number)
        path = outbound_export_path(directory, metadata)
        status = self._document_export_status(path, root)
        status["invoice_number"] = invoice_number
        return status

    @staticmethod
    def _copy_export_path(path: Path) -> Path:
        stem = path.stem
        suffix = path.suffix
        index = 1
        while True:
            candidate = path.with_name(f"{stem}-副本{index}{suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    def export_inbound_document(self, payload: dict | None = None) -> dict:
        with self._lock:
            return self._export_inbound_document_locked(payload)

    def _export_inbound_document_locked(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        if "selection" in payload:
            grouped = self._validated_inbound_selection(payload["selection"])
            if list(grouped) != [f"number:{str(payload.get('invoice_number') or '').strip()}"]:
                raise StaleInvoiceSelectionError("入库单与勾选发票不一致，请重新核对。")
            if payload.get("mode") not in {"skip_existing", "copy_existing"}:
                raise DocumentError("批量导出必须明确选择跳过已有文件或导出副本。")
        invoice_number, preview, path, root = self._inbound_document_target(payload)
        mode = str(payload.get("mode") or "").strip().casefold()
        status = self._document_export_status(path, root)
        if not status["ok"] or not root.is_relative_to(Path(self.active_profile.watch_dir).resolve()):
            raise DocumentError("入库单输出目录超出当前发票目录。")
        if mode == "skip_existing" and status["exists"]:
            return {**status, "skipped": True, "exported": False, "invoice_number": invoice_number}
        if status.get("occupied"):
            return {**status, "ok": False, "exported": False, "invoice_number": invoice_number}
        original_path = path
        copy_requested = mode in {"copy", "duplicate", "副本"} or (mode == "copy_existing" and status["exists"])
        if copy_requested:
            if not status.get("exists"):
                return {**status, "ok": False, "exported": False, "invoice_number": invoice_number, "message": f"文件已经被删除或尚未导出: {path}"}
            path = self._copy_export_path(path)
        try:
            write_inbound_workbook(preview, path)
        except PermissionError:
            return {**self._document_export_status(original_path, root), "ok": False, "exported": False, "occupied": True, "invoice_number": invoice_number, "message": "文件被占用，请关闭后再操作。"}
        self.append_event("documents.inbound_exported", {"invoice_number": invoice_number, "path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "exported": True, "invoice_number": invoice_number, "path": str(path), "file_path": str(path), "file_name": path.name, "folder_path": str(path.parent), "copy": path != original_path, "preview": preview}

    def export_outbound_document(self, payload: dict | None = None) -> dict:
        with self._lock:
            return self._export_outbound_document_locked(payload)

    def _export_outbound_document_locked(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        invoice_number, preview, path, root = self._outbound_document_target(payload)
        if preview.get("provisional"):
            raise DocumentError("当前为临时预览，请等待出库目录核对完成后导出。")
        mode = str(payload.get("mode") or "").strip().casefold()
        status = self._document_export_status(path, root)
        if status.get("occupied"):
            return {**status, "ok": False, "exported": False, "invoice_number": invoice_number}
        original_path = path
        copy_requested = mode in {"copy", "duplicate", "副本"}
        if copy_requested:
            if not status.get("exists"):
                return {**status, "ok": False, "exported": False, "invoice_number": invoice_number, "message": f"文件已经被删除或尚未导出: {path}"}
            path = self._copy_export_path(path)
        try:
            write_outbound_workbook(preview, path)
        except PermissionError:
            return {**self._document_export_status(original_path, root), "ok": False, "exported": False, "occupied": True, "invoice_number": invoice_number, "message": "文件被占用，请关闭后再操作。"}
        self.append_event("documents.outbound_exported", {"invoice_number": invoice_number, "path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "exported": True, "invoice_number": invoice_number, "path": str(path), "file_path": str(path), "file_name": path.name, "folder_path": str(path.parent), "copy": path != original_path, "preview": preview}

    def open_inbound_document(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._inbound_document_target(payload, include_defaults=False)
        return self._open_exported_document(path, root, "documents.inbound_opened", invoice_number)

    def open_outbound_document(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._outbound_document_target(payload, include_defaults=False)
        return self._open_exported_document(path, root, "documents.outbound_opened", invoice_number)

    def open_inbound_document_location(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._inbound_document_target(payload, include_defaults=False)
        return self._open_exported_document_location(path, root, "documents.inbound_location_opened", invoice_number)

    def open_outbound_document_location(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._outbound_document_target(payload, include_defaults=False)
        return self._open_exported_document_location(path, root, "documents.outbound_location_opened", invoice_number)

    def _open_exported_document(self, path: Path, root: Path, event_type: str, invoice_number: str) -> dict:
        resolved = Path(path).resolve()
        if not path_is_under_root(resolved, root):
            return {"ok": False, "opened": False, "message": "单据路径超出允许目录"}
        if not resolved.exists() or not resolved.is_file():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(resolved.parent), "message": f"单据尚未导出: {resolved}"}
        if self._document_path_occupied(resolved):
            return {"ok": False, "opened": False, "occupied": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(resolved.parent), "message": "文件被占用，请关闭后再操作。"}
        open_local_path(resolved)
        self.append_event(event_type, {"invoice_number": invoice_number, "path": str(resolved), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "file_name": resolved.name, "folder_path": str(resolved.parent)}

    def _open_exported_document_location(self, path: Path, root: Path, event_type: str, invoice_number: str) -> dict:
        resolved = Path(path).resolve()
        if not path_is_under_root(resolved, root):
            return {"ok": False, "opened": False, "message": "单据路径超出允许目录"}
        if not resolved.exists() or not resolved.is_file():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(resolved.parent), "message": f"文件已经被删除或尚未导出: {resolved}"}
        if self._document_path_occupied(resolved):
            return {"ok": False, "opened": False, "occupied": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(resolved.parent), "message": "文件被占用，请关闭后再操作。"}
        folder = resolved.parent
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(folder), "message": f"文件夹不存在: {folder}"}
        open_local_path(folder)
        self.append_event(event_type, {"invoice_number": invoice_number, "path": str(resolved), "folder_path": str(folder), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(folder), "file_name": resolved.name}
