"""Invoice source preview and batch print orchestration for the active watch_dir.

Moved out of ``AppState`` (ENG-03) without behaviour changes; ``AppState`` keeps the public
method names and forwards here. Rendering, job storage and limits stay in
``FilePreviewService``/``InvoicePrintService``; this layer turns a homepage selection into
sources inside the current watch_dir and records events. Both services are created by
AppState and passed in, because AppState clears them on watch_dir switches and temporary
recognition shares the preview pool.

Selection identity rules (validation, invoice-family key, source identity, file format)
belong to the invoice list and stay in AppState; they arrive as callbacks. The active
profile is read on every call, and preview creation holds AppState's own RLock so a
directory switch cannot publish a job built from the previous watch_dir.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.platform import open_local_path
from invoice_hub.services.file_preview import (
    MAX_PREVIEW_SELECTION_RECORDS,
    PREVIEW_JOB_TTL_SECONDS,
    FilePreviewError,
    FilePreviewJob,
    FilePreviewService,
    FilePreviewSource,
)
from invoice_hub.services.invoice_printing import (
    MAX_PRINT_SELECTION_RECORDS,
    InvoicePrintError,
    InvoicePrintJob,
    InvoicePrintService,
    InvoicePrintSource,
)
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets.paths import path_is_under_root


class InvoicePreviewPrintService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        preview_service: FilePreviewService,
        print_service: InvoicePrintService,
        active_profile: Callable[[], TargetProfile],
        validate_selection: Callable[..., tuple[dict, list[dict]]],
        family_key: Callable[[dict], str],
        source_identity: Callable[[object], str],
        file_format: Callable[..., str],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._file_preview_service = preview_service
        self._invoice_print_service = print_service
        self._active_profile = active_profile
        self._validate_selection = validate_selection
        self._family_key = family_key
        self._source_identity = source_identity
        self._file_format = file_format

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    @staticmethod
    def _invoice_print_label(items: list[dict], fallback_index: int) -> str:
        for item in items:
            invoice_number = str(item.get("invoice_number") or "").strip()
            if invoice_number:
                return f"发票 {invoice_number}"
        for item in items:
            file_name = str(item.get("file_name") or item.get("source_file") or "").strip()
            if file_name:
                return file_name
        return f"第 {fallback_index} 张发票"

    def _print_pdf_path(self, item: dict) -> Path | None:
        source_text = str(item.get("source_path") or item.get("file_path") or "").strip()
        if not source_text or self._file_format("", source_text) != "pdf":
            return None
        source = Path(source_text).expanduser()
        if not source.is_absolute():
            source = Path(self.active_profile.watch_dir) / source
        try:
            resolved = source.resolve(strict=False)
            resolved.relative_to(Path(self.active_profile.watch_dir).resolve())
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    @staticmethod
    def _invoice_print_error_message(issues: list[str]) -> str:
        visible = issues[:6]
        suffix = f"；另有 {len(issues) - len(visible)} 张" if len(issues) > len(visible) else ""
        return "本次打印未开始。" + "；".join(visible) + suffix

    @staticmethod
    def _invoice_print_payload(job: InvoicePrintJob) -> dict:
        return {
            "ok": True,
            "job_id": job.job_id,
            "print_url": f"/invoices/print/{job.job_id}",
            "record_count": job.record_count,
            "invoice_count": job.invoice_count,
            "collapsed_record_count": job.collapsed_record_count,
            "format_fallback_count": job.format_fallback_count,
            "source_file_count": job.invoice_count,
            "page_count": len(job.pages),
            "created_at": job.created_at,
            "expires_at": job.expires_at,
            "pages": [
                {
                    "page_number": page_number,
                    "image_url": f"/api/v1/invoices/print-jobs/{job.job_id}/pages/{page_number}",
                    "orientation": page.orientation,
                    "invoice_index": page.invoice_index,
                    "source_page_number": page.source_page_number,
                }
                for page_number, page in enumerate(job.pages, start=1)
            ],
        }

    def prepare_invoice_print(self, payload: dict) -> dict:
        current_payload, selected_items = self._validate_selection(
            payload,
            max_items=MAX_PRINT_SELECTION_RECORDS,
            operation="打印",
        )
        selected_families: dict[str, list[dict]] = {}
        for item in selected_items:
            selected_families.setdefault(self._family_key(item), []).append(item)
        current_families: dict[str, list[dict]] = {}
        for item in current_payload["items"]:
            current_families.setdefault(self._family_key(item), []).append(item)

        sources: list[InvoicePrintSource] = []
        issues: list[str] = []
        format_fallback_count = 0
        used_paths: set[str] = set()
        for family_index, (family_key, family_items) in enumerate(selected_families.items(), start=1):
            selected_pdf_items = [
                item
                for item in family_items
                if self._file_format(
                    str(item.get("source_file") or item.get("file_name") or ""),
                    str(item.get("source_path") or item.get("file_path") or ""),
                )
                == "pdf"
            ]
            all_pdf_items = [
                item
                for item in current_families.get(family_key, [])
                if self._file_format(
                    str(item.get("source_file") or item.get("file_name") or ""),
                    str(item.get("source_path") or item.get("file_path") or ""),
                )
                == "pdf"
            ]
            candidates: list[dict] = []
            candidate_identities: set[str] = set()
            for candidate in [*selected_pdf_items, *all_pdf_items]:
                identity = self._source_identity(candidate.get("source_path") or candidate.get("file_path"))
                if identity and identity not in candidate_identities:
                    candidate_identities.add(identity)
                    candidates.append(candidate)

            chosen_item = None
            chosen_path = None
            for candidate in candidates:
                candidate_path = self._print_pdf_path(candidate)
                if candidate_path is not None:
                    chosen_item = candidate
                    chosen_path = candidate_path
                    break
            label = self._invoice_print_label(family_items, family_index)
            if chosen_path is None:
                if candidates:
                    issues.append(f"{label} 的 PDF 已移动、删除或不在当前发票目录")
                else:
                    issues.append(f"{label} 仅有 OFD/XML，且同票家族没有可用 PDF")
                continue
            path_identity = self._source_identity(chosen_path)
            if path_identity in used_paths:
                continue
            used_paths.add(path_identity)
            selected_pdf_identities = {
                self._source_identity(item.get("source_path") or item.get("file_path"))
                for item in selected_pdf_items
            }
            if self._source_identity(chosen_item.get("source_path") or chosen_item.get("file_path")) not in selected_pdf_identities:
                format_fallback_count += 1
            sources.append(InvoicePrintSource(path=chosen_path, label=label))

        if issues:
            error = InvoicePrintError(
                self._invoice_print_error_message(issues),
                code="unprintable_selection",
            )
            self.append_event(
                "invoice.print_job_failed",
                {"code": error.code, "record_count": len(selected_items), "issue_count": len(issues)},
                error={"message": str(error)},
            )
            raise error

        try:
            job = self._invoice_print_service.create_job(
                sources,
                record_count=len(selected_items),
                invoice_count=len(selected_families),
                collapsed_record_count=len(selected_items) - len(selected_families),
                format_fallback_count=format_fallback_count,
            )
        except InvoicePrintError as exc:
            self.append_event(
                "invoice.print_job_failed",
                {"code": exc.code, "record_count": len(selected_items), "invoice_count": len(selected_families)},
                error={"message": str(exc)},
            )
            raise
        self.append_event(
            "invoice.print_job_created",
            {
                "job_id": job.job_id,
                "record_count": job.record_count,
                "invoice_count": job.invoice_count,
                "page_count": len(job.pages),
                "format_fallback_count": job.format_fallback_count,
            },
        )
        return self._invoice_print_payload(job)

    def invoice_print_job(self, job_id: str, *, record_open: bool = False) -> dict:
        job = self._invoice_print_service.get_job(job_id)
        if record_open:
            self.append_event(
                "invoice.print_page_opened",
                {"job_id": job.job_id, "invoice_count": job.invoice_count, "page_count": len(job.pages)},
            )
        return self._invoice_print_payload(job)

    def invoice_print_page(self, job_id: str, page_number: int):
        return self._invoice_print_service.get_page(job_id, page_number)

    def _invoice_preview_source(self, item: dict) -> FilePreviewSource:
        source_text = str(item.get("source_path") or item.get("file_path") or "").strip()
        if not source_text:
            raise FilePreviewError(
                "源文件路径已失效，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        source = Path(source_text).expanduser()
        root = Path(self.active_profile.watch_dir).resolve()
        if not source.is_absolute():
            source = root / source
        try:
            resolved = source.resolve()
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError(
                "源文件路径已失效，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            ) from exc
        if not path_is_under_root(resolved, root) or not resolved.is_file():
            raise FilePreviewError(
                "源文件已移动、删除或不在当前发票目录，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        return FilePreviewSource(path=resolved, display_name=resolved.relative_to(root).as_posix())

    @staticmethod
    def _invoice_preview_payload(job: FilePreviewJob) -> dict:
        files = []
        for item in job.files:
            base_url = f"/api/v1/invoices/preview-jobs/{job.job_id}/files/{item.file_number}"
            files.append(
                {
                    "file_number": item.file_number,
                    "name": item.display_name,
                    "file_name": item.file_name,
                    "extension": item.extension,
                    "size_bytes": item.size,
                    "modified_at": item.modified_at,
                    "preview_type": item.preview_type,
                    "page_count": item.page_count,
                    "reason": item.reason,
                    "error_code": item.error_code,
                    "text_truncated": item.text_truncated,
                    "page_url_template": f"{base_url}/pages/{{page_number}}" if item.preview_type == "pages" else "",
                    "text_url": f"{base_url}/text" if item.preview_type == "text" else "",
                    "open_file_url": f"{base_url}/open-file",
                    "open_location_url": f"{base_url}/open-location",
                }
            )
        return {
            "ok": True,
            "job_id": job.job_id,
            "record_count": job.record_count,
            "file_count": len(job.files),
            "renderable_page_count": job.renderable_page_count,
            "created_at": job.created_at,
            "expires_at": job.expires_at,
            "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS,
            "keep_alive_url": f"/api/v1/invoices/preview-jobs/{job.job_id}/keep-alive",
            "files": files,
        }

    def prepare_invoice_preview(self, payload: dict) -> dict:
        # Keep captured target, source validation and the published result in one directory generation.
        with self._lock:
            _current_payload, selected_items = self._validate_selection(
                payload,
                max_items=MAX_PREVIEW_SELECTION_RECORDS,
                operation="预览",
            )
            # Preview preserves every selected source record and its order; invoice-family
            # collapsing belongs to totals and printing, not to source-file inspection.
            sources = [self._invoice_preview_source(item) for item in selected_items]
            try:
                job = self._file_preview_service.create_job(sources)
            except FilePreviewError as exc:
                self.append_event(
                    "invoice.preview_job_failed",
                    {"code": exc.code, "record_count": len(selected_items)},
                    error={"message": str(exc)},
                )
                raise
            self.append_event(
                "invoice.preview_job_created",
                {
                    "job_id": job.job_id,
                    "record_count": job.record_count,
                    "file_count": len(job.files),
                    "renderable_page_count": job.renderable_page_count,
                },
            )
            return self._invoice_preview_payload(job)

    def invoice_preview_page(self, job_id: str, file_number: int, page_number: int):
        return self._file_preview_service.get_page(job_id, file_number, page_number)

    def invoice_preview_text(self, job_id: str, file_number: int):
        return self._file_preview_service.get_text(job_id, file_number)

    def keep_invoice_preview_alive(self, job_id: str) -> dict:
        job = self._file_preview_service.keep_alive(job_id)
        return {
            "ok": True,
            "job_id": job.job_id,
            "expires_at": job.expires_at,
            "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS,
        }

    def _invoice_preview_open_path(self, job_id: str, file_number: int) -> Path:
        entry = self._file_preview_service.get_file(job_id, file_number)
        root = Path(self.active_profile.watch_dir).resolve()
        if not path_is_under_root(entry.path, root):
            raise FilePreviewError(
                "源文件已不在当前发票目录，请重新打开预览。",
                code="source_changed",
                status_code=409,
            )
        return entry.path

    def open_invoice_preview_file(self, job_id: str, file_number: int) -> dict:
        path = self._invoice_preview_open_path(job_id, file_number)
        try:
            open_local_path(path)
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError("系统无法打开该文件。", code="open_failed") from exc
        self.append_event(
            "invoice.preview_file_opened",
            {"job_id": job_id, "file_number": file_number, "file_name": path.name},
        )
        return {"ok": True, "opened": True, "job_id": job_id, "file_number": file_number, "file_name": path.name}

    def open_invoice_preview_location(self, job_id: str, file_number: int) -> dict:
        path = self._invoice_preview_open_path(job_id, file_number)
        try:
            open_local_path(path.parent)
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError("系统无法打开文件所在位置。", code="open_failed") from exc
        self.append_event(
            "invoice.preview_location_opened",
            {"job_id": job_id, "file_number": file_number, "file_name": path.name},
        )
        return {"ok": True, "opened": True, "job_id": job_id, "file_number": file_number, "file_name": path.name}
