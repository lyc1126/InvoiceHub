"""Inbound/outbound document routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from invoice_hub.projections.documents import DocumentError
from invoice_hub.services import (
    StaleInvoiceSelectionError,
)

from invoice_hub.api.common import (
    _require_native_picker_origin,
    _run_native_picker,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/documents/state")
    def documents_state(request: Request, selection_only: bool = False, revalidate: bool = True) -> dict:
        return _state(request).documents.document_state(selection_only=selection_only, revalidate=revalidate)

    @routes.get("/api/v1/documents/index")
    def documents_index_status(request: Request) -> dict:
        return {"ok": True, "index": _state(request)._document_index.status()}

    @routes.post("/api/v1/documents/index/resume")
    def documents_index_resume(request: Request) -> dict:
        return _state(request).documents.document_state(restart=True)

    @routes.post("/api/v1/documents/index/cancel")
    async def documents_index_cancel(request: Request) -> dict:
        payload = await request.json()
        return await run_in_threadpool(_state(request)._document_index.cancel, str(payload.get("job_id") or ""))

    @routes.post("/api/v1/documents/pick-outbound-dir")
    def documents_pick_outbound_dir(request: Request) -> dict:
        _require_native_picker_origin(request)
        return _run_native_picker(_state(request).settings.pick_outbound_invoice_dir)

    @routes.post("/api/v1/documents/validate-outbound-dir")
    async def documents_validate_outbound_dir(request: Request) -> dict:
        return await run_in_threadpool(_state(request).settings.validate_outbound_invoice_dir, await request.json())

    @routes.put("/api/v1/documents/outbound-dir")
    async def documents_update_outbound_dir(request: Request) -> dict:
        return await run_in_threadpool(_state(request).settings.update_outbound_invoice_dir, await request.json())

    @routes.post("/api/v1/documents/recent-outbound-dirs/remove")
    async def documents_remove_recent_outbound_dir(request: Request) -> dict:
        return await run_in_threadpool(_state(request).settings.remove_recent_outbound_invoice_dir, await request.json())

    @routes.put("/api/v1/documents/defaults")
    async def documents_defaults(request: Request) -> dict:
        return _state(request).documents.save_document_defaults(await request.json())

    @routes.get("/api/v1/documents/inbound/preview")
    def documents_inbound_preview(request: Request, invoice_number: str = Query("")) -> dict:
        try:
            return _state(request).documents.document_inbound_preview(invoice_number)
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/inbound/selection")
    async def documents_inbound_selection(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.document_inbound_selection, await request.json())
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/inbound/export-status")
    async def documents_inbound_export_status(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.inbound_document_export_status, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/inbound/export")
    async def documents_inbound_export(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.export_inbound_document, await request.json())
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/inbound/open")
    async def documents_inbound_open(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.open_inbound_document, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/inbound/open-location")
    async def documents_inbound_open_location(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.open_inbound_document_location, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.get("/api/v1/documents/outbound/preview")
    def documents_outbound_preview(request: Request, invoice_number: str = Query("")) -> dict:
        try:
            return _state(request).documents.document_outbound_preview(invoice_number)
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/outbound/export-status")
    async def documents_outbound_export_status(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.outbound_document_export_status, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/outbound/export")
    async def documents_outbound_export(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.export_outbound_document, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/outbound/open")
    async def documents_outbound_open(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.open_outbound_document, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/documents/outbound/open-location")
    async def documents_outbound_open_location(request: Request) -> dict:
        try:
            return await run_in_threadpool(_state(request).documents.open_outbound_document_location, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return routes
