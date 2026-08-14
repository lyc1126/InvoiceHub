from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from invoice_hub.services.document_rendering import (
    MuPDFRendererUnavailableError,
    MuPDFRenderingError,
    open_mupdf_document,
    render_mupdf_page,
)


PRINT_DPI = 150
PRINT_JOB_TTL_SECONDS = 15 * 60
MAX_PRINT_SELECTION_RECORDS = 100
MAX_PRINT_PAGES = 200
MAX_PRINT_JOB_BYTES = 128 * 1024 * 1024
MAX_PRINT_CACHE_BYTES = 256 * 1024 * 1024
MAX_PRINT_PAGE_PIXELS = 30_000_000
MAX_PRINT_JOBS = 8
_PRINT_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


class InvoicePrintError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class InvoicePrintSource:
    path: Path
    label: str


@dataclass(frozen=True)
class InvoicePrintPage:
    content: bytes
    orientation: str
    invoice_index: int
    source_page_number: int


@dataclass(frozen=True)
class InvoicePrintJob:
    job_id: str
    created_at: str
    expires_at: str
    expires_monotonic: float
    record_count: int
    invoice_count: int
    collapsed_record_count: int
    format_fallback_count: int
    pages: tuple[InvoicePrintPage, ...]
    total_bytes: int


class InvoicePrintService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, InvoicePrintJob] = {}

    @staticmethod
    def _render_sources(sources: list[InvoicePrintSource]) -> tuple[tuple[InvoicePrintPage, ...], int]:
        rendered: list[InvoicePrintPage] = []
        total_bytes = 0
        for invoice_index, source in enumerate(sources, start=1):
            if not source.path.is_file():
                raise InvoicePrintError(
                    f"发票文件已被移动或删除：{source.label}。请刷新列表后重新勾选。",
                    code="source_missing",
                )
            try:
                with open_mupdf_document(source.path) as document:
                    if len(rendered) + document.page_count > MAX_PRINT_PAGES:
                        raise InvoicePrintError(
                            f"本次打印超过 {MAX_PRINT_PAGES} 页，请减少勾选数量后重试。",
                            code="too_many_pages",
                            status_code=400,
                        )

                    for page_index in range(document.page_count):
                        try:
                            page = render_mupdf_page(
                                document,
                                page_index,
                                dpi=PRINT_DPI,
                                max_pixels=MAX_PRINT_PAGE_PIXELS,
                            )
                        except MuPDFRenderingError as exc:
                            if exc.code == "page_size_unsupported":
                                raise InvoicePrintError(
                                    f"PDF 页面尺寸异常，无法安全准备打印：{source.label}（第 {page_index + 1} 页）。",
                                    code="page_size_unsupported",
                                ) from exc
                            raise
                        total_bytes += len(page.content)
                        if total_bytes > MAX_PRINT_JOB_BYTES:
                            raise InvoicePrintError(
                                "本次打印票面数据过大，请减少勾选数量后重试。",
                                code="job_too_large",
                                status_code=400,
                            )
                        rendered.append(
                            InvoicePrintPage(
                                content=page.content,
                                orientation=page.orientation,
                                invoice_index=invoice_index,
                                source_page_number=page_index + 1,
                            )
                        )
            except InvoicePrintError:
                raise
            except MuPDFRendererUnavailableError as exc:
                raise InvoicePrintError(
                    "PDF 打印组件不可用，请重启系统后重试。",
                    code="renderer_unavailable",
                    status_code=503,
                ) from exc
            except MuPDFRenderingError as exc:
                if exc.code == "document_encrypted":
                    raise InvoicePrintError(
                        f"PDF 已加密，无法准备打印：{source.label}。",
                        code="encrypted_pdf",
                    ) from exc
                if exc.code == "document_empty":
                    raise InvoicePrintError(
                        f"PDF 没有可打印页面：{source.label}。",
                        code="empty_pdf",
                    ) from exc
                raise InvoicePrintError(
                    f"PDF 票面读取失败：{source.label}。请确认文件可以正常打开后重试。",
                    code="pdf_render_failed",
                ) from exc
        return tuple(rendered), total_bytes

    def _remove_expired_locked(self, now: float) -> None:
        expired = [job_id for job_id, job in self._jobs.items() if job.expires_monotonic <= now]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def _make_capacity_locked(self, incoming_bytes: int) -> None:
        def cache_bytes() -> int:
            return sum(job.total_bytes for job in self._jobs.values())

        while self._jobs and (len(self._jobs) >= MAX_PRINT_JOBS or cache_bytes() + incoming_bytes > MAX_PRINT_CACHE_BYTES):
            oldest_id = min(self._jobs, key=lambda job_id: self._jobs[job_id].expires_monotonic)
            self._jobs.pop(oldest_id, None)

    def create_job(
        self,
        sources: list[InvoicePrintSource],
        *,
        record_count: int,
        invoice_count: int,
        collapsed_record_count: int,
        format_fallback_count: int,
    ) -> InvoicePrintJob:
        if not sources:
            raise InvoicePrintError("没有可打印的 PDF 票面。", code="no_printable_sources")
        pages, total_bytes = self._render_sources(sources)
        now = datetime.now(UTC)
        job = InvoicePrintJob(
            job_id=secrets.token_urlsafe(24),
            created_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=PRINT_JOB_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            expires_monotonic=time.monotonic() + PRINT_JOB_TTL_SECONDS,
            record_count=record_count,
            invoice_count=invoice_count,
            collapsed_record_count=collapsed_record_count,
            format_fallback_count=format_fallback_count,
            pages=pages,
            total_bytes=total_bytes,
        )
        with self._lock:
            self._remove_expired_locked(time.monotonic())
            self._make_capacity_locked(total_bytes)
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> InvoicePrintJob:
        if not _PRINT_JOB_ID.fullmatch(str(job_id or "")):
            raise InvoicePrintError(
                "打印作业不存在，请返回首页重新勾选。",
                code="job_not_found",
                status_code=404,
            )
        with self._lock:
            self._remove_expired_locked(time.monotonic())
            job = self._jobs.get(job_id)
        if job is None:
            raise InvoicePrintError(
                "打印作业已过期或不存在，请返回首页重新勾选。",
                code="job_expired",
                status_code=410,
            )
        return job

    def get_page(self, job_id: str, page_number: int) -> InvoicePrintPage:
        job = self.get_job(job_id)
        if page_number < 1 or page_number > len(job.pages):
            raise InvoicePrintError(
                "打印页面不存在。",
                code="page_not_found",
                status_code=404,
            )
        return job.pages[page_number - 1]

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
