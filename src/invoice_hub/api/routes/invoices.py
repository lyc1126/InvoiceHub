"""Invoice list, selection, trash, preview, print and detail routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from invoice_hub.services.invoice_trash import TrashError
from invoice_hub.services import (
    FilePreviewError,
    InvoicePrintError,
    StaleInvoiceSelectionError,
)

from invoice_hub.api.common import (
    PREVIEW_CONTENT_HEADERS,
    _require_same_origin_write,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/invoices")
    def invoices(request: Request, search_scope: Literal["invoice", "filename", "all"] = "all",
                 page: int | None = Query(None, ge=1), page_size: int = Query(100, ge=1, le=200),
                 date_sort: Literal["", "asc", "desc"] = "") -> dict:
        return _state(request).list_invoices({**dict(request.query_params), "search_scope": search_scope})

    @routes.post("/api/v1/invoices/trash-jobs")
    async def prepare_invoice_trash(request: Request):
        _require_same_origin_write(request)
        try:
            return await run_in_threadpool(_state(request).prepare_invoice_trash, await request.json())
        except (ValueError, OSError, StaleInvoiceSelectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @routes.get("/api/v1/invoices/trash-jobs/{job_id}")
    def invoice_trash_status(request: Request, job_id: str):
        try:
            return _state(request).invoice_trash_status(job_id)
        except TrashError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @routes.post("/api/v1/invoices/trash-jobs/{job_id}/confirm")
    async def commit_invoice_trash(request: Request, job_id: str):
        _require_same_origin_write(request)
        try:
            return await run_in_threadpool(_state(request).commit_invoice_trash, job_id, await request.json())
        except (ValueError, OSError, StaleInvoiceSelectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @routes.post("/api/v1/invoices/selection-summary")
    async def invoice_selection_summary(request: Request) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。")
        try:
            return await run_in_threadpool(_state(request).invoice_selection_summary, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/invoices/preview-jobs")
    async def create_invoice_preview_job(request: Request):
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。", headers=PREVIEW_CONTENT_HEADERS)
        try:
            result = await run_in_threadpool(_state(request).prepare_invoice_preview, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @routes.get("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}")
    def invoice_preview_job_page(request: Request, job_id: str, file_number: int, page_number: int):
        try:
            page = _state(request).invoice_preview_page(job_id, file_number, page_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return Response(
            content=page.content,
            media_type="image/png",
            headers={
                **PREVIEW_CONTENT_HEADERS,
                "X-Preview-Width": str(page.width_pixels),
                "X-Preview-Height": str(page.height_pixels),
                "X-Preview-Orientation": page.orientation,
            },
        )

    @routes.get("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text")
    def invoice_preview_job_text(request: Request, job_id: str, file_number: int):
        try:
            text = _state(request).invoice_preview_text(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return Response(
            content=text.content,
            media_type="text/plain",
            headers={
                **PREVIEW_CONTENT_HEADERS,
                "X-Preview-Encoding": text.encoding,
                "X-Preview-Truncated": "true" if text.truncated else "false",
                "X-Preview-Replacements": "true" if text.had_replacements else "false",
            },
        )

    @routes.post("/api/v1/invoices/preview-jobs/{job_id}/keep-alive")
    def keep_invoice_preview_job_alive(request: Request, job_id: str):
        try:
            result = _state(request).keep_invoice_preview_alive(job_id)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @routes.post("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file")
    def open_invoice_preview_file(request: Request, job_id: str, file_number: int):
        try:
            result = _state(request).open_invoice_preview_file(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @routes.post("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location")
    def open_invoice_preview_location(request: Request, job_id: str, file_number: int):
        try:
            result = _state(request).open_invoice_preview_location(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @routes.post("/api/v1/invoices/print-jobs")
    async def create_invoice_print_job(request: Request) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。")
        try:
            return await run_in_threadpool(_state(request).prepare_invoice_print, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.get("/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}")
    def invoice_print_job_page(request: Request, job_id: str, page_number: int):
        try:
            page = _state(request).invoice_print_page(job_id, page_number)
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return Response(
            content=page.content,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @routes.get("/api/v1/invoices/{invoice_key}")
    def invoice_detail(request: Request, invoice_key: str, source_path: str = "", target_id: str = "") -> dict:
        try:
            state = _state(request)
            with state._lock:
                if source_path or target_id:
                    state._validated_invoice_selection({"target_id": target_id,
                        "items": [{"invoice_key": invoice_key, "source_path": source_path}]},
                        max_items=1, operation="查看")
                return state.invoice_detail(invoice_key)
        except (ValueError, StaleInvoiceSelectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @routes.patch("/api/v1/invoices/{invoice_key}/manual-fields")
    async def manual_fields(request: Request, invoice_key: str) -> dict:
        try:
            payload = await request.json()
            return await run_in_threadpool(_state(request).update_manual_fields, invoice_key, payload)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @routes.post("/api/v1/invoices/{invoice_key}/open-file")
    def open_file(request: Request, invoice_key: str) -> dict:
        try:
            return _state(request).open_invoice_file(invoice_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @routes.post("/api/v1/invoices/{invoice_key}/open-location")
    def open_location(request: Request, invoice_key: str) -> dict:
        try:
            return _state(request).open_invoice_location(invoice_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    return routes
